"""
Playout Engine for Appalachia Radio 3.1.

Non-blocking, frame-based playout engine that emits lifecycle events
and plays audio segments from the queue.

Architecture 3.1 Reference:
- Section 2.2: Playback Engine Is the Metronome
- Section 2.7: Frame-Based Audio Pipeline
- Section 5: Updated Playout Engine Flow (Event-Driven, Intent-Aware)
"""

import json
import logging
import os
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional, Protocol, Dict, Any

import httpx
import numpy as np

from station.broadcast_core.audio_event import AudioEvent
from station.broadcast_core.playout_queue import PlayoutQueue
from station.broadcast_core.ffmpeg_decoder import FFmpegDecoder
from station.broadcast_core.buffer_pid_controller import BufferPIDController
from station.broadcast_core.pcm_output_pipeline import PCMOutputPipeline, FRAME_DURATION_SEC
from station.broadcast_core.segment_decoder import SegmentDecoder
from station.mixer.mixer import Mixer
from station.outputs.base_sink import BaseSink

logger = logging.getLogger(__name__)

# Setup file handler for contract-compliant logging (LOG1, LOG2, LOG3, LOG4)
# Per contract: /var/log/retrowaves/station.log, non-blocking, rotation-tolerant
try:
    import logging.handlers
    # Use WatchedFileHandler for rotation tolerance (per LOG3)
    handler = logging.handlers.WatchedFileHandler('/var/log/retrowaves/station.log', mode='a')
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    # Wrap emit to handle write failures gracefully (per LOG4)
    original_emit = handler.emit
    def safe_emit(record):
        try:
            original_emit(record)
        except (IOError, OSError):
            # Logging failures degrade silently per contract LOG4
            pass
    handler.emit = safe_emit
    # Prevent duplicate handlers on module reload
    if not any(isinstance(h, logging.handlers.WatchedFileHandler)
               and getattr(h, 'baseFilename', None) == '/var/log/retrowaves/station.log'
               for h in logger.handlers):
        logger.addHandler(handler)
    logger.propagate = False  # Avoid duplicate logs
except Exception:
    # Logging must never crash component per LOG4
    # Catch all exceptions (including I/O errors) to prevent import-time failures
    pass


def _get_audio_duration(file_path: str) -> Optional[float]:
    """
    Get the duration of an audio file in seconds using ffprobe.
    
    Returns None if ffprobe fails or file doesn't exist.
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=2.0
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        pass
    return None


def _get_mp3_metadata(file_path: str) -> dict:
    """
    Get MP3 metadata (title, artist, album, duration) using ffprobe.
    
    Returns a dictionary with keys: title, artist, album, duration.
    Missing values will be None.
    
    Uses a single ffprobe call to get both format duration and tags for efficiency.
    
    Args:
        file_path: Path to MP3 file
        
    Returns:
        Dictionary with metadata fields
    """
    metadata = {
        "title": None,
        "artist": None,
        "album": None,
        "duration": None
    }
    
    try:
        # Get both duration and tags in a single ffprobe call for efficiency
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration:format_tags=title:format_tags=artist:format_tags=album",
            "-of", "json",
            file_path
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1.0  # Reduced timeout for faster failure
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                format_info = data.get("format", {})
                
                # Extract duration
                if "duration" in format_info:
                    duration_str = format_info["duration"]
                    if duration_str:
                        metadata["duration"] = float(duration_str)
                
                # Extract tags
                tags = format_info.get("tags", {})
                if "title" in tags:
                    metadata["title"] = tags["title"]
                if "artist" in tags:
                    metadata["artist"] = tags["artist"]
                if "album" in tags:
                    metadata["album"] = tags["album"]
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        pass
    
    return metadata


def _get_segment_metadata(segment: AudioEvent) -> Dict[str, str]:
    """
    Get required segment metadata (segment_class, segment_role, production_type) for non-song segments.
    
    Per EVENT_INVENTORY.md: segment_playing events MUST include these three required fields.
    
    This function extracts metadata from AudioEvent.metadata if present, otherwise infers from segment type.
    Per contract: Metadata MUST be explicit and intentional, never inferred silently.
    However, for backward compatibility during transition, we infer from segment type if not explicitly set.
    
    Args:
        segment: AudioEvent to get metadata for
        
    Returns:
        Dictionary with segment_class, segment_role, production_type
        
    Raises:
        ValueError: If required metadata cannot be determined
    """
    # First, check if metadata is explicitly set in AudioEvent.metadata
    metadata = segment.metadata or {}
    
    segment_class = metadata.get('segment_class')
    segment_role = metadata.get('segment_role')
    production_type = metadata.get('production_type')
    
    # If all three are present, return them
    if segment_class and segment_role and production_type:
        return {
            "segment_class": segment_class,
            "segment_role": segment_role,
            "production_type": production_type
        }
    
    # Otherwise, infer from segment type (for backward compatibility during transition)
    # Per contract: This should eventually be removed once all segments have explicit metadata
    if segment.type == "intro":
        return {
            "segment_class": "dj_talk",
            "segment_role": "intro",
            "production_type": "live_dj"
        }
    elif segment.type == "outro":
        return {
            "segment_class": "dj_talk",
            "segment_role": "outro",
            "production_type": "live_dj"
        }
    elif segment.type == "talk":
        return {
            "segment_class": "dj_talk",
            "segment_role": "interstitial",
            "production_type": "live_dj"
        }
    elif segment.type == "id":
        return {
            "segment_class": "station_id",
            "segment_role": "top_of_hour",
            "production_type": "produced"
        }
    elif segment.type == "announcement":
        # Announcements can be startup or shutdown
        # Default to system-produced standalone announcement
        return {
            "segment_class": "dj_talk",
            "segment_role": "standalone",
            "production_type": "system"
        }
    else:
        # Unknown segment type - fail loudly per contract
        raise ValueError(
            f"Cannot determine segment metadata for segment type '{segment.type}'. "
            f"Required metadata (segment_class, segment_role, production_type) must be explicitly set in AudioEvent.metadata."
        )


class DJCallback(Protocol):
    """
    Protocol for DJ callback object.
    
    The DJ engine should implement this interface to receive
    lifecycle events from the PlayoutEngine.
    
    Architecture 3.1 Reference: Section 5
    """
    
    def on_segment_started(self, segment: AudioEvent) -> None:
        """
        Called when a segment starts playing.
        
        This triggers the Prep Window (THINK phase) where the DJ
        decides what to play next and forms DJIntent.
        
        Architecture 3.1 Reference: Section 3.2 (on_segment_started)
        
        Args:
            segment: The AudioEvent that just started playing
        """
        ...
    
    def on_segment_finished(self, segment: AudioEvent) -> None:
        """
        Called when a segment finishes playing.
        
        This triggers the Transition Window (DO phase) where the DJ
        executes the pre-formed DJIntent.
        
        Architecture 3.1 Reference: Section 3.3 (on_segment_finished)
        
        Args:
            segment: The AudioEvent that just finished playing
        """
        ...


class PlayoutEngine:
    """
    Event-driven playout engine for Architecture 3.2.
    
    Emits lifecycle events:
    - on_segment_started(segment)
    - on_segment_finished(segment)
    
    Uses real audio file durations detected via ffprobe.
    
    Architecture 3.2 Reference: Section 5
    """
    
    def __init__(self, dj_callback: Optional[DJCallback] = None, output_sink: Optional[BaseSink] = None, tower_control: Optional = None):
        """
        Initialize the playout engine.
        
        Args:
            dj_callback: Optional DJ callback object that implements
                        on_segment_started and on_segment_finished methods
            output_sink: Output sink to write audio frames to (required for real audio playback)
            tower_control: Optional TowerControlClient (for PID controller Tower connection)
        """
        self._queue = PlayoutQueue()
        self._dj_callback = dj_callback
        self._output_sink = output_sink
        self._tower_control = tower_control
        self._current_segment: Optional[AudioEvent] = None
        self._is_playing = False
        self._is_running = False
        self._stop_event = threading.Event()
        self._play_thread: Optional[threading.Thread] = None
        self._current_decoder: Optional[FFmpegDecoder] = None  # Track active decoder for PHASE 2 kill
        self._segment_decoder: Optional[SegmentDecoder] = None
        self._pcm_pipeline: Optional[PCMOutputPipeline] = None
        if output_sink is not None:
            queue_size = int(os.getenv("PCM_OUTPUT_QUEUE_SIZE", "100"))
            self._pcm_pipeline = PCMOutputPipeline(output_sink, capacity=queue_size)
        self._mixer = Mixer()
        self._shutdown_requested = False  # Per contract SL2.2: Prevent THINK/DO after shutdown
        self._is_draining = False  # Per contract SL2.2.1: DRAINING state (stop dequeuing, finish current)
        self._terminal_segment_played = False  # Track if terminal segment has been played (per PE7.3)
        self._terminal_do_executed = False  # Track if terminal DO has been executed (per SL2.2, E1.3)
        self._terminal_audio_queued = False  # Track if shutdown announcement was queued by terminal DO
        self._terminal_audio_played = False  # Track if shutdown announcement actually played to EOF (frames emitted)
        self._terminal_playout_complete = False  # Definitive flag: terminal DO executed AND (no audio queued OR audio played)
        self._playout_stopped_event = threading.Event()  # Signal when playout loop has finished
        self._current_segment_is_terminal = False  # Track if currently playing segment is the terminal shutdown announcement
        
        # Removed: _is_in_talking_sequence tracking (dj_talking is deprecated)
        
        # Track segment active state to prevent pre-fill during active playback
        # Per contract C8: Pre-fill MUST NOT affect segment timing or active content
        # Thread-safe lock for _segment_active reads/writes
        self._segment_active_lock = threading.RLock()
        self._segment_active = False  # True while a segment decode session is in progress
        self._decoding_pcm = False    # True only during the PCM decode loop (prefill gate)
        
        # Monitoring: track queue stats for debugging
        self._last_queue_log_time = time.time()
        self._queue_log_interval = 5.0  # Log queue stats every 5 seconds
        
        # Fallback segment durations (in seconds) if we can't detect real duration
        self._default_segment_duration = 180.0  # 3 minutes default for songs
        self._fallback_durations = {
            "song": 180.0,      # 3 minutes
            "intro": 5.0,       # 5 seconds
            "outro": 10.0,      # 10 seconds
            "talk": 30.0,       # 30 seconds
            "id": 5.0,          # 5 seconds
        }
        
        # PE6: Optional PID (disabled when PCM output pump owns pacing)
        tower_host = os.getenv("TOWER_HOST", "127.0.0.1")
        tower_port = int(os.getenv("TOWER_PORT", "8005"))
        pid_enabled = os.getenv("PID_ENABLED", "false").lower() == "true"
        if self._pcm_pipeline is not None and pid_enabled:
            logger.info("PID controller disabled — PCM output pump owns Clock A pacing")
            pid_enabled = False
        
        self._pid_controller: Optional[BufferPIDController] = None
        if pid_enabled:
            self._pid_controller = BufferPIDController(
                tower_host=tower_host,
                tower_port=tower_port,
                enabled=True,
            )
            logger.info("PID controller enabled for adaptive Clock A pacing")
        else:
            logger.info("PID controller disabled - using fixed-rate Clock A pacing")
    
    def set_dj_callback(self, dj_callback: Optional[DJCallback]) -> None:
        """
        Set the DJ callback object.
        
        Args:
            dj_callback: DJ callback object implementing on_segment_started
                        and on_segment_finished methods, or None to disable callbacks
        """
        self._dj_callback = dj_callback
    
    def request_shutdown(self) -> None:
        """
        Request shutdown of the playout engine.
        
        Per contract SL2.2: Prevents new THINK/DO events from firing after shutdown begins.
        This flag is checked before firing callbacks to ensure strict compliance.
        """
        self._shutdown_requested = True
    
    def set_draining(self, is_draining: bool = True) -> None:
        """
        Set draining state (per SL2.2.1, PE7.2).
        
        When draining:
        - Current segment MUST finish completely
        - No new segments MAY be dequeued
        - Exactly one terminal segment MAY play if present
        
        Args:
            is_draining: True to enter DRAINING state
        """
        self._is_draining = is_draining
        if is_draining:
            logger.info("[PLAYOUT] Entering DRAINING state - current segment will finish, no new segments will be dequeued")
    
    def _trigger_terminal_do_if_idle(self) -> None:
        """Queue shutdown announcement when draining begins with nothing actively playing."""
        if not self._is_draining or self._terminal_do_executed or self._is_playing:
            return
        if not self._dj_callback:
            self._terminal_do_executed = True
            logger.warning("[PLAYOUT] DRAINING: No DJ callback — marking terminal DO complete")
            return

        logger.info("[PLAYOUT] DRAINING: No active segment — triggering terminal shutdown DO")
        try:
            idle_segment = AudioEvent(path="", type="song")
            self._dj_callback.on_segment_finished(idle_segment)
            if getattr(self._dj_callback, "_terminal_intent_queued", False):
                self._terminal_do_executed = True
                logger.info("[PLAYOUT] Terminal DO executed (idle drain kick)")
        except Exception as e:
            logger.error(f"[PLAYOUT] Failed to trigger terminal DO while idle: {e}", exc_info=True)

    def queue_audio(self, audio_events: list[AudioEvent]) -> None:
        """
        Queue audio events for playout.
        
        Called during Transition Window to push pre-selected audio.
        
        Architecture 3.1 Reference: Section 4.4
        
        Args:
            audio_events: List of AudioEvents to queue
        """
        self._queue.enqueue_multiple(audio_events)
        logger.info(f"Queued {len(audio_events)} audio event(s)")
        
        # Track if shutdown announcement was queued during DRAINING (terminal DO)
        # Check if any of the queued events is the terminal shutdown announcement
        if self._is_draining:
            for event in audio_events:
                if event and event.is_terminal:
                    self._terminal_audio_queued = True
                    logger.info(f"[PLAYOUT] Terminal shutdown announcement queued - {event.path}")
                    break
    
    def start_segment(self, segment: AudioEvent) -> None:
        """
        Start playing a segment.
        
        Emits on_segment_started callback to trigger DJ Prep Window.
        
        Architecture 3.1 Reference: Section 5
        
        Args:
            segment: AudioEvent to start playing
        """
        if self._is_playing:
            logger.warning(f"Cannot start segment {segment.path}: already playing")
            return
        
        self._current_segment = segment
        self._is_playing = True
        self._segment_start_time = time.monotonic()
        self._current_segment_id = f"{segment.type}_{os.path.basename(segment.path)}_{int(time.monotonic() * 1000)}"
        self._last_progress_event_time = time.monotonic()

        # Start decode first — overlaps logging, HTTP events, and THINK
        self._begin_segment_decode(segment)
        
        # Log intent_id and verify execution order (atomic intent execution tracking)
        intent_id = segment.intent_id if segment.intent_id else None
        if intent_id:
            logger.info(f"Starting segment: intent_id={intent_id}, type={segment.type}, path={segment.path}")
            
            # Verify intent_id matches expected execution order
            # This helps detect cross-intent leakage where segments from previous intents play
            # Note: We can't verify against a "current expected intent" here since intents are consumed,
            # but logging the intent_id allows post-hoc analysis of execution order
            logger.debug(f"[PLAYOUT] Segment intent_id={intent_id} starting - execution order verification")
        else:
            logger.warning(f"Starting segment without intent_id: type={segment.type}, path={segment.path}")
        
        logger.info(f"Starting segment: {segment.type} - {segment.path}")
        
        # Emit appropriate event based on segment type
        # Per contract: Events are edge-triggered transitions only
        # Per EVENT_INVENTORY.md: segment_playing is the only non-song content event
        if self._tower_control and not self._shutdown_requested:
            try:
                if segment.type == "song":
                    # Emit song_playing event (edge-triggered transition)
                    metadata = segment.metadata or {}
                    self._tower_control.send_event(
                        event_type="song_playing",
                        timestamp=time.monotonic(),
                        metadata={
                            "segment_type": segment.type,
                            "file_path": segment.path,
                            "started_at": time.time(),
                            "title": metadata.get('title'),
                            "artist": metadata.get('artist'),
                            "album": metadata.get('album'),
                            "year": metadata.get('year'),
                            "duration_sec": metadata.get('duration'),
                        }
                    )
                else:
                    # Emit segment_playing event for all non-song segments
                    # Per EVENT_INVENTORY.md: segment_playing MUST include required metadata
                    try:
                        segment_metadata = _get_segment_metadata(segment)
                        
                        # Build metadata dict with required fields
                        event_metadata = {
                            "segment_class": segment_metadata["segment_class"],
                            "segment_role": segment_metadata["segment_role"],
                            "production_type": segment_metadata["production_type"],
                        }
                        
                        # Add optional fields if available
                        metadata = segment.metadata or {}
                        if segment.path:
                            event_metadata["file_path"] = segment.path
                        if metadata.get('duration') is not None:
                            event_metadata["duration_sec"] = metadata.get('duration')
                        
                        self._tower_control.send_event(
                            event_type="segment_playing",
                            timestamp=time.monotonic(),
                            metadata=event_metadata
                        )
                    except ValueError as e:
                        # Per contract: Fail loudly if metadata is missing
                        logger.error(
                            f"Contract violation [EVENT_INVENTORY]: Cannot emit segment_playing for segment {segment.path}: {e}. "
                            f"Event emission refused."
                        )
                        # Do not emit event if metadata is missing
            except Exception as e:
                logger.error(f"Error sending event: {e}", exc_info=True)
        
        # Emit on_segment_started callback (THINK phase)
        # Per contract SL2.2: No THINK events MAY fire after shutdown begins
        # Per contract SL2.2: Check both shutdown_requested and callback existence
        if not self._shutdown_requested and self._dj_callback:
            try:
                self._dj_callback.on_segment_started(segment)
            except Exception as e:
                logger.error(f"Error in DJ callback on_segment_started: {e}")
    
    def _set_current_decoder(self, decoder: FFmpegDecoder) -> None:
        self._current_decoder = decoder

    def _begin_segment_decode(self, segment: AudioEvent) -> None:
        """Start background decode for segment (overlaps THINK; feeds PCM output queue)."""
        self._stop_segment_decoder()
        if self._pcm_pipeline is None or not segment.path:
            self._segment_decoder = None
            return
        self._segment_decoder = SegmentDecoder(
            path=segment.path,
            gain=segment.gain,
            mixer=self._mixer,
            pipeline=self._pcm_pipeline,
            on_decoder=self._set_current_decoder,
        )
        self._segment_decoder.start()
        with self._segment_active_lock:
            self._decoding_pcm = True
        logger.debug(f"[PLAYOUT] Background decode started for {segment.path}")

    def _wait_pcm_preroll(self, min_frames: int = 10, timeout_sec: float = 1.0) -> int:
        """Wait until the PCM queue has enough decoded audio before playback is considered live."""
        if self._pcm_pipeline is None:
            return 0
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            depth = self._pcm_pipeline.depth()
            if depth >= min_frames:
                logger.debug(f"[PLAYOUT] PCM preroll ready (depth={depth}, min={min_frames})")
                return depth
            if self._stop_event.is_set() or not self._is_running:
                break
            time.sleep(0.005)
        depth = self._pcm_pipeline.depth()
        if depth < min_frames:
            logger.warning(
                f"[PLAYOUT] PCM preroll timeout (depth={depth}, wanted>={min_frames}, "
                f"timeout={timeout_sec:.1f}s)"
            )
        return depth

    def _wait_pcm_drain(self, timeout_sec: float = 30.0, allow_abort: bool = True) -> bool:
        """Wait until all queued PCM frames have been sent to Tower."""
        if self._pcm_pipeline is None:
            return True
        deadline = time.monotonic() + timeout_sec
        initial_depth = self._pcm_pipeline.depth()
        while self._pcm_pipeline.depth() > 0:
            if allow_abort and (self._stop_event.is_set() or not self._is_running):
                logger.warning(
                    f"[PLAYOUT] PCM drain aborted (depth={self._pcm_pipeline.depth()})"
                )
                return False
            if time.monotonic() >= deadline:
                logger.warning(
                    f"[PLAYOUT] PCM drain timeout (depth={self._pcm_pipeline.depth()}, "
                    f"started_at={initial_depth}, timeout={timeout_sec:.1f}s)"
                )
                return False
            time.sleep(0.005)
        # One more tick so the pump sends the last dequeued frame
        time.sleep(FRAME_DURATION_SEC + 0.01)
        logger.debug(f"[PLAYOUT] PCM drain complete (started_at={initial_depth})")
        return True

    def _stop_segment_decoder(self) -> None:
        if self._segment_decoder is not None:
            try:
                self._segment_decoder.stop()
            except Exception:
                pass
            self._segment_decoder = None
        self._current_decoder = None
        with self._segment_active_lock:
            self._decoding_pcm = False
    
    def finish_segment(self, segment: AudioEvent) -> None:
        """
        Finish playing a segment.
        
        Emits on_segment_finished callback to trigger DJ Transition Window.
        
        Architecture 3.1 Reference: Section 5
        
        Args:
            segment: AudioEvent that finished playing
        """
        if not self._is_playing or self._current_segment != segment:
            logger.warning(f"Cannot finish segment {segment.path}: not currently playing")
            return
        
        logger.info(f"Finishing segment: {segment.type} - {segment.path}")
        
        # Emit on_segment_finished callback (DO phase)
        # Per contract SL2.2, E1.3: Terminal DO MUST be allowed to execute even if shutdown is requested
        # Exception: If draining and terminal DO not yet executed, allow DO to run
        # Otherwise, respect shutdown_requested (no DO events after shutdown, except terminal DO)
        should_allow_do = False
        if self._is_draining and not self._terminal_do_executed:
            # Per SL2.2: Exactly one terminal THINK/DO cycle is permitted during DRAINING
            # We're in DRAINING and terminal DO hasn't executed yet, so allow it
            should_allow_do = True
            logger.info("[PLAYOUT] Allowing terminal DO to execute (draining state, terminal DO not yet executed)")
        elif not self._shutdown_requested:
            # Normal case: not shutdown, allow DO
            should_allow_do = True
        
        if should_allow_do and self._dj_callback:
            try:
                self._dj_callback.on_segment_finished(segment)
                # Check if this was a terminal DO by inspecting DJ engine's state
                # Terminal DO is indicated by terminal intent being queued
                if self._is_draining and hasattr(self._dj_callback, '_terminal_intent_queued'):
                    if self._dj_callback._terminal_intent_queued:
                        self._terminal_do_executed = True
                        logger.info("[PLAYOUT] Terminal DO executed - no further THINK/DO cycles will occur")
                        # Check if shutdown announcement was queued (terminal intent may be empty)
                        # We'll detect this when we try to dequeue the terminal segment
                        # For now, mark that terminal DO executed - terminal event queued will be set when we find it
            except Exception as e:
                logger.error(f"Error in DJ callback on_segment_finished: {e}")
        
        # Clear current segment
        self._current_segment = None
        self._is_playing = False
        
        # Set segment_active = False when segment finishes
        # Per contract C8: Pre-fill MUST NOT execute during active segment playback
        with self._segment_active_lock:
            self._segment_active = False
            self._decoding_pcm = False
    
    def _get_segment_duration(self, segment: AudioEvent) -> float:
        """
        Get the duration for a segment using real audio file duration.
        
        Falls back to type-based defaults if duration cannot be detected.
        
        Args:
            segment: AudioEvent to get duration for
            
        Returns:
            Duration in seconds
        """
        # Try to get real duration from audio file
        real_duration = _get_audio_duration(segment.path)
        if real_duration is not None and real_duration > 0:
            return real_duration
        
        # Fallback to type-based defaults if detection fails
        logger.debug(f"Could not detect duration for {segment.path}, using fallback for type {segment.type}")
        return self._fallback_durations.get(segment.type, self._default_segment_duration)
    
    def _playout_loop(self) -> None:
        """
        Internal playout loop that processes segments from queue.
        
        Decodes audio and sends frames to output sink for real playback.
        
        Per contract SL2.2: No THINK or DO events MAY fire after shutdown begins.
        This loop checks _shutdown_requested at multiple points to ensure strict compliance.
        """
        logger.info("Playout loop started")
        try:
            # Loop continues until: stop event OR terminal playout complete
            # During DRAINING, loop MUST continue until terminal DO executed AND terminal segment (if any) finished
            while self._is_running and not self._stop_event.is_set() and not self._terminal_playout_complete:
                # Periodic queue monitoring (every 5 seconds)
                now = time.time()
                if now - self._last_queue_log_time >= self._queue_log_interval:
                    queue_size = self._queue.size()
                    logger.info(
                        f"[QUEUE_MONITOR] PlayoutQueue: {queue_size} segments waiting"
                    )
                    self._last_queue_log_time = now
                
                # Per contract PE7.2: Stop dequeuing new segments once DRAINING state begins
                # Exception: Allow exactly one terminal segment (shutdown announcement) to be dequeued (per PE7.3)
                if self._is_draining:
                    # If nothing is playing yet, kick terminal DO so sign-off still queues
                    if not self._terminal_do_executed and not self._is_playing:
                        self._trigger_terminal_do_if_idle()

                    # Check if terminal playout is complete: DO executed AND (no audio queued OR audio played)
                    if self._terminal_do_executed:
                        if not self._terminal_audio_queued or self._terminal_audio_played:
                            # Terminal playout complete: DO executed AND (no audio queued OR audio played)
                            self._terminal_playout_complete = True
                            if self._terminal_audio_played:
                                logger.info("[PLAYOUT] DRAINING: Terminal playout complete - shutdown announcement played")
                            else:
                                logger.info("[PLAYOUT] DRAINING: Terminal playout complete - DO executed, no shutdown announcement queued")
                            break
                        # Terminal audio was queued but not yet played - continue to dequeue and play it
                    
                    # During DRAINING: Only dequeue terminal segments (shutdown announcement)
                    # Must NOT dequeue arbitrary queued segments (IDs, intros, songs)
                    segment = self._queue.dequeue()
                    
                    if segment is None:
                        # Queue is empty - wait for terminal DO or terminal audio to be queued
                        if not self._terminal_do_executed:
                            # Waiting for terminal DO
                            logger.debug("[PLAYOUT] DRAINING: Queue empty, waiting for terminal DO...")
                            time.sleep(0.1)
                            continue
                        # Terminal DO executed - check if audio was queued
                        if self._terminal_audio_queued and not self._terminal_audio_played:
                            # Terminal audio was queued but not in queue - this shouldn't happen, but wait a bit
                            logger.debug("[PLAYOUT] DRAINING: Terminal audio queued but not in queue, waiting...")
                            time.sleep(0.1)
                            continue
                        # Terminal DO executed and no audio queued (or already played) - complete
                        self._terminal_playout_complete = True
                        logger.info("[PLAYOUT] DRAINING: Terminal playout complete (DO executed, no shutdown announcement in queue)")
                        break
                    
                    # When draining: discard non-terminal segments, only play terminal shutdown announcement
                    if not segment.is_terminal:
                        logger.info(f"[PLAYOUT] DRAINING: Discarding non-terminal queued segment - {segment.type} - {segment.path}")
                        continue
                    
                    # Terminal segment found - mark that we're about to play it
                    self._current_segment_is_terminal = True
                    # Ensure terminal_audio_queued is set (should already be set when queued, but ensure it)
                    if not self._terminal_audio_queued:
                        self._terminal_audio_queued = True
                        logger.info(f"[PLAYOUT] DRAINING: Terminal audio detected when dequeuing - {segment.path}")
                    logger.info(f"[PLAYOUT] DRAINING: Dequeued terminal shutdown announcement - {segment.path}")
                else:
                    # Not draining - normal dequeuing
                    segment = self._queue.dequeue()
                    self._current_segment_is_terminal = False
                
                if segment is None:
                    # PCM output pump sends silence while queue is empty
                    time.sleep(0.05)
                    continue
                
                # Start the segment (triggers on_segment_started - THINK phase)
                self.start_segment(segment)
                
                # Decode and play the audio segment
                try:
                    frame_count = self._play_audio_segment(segment)
                except Exception as e:
                    logger.error(f"[PLAYOUT] Error playing segment {segment.path}: {e}", exc_info=True)
                    # Don't continue to finish_segment if playback failed
                    continue
                
                # Finish the segment (triggers on_segment_finished - DO phase)
                # finish_segment() will allow terminal DO to execute during DRAINING
                # Note: finish_segment() will verify the segment is still current, so we can call it directly
                self.finish_segment(segment)
                
                # Per contract PE7.3: Mark terminal segment as played ONLY IF:
                # 1. segment.is_terminal == True
                # 2. decoder reached EOF (we're here, so decode finished)
                # 3. frame_count > 0 (frames were actually decoded and written)
                # 
                # Terminal playout completion requires:
                # - terminal_do_executed (DJ decided to shut down)
                # - AND (no_terminal_audio_queued OR terminal_audio_played)
                if self._is_draining and segment.is_terminal and frame_count > 0:
                    # Terminal shutdown announcement actually played to completion (decoded frames and reached EOF)
                    self._terminal_audio_played = True
                    self._terminal_segment_played = True
                    logger.info(f"[PLAYOUT] Terminal shutdown announcement finished (decoded {frame_count} frames to EOF)")
                    
                    # Terminal playout is complete: terminal DO executed AND terminal audio played
                    if self._terminal_do_executed:
                        self._terminal_playout_complete = True
                        logger.info("[PLAYOUT] Terminal playout complete: DO executed and shutdown announcement played to EOF")
                        break
                elif self._is_draining and not segment.is_terminal:
                    # During DRAINING but this wasn't the terminal segment
                    # This should only happen if we're finishing the current song before shutdown announcement
                    logger.debug(f"[PLAYOUT] Segment finished during DRAINING (not terminal): {segment.type}")
                    # Do NOT mark terminal playout complete here - wait for terminal audio to play
        finally:
            # Always signal that playout loop has stopped, regardless of how it exited
            logger.info("Playout loop stopped")
            self._playout_stopped_event.set()
    
    def _get_tower_buffer_status(self) -> Optional[Dict[str, Any]]:
        """
        Get Tower buffer status from /tower/buffer endpoint.
        
        Contract reference: Tower Runtime Contract T-BUF
        
        Returns:
            Buffer status dict with 'capacity', 'count', 'ratio' keys, or None if unavailable
        """
        # Use TowerControlClient if available, otherwise create temporary HTTP client
        if self._tower_control:
            return self._tower_control.get_buffer()
        
        # Fallback: create temporary HTTP client
        tower_host = os.getenv("TOWER_HOST", "127.0.0.1")
        tower_port = int(os.getenv("TOWER_PORT", "8005"))
        url = f"http://{tower_host}:{tower_port}/tower/buffer"
        
        try:
            with httpx.Client(timeout=0.1) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            # Log HTTP errors at warning level (but don't spam if Tower is down)
            # Only log periodically to avoid log spam
            import random
            if random.random() < 0.1:  # Log ~10% of errors to avoid spam
                logger.warning(f"[PREFILL] Failed to get buffer status from Tower: {e}")
            return None
        except Exception as e:
            # Log unexpected errors at warning level (but don't spam)
            import random
            if random.random() < 0.1:  # Log ~10% of errors to avoid spam
                logger.warning(f"[PREFILL] Unexpected error getting buffer status: {e}")
            return None
    
    def _get_buffer_ratio(self, buffer_status: Dict[str, Any]) -> float:
        """
        Calculate buffer fill ratio from buffer status.
        
        Args:
            buffer_status: Buffer status dict from /tower/buffer
        
        Returns:
            Buffer fill ratio (0.0-1.0)
        """
        if "ratio" in buffer_status:
            return max(0.0, min(1.0, float(buffer_status["ratio"])))
        
        # Calculate from fill/capacity or count/capacity if ratio not provided
        fill = buffer_status.get("fill")
        if fill is None:
            fill = buffer_status.get("count", 0)
        capacity = buffer_status.get("capacity", 1)
        if capacity > 0:
            return max(0.0, min(1.0, float(fill) / float(capacity)))
        
        return 0.0
    
    _FRAME_DURATION_SEC = 1024.0 / 48000.0

    def _send_idle_keepalive_frame(self) -> None:
        """Feed Tower silence at ~real-time while the queue is empty (DJ THINK/DO)."""
        if not self._output_sink:
            time.sleep(0.1)
            return
        silence = np.zeros((1024, 2), dtype=np.int16)
        try:
            self._output_sink.write(silence)
        except Exception:
            pass
        time.sleep(self._FRAME_DURATION_SEC)
    
    def _run_prefill_if_needed(
        self,
        segment: AudioEvent,
        start_time: float,
        next_frame_time: float,
    ) -> bool:
        """
        Run pre-fill stage if Tower buffer is below target threshold.
        
        Contract reference: Station–Tower PCM Bridge Contract C8 Pre-Fill Stage
        
        Pre-fill behavior:
        - Checks Tower buffer status via /tower/buffer endpoint
        - If buffer ratio < target (e.g., < 0.5), enters pre-fill mode
        - Sends NON-PROGRAM PCM (silence/tone) frames as fast as possible (no Clock A sleep)
        - Monitors buffer fill level periodically
        - Exits when buffer reaches target or timeout elapses
        
        Pre-fill MUST NOT:
        - Decode program audio (segment file)
        - Touch the decoder
        - Advance file position
        - Segment state queryable via /station/state endpoint (authoritative)
        - Make program audio audible
        - Change segment timing logic (elapsed = time.monotonic() - segment_start)
        - Reset or manipulate Clock A's internal next_frame_time
        - Introduce any pacing on socket writes (writes remain immediate + non-blocking)
        - Execute during active segment playback (per C8: MUST NOT affect active content)
        
        Pre-fill MUST:
        - Use fallback PCM (silence/tone) only
        - Warm Tower buffer without audible program leak
        - Preserve segment semantics (start from position 0 after pre-fill)
        - Only execute when NO segment is actively playing
        
        Args:
            segment: AudioEvent being played (used for logging only, NOT decoded)
            start_time: Segment start time (Clock A baseline, MUST NOT be modified)
            next_frame_time: Clock A's next_frame_time (MUST NOT be modified)
        
        Returns:
            True if pre-fill was executed, False if skipped
        """
        # C8: Pre-fill MUST NOT execute during program PCM decode
        with self._segment_active_lock:
            decoding = self._decoding_pcm
            current_seg_type = self._current_segment.type if self._current_segment else "unknown"
            current_seg_path = self._current_segment.path if self._current_segment else "unknown"
        
        if decoding:
            logger.debug(
                f"[PREFILL-SILENCE] Skipped — decode in progress (type={current_seg_type}, path={current_seg_path})"
            )
            return False
        
        # SS5.1: Suppress pre-fill only while startup announcement PCM is actively decoding
        if hasattr(self, '_station_startup_state_getter'):
            startup_state = self._station_startup_state_getter()
            if startup_state in ("STARTUP_ANNOUNCEMENT_PLAYING", "STARTUP_THINK_COMPLETE"):
                with self._segment_active_lock:
                    if self._decoding_pcm:
                        logger.debug(
                            f"[PREFILL-SILENCE] Skipped — startup announcement decode in progress (SS5.1)"
                        )
                        return False
        
        # SD5.1, SD5.2: Pre-fill MUST be suppressed during DRAINING state
        # SD5.1: Pre-fill silence injection MUST NOT occur while the shutdown announcement is playing
        # SD5.2: Pre-fill MUST be suppressed throughout the DRAINING state
        if self._is_draining:
            logger.warning("[PREFILL-SILENCE] Skipped — DRAINING state (SD5.2)")
            return False
        
        # SD5.1: Pre-fill MUST NOT occur while the shutdown announcement is playing
        # Check if a shutdown announcement is currently active (segment is playing and is terminal)
        with self._segment_active_lock:
            decoding = self._decoding_pcm
        if decoding and self._current_segment_is_terminal:
            current_seg_type = self._current_segment.type if self._current_segment else "unknown"
            current_seg_path = self._current_segment.path if self._current_segment else "unknown"
            logger.warning(
                f"[PREFILL-SILENCE] Skipped — shutdown announcement playing (SD5.1) "
                f"(type={current_seg_type}, path={current_seg_path})"
            )
            return False
        
        # SD5.1: Also suppress prefill before shutdown announcement starts (defensive check)
        # Check if the segment about to play is a shutdown announcement
        if segment and hasattr(segment, 'is_terminal') and segment.is_terminal and segment.type == "announcement":
            logger.warning("[PREFILL-SILENCE] Skipped — shutdown announcement about to start (SD5.1)")
            return False
        
        # C8: Pre-fill is optional and implementation-defined
        # Check if pre-fill should run
        prefill_enabled = os.getenv("PREFILL_ENABLED", "true").lower() == "true"
        if not prefill_enabled:
            return False
        
        # C8: Check Tower buffer status via /tower/buffer endpoint
        buffer_status = self._get_tower_buffer_status()
        if buffer_status is None:
            # C8: If endpoint unavailable, skip pre-fill and fall back to normal pacing
            logger.debug("[PREFILL-SILENCE] Tower buffer endpoint unavailable, skipping pre-fill")
            return False
        
        # Calculate buffer ratio
        ratio = self._get_buffer_ratio(buffer_status)
        
        # C8: Configurable pre-fill parameters with validation
        target_ratio = float(os.getenv("PREFILL_TARGET_RATIO", "0.5"))
        target_ratio = max(0.1, min(0.9, target_ratio))  # Enforce sane bounds (0.1-0.9)
        
        prefill_timeout = float(os.getenv("PREFILL_TIMEOUT_SEC", "0.25"))
        prefill_timeout = max(0.1, min(30.0, prefill_timeout))
        
        # C8: If ratio >= target, skip pre-fill
        if ratio >= target_ratio:
            logger.debug(f"[PREFILL-SILENCE] Buffer ratio {ratio:.3f} >= target {target_ratio}, skipping pre-fill")
            return False
        
        capacity = int(buffer_status.get("capacity", 100) or 100)
        fill = buffer_status.get("count", buffer_status.get("fill", 0)) or 0
        frames_needed = max(1, int(capacity * target_ratio) - int(fill))
        max_burst = min(frames_needed, 50, int(capacity * 0.9))
        
        prefill_start_time = time.monotonic()
        time_to_segment_start = abs(prefill_start_time - start_time)
        if time_to_segment_start <= 0.250:
            logger.warning(
                f"[PREFILL-SILENCE] Pre-fill starting within ±250ms of segment start "
                f"(time_to_start={time_to_segment_start*1000:.1f}ms, buffer_ratio={ratio:.3f} < target={target_ratio})"
            )
        
        logger.info(
            f"[PREFILL-SILENCE] Starting pre-fill burst "
            f"(buffer ratio {ratio:.3f} < target {target_ratio}, burst_frames={max_burst})"
        )
        frame_count = 0
        silence_frame = np.zeros((1024, 2), dtype=np.int16)
        
        try:
            for _ in range(max_burst):
                if self._shutdown_requested or not self._is_running or self._stop_event.is_set():
                    break
                with self._segment_active_lock:
                    if self._decoding_pcm:
                        break
                if time.monotonic() - prefill_start_time >= prefill_timeout:
                    break
                try:
                    if hasattr(self._output_sink, "write_unpaced"):
                        self._output_sink.write_unpaced(silence_frame)
                    else:
                        self._output_sink.write(silence_frame)
                    frame_count += 1
                except Exception as e:
                    logger.error(f"[PREFILL-SILENCE] Error writing silence frame: {e}", exc_info=True)
            
            prefill_duration = time.monotonic() - prefill_start_time
            # Calculate total duration in milliseconds for clarity
            total_duration_ms = prefill_duration * 1000
            # Calculate frame duration (each frame is ~21.333ms at 48kHz)
            frame_duration_ms = 1024.0 / 48000.0 * 1000  # ~21.333ms per frame
            expected_duration_ms = frame_count * frame_duration_ms
            logger.info(
                f"[PREFILL-SILENCE] Pre-fill complete "
                f"(frames={frame_count}, duration={prefill_duration:.3f}s, total_duration={total_duration_ms:.1f}ms, "
                f"expected_duration={expected_duration_ms:.1f}ms)"
            )
            return True  # Pre-fill executed
            
        except Exception as e:
            elapsed = time.monotonic() - prefill_start_time if 'prefill_start_time' in locals() else 0.0
            logger.error(
                f"[PREFILL-SILENCE] Error during pre-fill "
                f"(frames={frame_count if 'frame_count' in locals() else 0}, duration={elapsed:.3f}s): {e}",
                exc_info=True
            )
            return True  # Pre-fill attempted
    
    def _play_audio_segment(self, segment: AudioEvent) -> int:
        """
        Wait for background segment decode to finish.

        PCM is sent continuously by PCMOutputPipeline — this method only waits for
        the decode worker and tracks segment completion.
        """
        if not self._output_sink:
            logger.warning("No output sink configured - cannot play audio")
            duration = self._get_segment_duration(segment)
            logger.debug(f"Simulating playback for {duration:.1f} seconds (no sink)")
            time.sleep(duration)
            return 0

        expected_duration = self._get_segment_duration(segment)
        logger.info(f"[PLAYOUT] Playing: {segment.path} (expected duration: {expected_duration:.1f}s)")

        start_time = time.monotonic()

        if self._segment_decoder is None:
            self._begin_segment_decode(segment)

        preroll_depth = self._wait_pcm_preroll(min_frames=10, timeout_sec=1.0)
        if preroll_depth == 0 and self._segment_decoder is not None:
            self._wait_pcm_preroll(min_frames=1, timeout_sec=2.0)

        decoder_task = self._segment_decoder
        if decoder_task is None:
            logger.error(f"[PLAYOUT] No decode worker for {segment.path}")
            return 0

        with self._segment_active_lock:
            self._segment_active = True

        try:
            while not decoder_task.exhausted:
                if self._is_draining:
                    if not self._is_running:
                        logger.warning(
                            f"[PLAYOUT] Segment ended early during DRAINING: reason=explicit_hard_stop, "
                            f"path={segment.path}"
                        )
                        decoder_task.stop()
                        break
                else:
                    if self._shutdown_requested or not self._is_running or self._stop_event.is_set():
                        logger.info(
                            f"[PLAYOUT] Stopping playback early: reason=normal_shutdown, path={segment.path}"
                        )
                        decoder_task.stop()
                        break
                time.sleep(0.005)

            if decoder_task.error is not None:
                raise decoder_task.error

            frame_count = decoder_task.frames_pushed
            drain_timeout = max(expected_duration * 1.5, 30.0)
            allow_drain_abort = not (self._is_draining and segment.is_terminal)
            self._wait_pcm_drain(timeout_sec=drain_timeout, allow_abort=allow_drain_abort)

            total_time = time.monotonic() - start_time
            expected_frames = max(1, int(expected_duration / FRAME_DURATION_SEC))

            if frame_count == 0:
                logger.warning(f"[PLAYOUT] Segment produced no frames: {segment.path}")
            elif frame_count < expected_frames * 0.95:
                logger.warning(
                    f"[PLAYOUT] Segment ended early: {segment.path} "
                    f"({frame_count} frames, expected ~{expected_frames}, "
                    f"wall={total_time:.1f}s, audio={expected_duration:.1f}s)"
                )
            else:
                logger.info(
                    f"[PLAYOUT] Finished {segment.path} "
                    f"({frame_count} frames, wall={total_time:.1f}s, "
                    f"expected {expected_duration:.1f}s, pcm_queue={self._pcm_pipeline.depth() if self._pcm_pipeline else 0})"
                )

            return frame_count

        except FileNotFoundError:
            logger.error(f"[PLAYOUT] Audio file not found: {segment.path}")
            raise
        except Exception as e:
            logger.error(f"[PLAYOUT] Error playing {segment.path}: {e}", exc_info=True)
            raise
        finally:
            with self._segment_active_lock:
                self._segment_active = False
            self._stop_segment_decoder()
    
    def run(self) -> None:
        """
        Run the playout engine main loop.
        
        Continuously plays segments from queue and emits events.
        Architecture 3.1 Reference: Section 5
        """
        if self._is_running:
            logger.warning("Playout engine is already running")
            return
        
        logger.info("Starting playout engine")
        self._is_running = True
        self._stop_event.clear()
        self._playout_stopped_event.clear()  # Reset stopped event for new run
        # Reset terminal flags for new run
        self._terminal_segment_played = False
        self._terminal_do_executed = False
        self._terminal_audio_queued = False
        self._terminal_audio_played = False
        self._terminal_playout_complete = False
        self._current_segment_is_terminal = False
        self._current_decoder = None  # Clear decoder reference on new run
        
        if self._pcm_pipeline is not None:
            self._pcm_pipeline.start()
        
        # Start playout loop in background thread
        self._play_thread = threading.Thread(target=self._playout_loop, daemon=True)
        self._play_thread.start()
    
    def stop(self) -> None:
        """
        Stop the playout engine gracefully.
        
        Waits for current segment to finish, then stops.
        
        Per PHASE 2 requirements: Kills all FFmpeg subprocesses to prevent orphaned processes
        when systemd uses KillMode=process.
        """
        if not self._is_running:
            return
        
        logger.info("Stopping playout engine")
        self._is_running = False
        self._stop_event.set()
        
        self._stop_segment_decoder()
        
        # PHASE 2: Kill active FFmpeg decoder to ensure no orphaned processes
        # This is safe because stop() is only called during PHASE 2 (SHUTTING_DOWN)
        if self._current_decoder is not None:
            logger.info("[PLAYOUT] PHASE 2: Killing active FFmpeg decoder to prevent orphaned processes")
            try:
                self._current_decoder.kill(grace_period_seconds=2.0)
            except Exception as e:
                logger.error(f"[PLAYOUT] Error killing FFmpeg decoder during PHASE 2: {e}", exc_info=True)
            finally:
                self._current_decoder = None
        
        # Wait for playout thread to finish (per SL2.3.3: all threads must join within timeout)
        # Use longer timeout to allow current segment to finish (matches Station shutdown timeout)
        if self._play_thread and self._play_thread.is_alive():
            # Use a reasonable timeout (60 seconds) to allow long segments to finish
            # Station.stop() will enforce its own max-wait timeout
            self._play_thread.join(timeout=60.0)
            if self._play_thread.is_alive():
                logger.warning("Playout thread did not stop within timeout (60s)")
                # If thread is still alive, try to kill decoder one more time (defensive)
                if self._current_decoder is not None:
                    logger.warning("[PLAYOUT] PHASE 2: Thread timeout - attempting to kill decoder again")
                    try:
                        self._current_decoder.kill(grace_period_seconds=1.0)
                    except Exception:
                        pass
                    self._current_decoder = None
        
        if self._pcm_pipeline is not None:
            self._wait_pcm_drain(timeout_sec=15.0, allow_abort=False)
            self._pcm_pipeline.stop()
        
        logger.info("Playout engine stopped")
    
    def wait_for_playout_stopped(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for the playout loop to stop.
        
        This provides a reliable signal that the playout loop has finished,
        regardless of how it exited (normal completion, shutdown, error, etc.).
        
        Args:
            timeout: Maximum time to wait in seconds (None = wait indefinitely)
        
        Returns:
            True if playout stopped within timeout, False if timeout exceeded
        """
        return self._playout_stopped_event.wait(timeout=timeout)
    
    def is_playing(self) -> bool:
        """
        Check if a segment is currently playing.
        
        Returns:
            True if a segment is playing, False otherwise
        """
        return self._is_playing
    
    def get_current_segment(self) -> Optional[AudioEvent]:
        """
        Get the currently playing segment.
        
        Returns:
            Current AudioEvent or None if not playing
        """
        return self._current_segment
    
    def queue_size(self) -> int:
        """
        Get the number of segments waiting in the queue.
        
        Returns:
            Number of AudioEvents in queue
        """
        return self._queue.size()
