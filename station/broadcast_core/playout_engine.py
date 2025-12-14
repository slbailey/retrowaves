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
        
        # Track talking state to avoid multiple dj_talking events for consecutive talk files
        self._is_in_talking_sequence = False
        
        # Track segment active state to prevent pre-fill during active playback
        # Per contract C8: Pre-fill MUST NOT affect segment timing or active content
        # Thread-safe lock for _segment_active reads/writes
        self._segment_active_lock = threading.RLock()
        self._segment_active = False
        
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
        
        # PE6: Optional PID controller for adaptive Clock A pacing
        # Initialize PID controller (enabled by default, can be disabled via config)
        import os
        tower_host = os.getenv("TOWER_HOST", "127.0.0.1")
        tower_port = int(os.getenv("TOWER_PORT", "8005"))
        pid_enabled = os.getenv("PID_ENABLED", "true").lower() == "true"
        
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
        
        # Set segment_active = True at the segment commit boundary
        # This MUST occur immediately when segment is committed for playback, before:
        # - any prefill check
        # - any buffer warmup logic
        # - any decode setup
        # Per contract C8: Pre-fill MUST NOT execute during active segment playback
        # _segment_active remains True until decode completes AND segment teardown completes
        with self._segment_active_lock:
            self._segment_active = True
        
        # Emit appropriate event based on segment type
        # Removed: superseded by now_playing authoritative state
        # See NEW_NOW_PLAYING_STATE_CONTRACT.md for authoritative segment state
        if self._tower_control and not self._shutdown_requested:
            try:
                if segment.type == "song":
                    # Reset talking sequence flag when a song starts
                    # Segment state is now emitted via now_playing event (authoritative)
                    self._is_in_talking_sequence = False
                elif segment.type in ("intro", "outro", "talk"):
                    # Emit dj_talking event when DJ talking segments start
                    # DJ talking encompasses: intro, outro, and talk segment types
                    # Only emit once even if multiple talking files are strung together
                    if not self._is_in_talking_sequence:
                        self._tower_control.send_event(
                            event_type="dj_talking",
                            timestamp=time.monotonic(),
                            metadata={}
                        )
                        self._is_in_talking_sequence = True
                else:
                    # Reset talking sequence flag when any non-talking, non-song segment starts
                    # (e.g., id) so that if talking segments come after, we emit dj_talking again
                    self._is_in_talking_sequence = False
            except Exception as e:
                logger.debug(f"Error sending event: {e}")
        
        # Emit on_segment_started callback (THINK phase)
        # Per contract SL2.2: No THINK events MAY fire after shutdown begins
        # Per contract SL2.2: Check both shutdown_requested and callback existence
        if not self._shutdown_requested and self._dj_callback:
            try:
                self._dj_callback.on_segment_started(segment)
            except Exception as e:
                logger.error(f"Error in DJ callback on_segment_started: {e}")
    
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
                    # Queue is empty, wait a bit before checking again
                    time.sleep(0.1)
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
        
        # Calculate from fill/capacity if ratio not provided
        fill = buffer_status.get("fill", 0)
        capacity = buffer_status.get("capacity", 1)
        if capacity > 0:
            return max(0.0, min(1.0, float(fill) / float(capacity)))
        
        return 0.0
    
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
        - Segment state emitted via now_playing event (authoritative)
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
        # C8: Pre-fill MUST NOT execute during active segment playback
        # Gate all pre-fill entry points to prevent silence injection mid-segment
        # Read _segment_active under lock for thread safety
        with self._segment_active_lock:
            segment_active = self._segment_active
            current_seg_type = self._current_segment.type if self._current_segment else "unknown"
            current_seg_path = self._current_segment.path if self._current_segment else "unknown"
        
        if segment_active:
            logger.warning(
                f"[PREFILL-SILENCE] Skipped — segment active (type={current_seg_type}, path={current_seg_path})"
            )
            return False
        
        # SS5.1: Pre-fill MUST NOT run during any startup state where a segment is active
        # SS5.1: Pre-fill MUST NOT run during STARTUP_ANNOUNCEMENT_PLAYING
        # SS5.1: Pre-fill MUST NOT inject silence during startup announcement playback
        if hasattr(self, '_station_startup_state_getter'):
            startup_state = self._station_startup_state_getter()
            if startup_state != "NORMAL_OPERATION":
                logger.warning(f"[PREFILL-SILENCE] Skipped — startup state {startup_state} (SS5.1)")
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
            segment_active = self._segment_active
        if segment_active and self._current_segment_is_terminal:
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
        
        prefill_timeout = float(os.getenv("PREFILL_TIMEOUT_SEC", "5.0"))
        prefill_timeout = max(1.0, min(30.0, prefill_timeout))  # Enforce sane bounds (1-30s)
        
        prefill_poll_interval = float(os.getenv("PREFILL_POLL_INTERVAL_SEC", "0.1"))
        prefill_poll_interval = max(0.05, min(1.0, prefill_poll_interval))  # Enforce sane bounds (50ms-1s)
        
        # C8: If ratio >= target, skip pre-fill
        if ratio >= target_ratio:
            logger.debug(f"[PREFILL-SILENCE] Buffer ratio {ratio:.3f} >= target {target_ratio}, skipping pre-fill")
            return False
        
        # C8: Enter pre-fill mode - send NON-PROGRAM PCM (silence) frames as fast as possible
        # Pre-fill MUST NOT decode program audio or touch the decoder
        # Pre-fill uses fallback PCM (silence/tone) to warm Tower buffer
        prefill_start_time = time.monotonic()
        
        # Check if pre-fill occurs within ±250ms of segment start
        time_to_segment_start = abs(prefill_start_time - start_time)
        if time_to_segment_start <= 0.250:  # 250ms = 0.25 seconds
            logger.warning(
                f"[PREFILL-SILENCE] Pre-fill starting within ±250ms of segment start "
                f"(time_to_start={time_to_segment_start*1000:.1f}ms, buffer_ratio={ratio:.3f} < target={target_ratio})"
            )
        
        logger.info(
            f"[PREFILL-SILENCE] Starting pre-fill with silence "
            f"(buffer ratio {ratio:.3f} < target {target_ratio}, time_to_segment_start={time_to_segment_start*1000:.1f}ms)"
        )
        frame_count = 0
        last_poll_time = prefill_start_time
        
        # C8: Safety limit - don't pre-fill indefinitely
        # Limit to ~10 seconds of audio (approximately 470 frames at 48kHz)
        max_prefill_frames = int(10.0 * 48000.0 / 1024.0)  # ~470 frames = ~10 seconds
        
        # Generate silence frame: 1024 samples × 2 channels, int16, all zeros
        # Format matches decoder output: numpy array shape (1024, 2), dtype int16
        silence_frame = np.zeros((1024, 2), dtype=np.int16)
        
        try:
            while True:
                # Check shutdown
                if self._shutdown_requested or not self._is_running or self._stop_event.is_set():
                    elapsed = time.monotonic() - prefill_start_time
                    logger.info(
                        f"[PREFILL-SILENCE] Stopping pre-fill early (shutdown requested) "
                        f"(frames={frame_count}, duration={elapsed:.3f}s, total_duration={elapsed*1000:.1f}ms)"
                    )
                    break
                
                # C8: Continuously check if segment became active during prefill loop
                # This prevents prefill from continuing if segment starts decoding mid-prefill
                with self._segment_active_lock:
                    segment_active = self._segment_active
                    if segment_active:
                        current_seg_type = self._current_segment.type if self._current_segment else "unknown"
                        current_seg_path = self._current_segment.path if self._current_segment else "unknown"
                        elapsed = time.monotonic() - prefill_start_time
                        logger.warning(
                            f"[PREFILL-SILENCE] Stopping pre-fill early — segment became active "
                            f"(type={current_seg_type}, path={current_seg_path}, "
                            f"frames={frame_count}, duration={elapsed:.3f}s, total_duration={elapsed*1000:.1f}ms)"
                        )
                        break
                
                # C8: Safety check - don't pre-fill indefinitely
                if frame_count >= max_prefill_frames:
                    elapsed = time.monotonic() - prefill_start_time
                    logger.info(
                        f"[PREFILL-SILENCE] Pre-fill frame limit reached "
                        f"(frames={frame_count}/{max_prefill_frames}, duration={elapsed:.3f}s, total_duration={elapsed*1000:.1f}ms)"
                    )
                    break
                
                # C8: Check timeout
                elapsed = time.monotonic() - prefill_start_time
                if elapsed >= prefill_timeout:
                    logger.warning(
                        f"[PREFILL-SILENCE] Pre-fill timeout reached "
                        f"(frames={frame_count}, duration={elapsed:.3f}s, total_duration={elapsed*1000:.1f}ms, timeout={prefill_timeout}s)"
                    )
                    break
                
                # C8: Poll buffer status periodically (every ~50-100ms)
                now = time.monotonic()
                if now - last_poll_time >= prefill_poll_interval:
                    buffer_status = self._get_tower_buffer_status()
                    if buffer_status is not None:
                        ratio = self._get_buffer_ratio(buffer_status)
                        # C8: Exit pre-fill when buffer reaches target
                        if ratio >= target_ratio:
                            elapsed = time.monotonic() - prefill_start_time
                            logger.info(
                                f"[PREFILL-SILENCE] Buffer target reached, pre-fill complete "
                                f"(frames={frame_count}, duration={elapsed:.3f}s, total_duration={elapsed*1000:.1f}ms, "
                                f"buffer_ratio={ratio:.3f} >= target={target_ratio})"
                            )
                            break
                    last_poll_time = now
                
                # C8: Write silence frame immediately (no sleep, no pacing, no decoder, no program audio)
                # Pre-fill MUST NOT affect segment timing or Clock A timeline
                # Pre-fill MUST NOT emit events or touch decoder
                try:
                    # Write silence frame directly (no gain applied, no mixer - it's silence)
                    self._output_sink.write(silence_frame)
                    frame_count += 1
                except Exception as e:
                    elapsed = time.monotonic() - prefill_start_time
                    logger.error(
                        f"[PREFILL-SILENCE] Error writing silence frame "
                        f"(frame_count={frame_count}, duration={elapsed:.3f}s): {e}",
                        exc_info=True
                    )
                    # Continue even if write fails (non-blocking behavior)
            
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
        Decode and play an audio segment.
        
        ARCHITECTURAL INVARIANT: Station uses Clock A (decode metronome) for local playback correctness.
        Station paces consumption of decoded PCM frames to ensure songs play at real duration.
        Station MUST NOT: attempt Tower-synchronized pacing, observe Tower state, or alter pacing
        based on socket success/failure.
        
        Station pushes PCM frames into the Unix domain socket immediately after decode pacing.
        Tower is the ONLY owner of broadcast timing (AudioPump @ 21.333ms - Clock B).
        
        Args:
            segment: AudioEvent to play
        """
        if not self._output_sink:
            logger.warning("No output sink configured - cannot play audio")
            # Fall back to simulated playback (minimal timing for simulation only)
            duration = self._get_segment_duration(segment)
            logger.debug(f"Simulating playback for {duration:.1f} seconds (no sink)")
            time.sleep(duration)
            return 0
        
        # Get expected duration for logging
        expected_duration = self._get_segment_duration(segment)
        logger.info(f"[PLAYOUT] Decoding and playing: {segment.path} (expected duration: {expected_duration:.1f}s)")
        
        start_time = time.monotonic()  # Use monotonic clock for Clock A
        frame_count = 0
        
        # Clock A: Decode pacing metronome
        # Target: ~21.333 ms per 1024-sample frame (1024 samples / 48000 Hz)
        FRAME_DURATION = 1024.0 / 48000.0  # ~0.021333 seconds
        next_frame_time = start_time  # Initialize Clock A timeline
        
        decoder: Optional[FFmpegDecoder] = None
        try:
            # Create decoder for this segment
            # Note: decoder.read_frames() handles cleanup automatically via finally block
            decoder = FFmpegDecoder(segment.path, frame_size=1024)
            logger.debug(f"[PLAYOUT] FFmpegDecoder created for {segment.path}")
            
            # C8: Pre-Fill Stage - build up Tower buffer before normal pacing
            # Pre-fill MUST NOT affect Clock A timeline or segment timing
            # Pre-fill uses NON-PROGRAM PCM (silence/tone) only - does NOT decode segment
            # After pre-fill, normal decode loop starts from position 0 with Clock A + PID pacing
            # Note: _segment_active is already True (set in start_segment at commit boundary)
            # Pre-fill will check _segment_active and skip immediately, preventing silence injection
            prefill_executed = self._run_prefill_if_needed(segment, start_time, next_frame_time)
            
            # Safeguard: Ensure _segment_active is True before decoding begins
            # (Already set in start_segment, but this ensures it's set even if start_segment wasn't called)
            with self._segment_active_lock:
                if not self._segment_active:
                    logger.warning("[PLAYOUT] _segment_active was False before decode - setting as safeguard")
                    self._segment_active = True
            
            # C8: Pre-fill does NOT touch the decoder, so we create it fresh here
            # Decoder starts from position 0 (beginning of file) after pre-fill completes
            # This ensures no program audio leak and clean segment semantics
            # Close the pre-prefill decoder and create the actual decoder
            if decoder:
                decoder.close()
            decoder = FFmpegDecoder(segment.path, frame_size=1024)
            # Track current decoder for PHASE 2 kill (thread-safe: only accessed from playout thread)
            self._current_decoder = decoder
            if prefill_executed:
                logger.debug(f"[PLAYOUT] FFmpegDecoder created after pre-fill (starting from position 0)")
            else:
                logger.debug(f"[PLAYOUT] FFmpegDecoder created for {segment.path}")
            
            # _segment_active is already True (set in start_segment), ensuring prefill cannot run during decoding
            
            # Decode and write frames with Clock A pacing
            # Clock A paces consumption to ensure real-time playback duration
            # Socket writes fire immediately (non-blocking, no pacing on writes)
            for frame in decoder.read_frames():
                # During DRAINING: Current segment MUST be atomic - play to completion
                # Only allowed early-exit reasons: explicit hard stop (PHASE 2) or shutdown timeout safety
                # DO NOT break for: shutdown_requested, stop_event, or any other reason
                if self._is_draining:
                    # DRAINING: Only stop if _is_running is False (explicit hard stop from PHASE 2)
                    # This is the ONLY allowed early-exit reason during DRAINING
                    # stop_event and shutdown_requested are IGNORED during DRAINING to allow completion
                    if not self._is_running:
                        expected_duration = self._get_segment_duration(segment)
                        logger.warning(f"[PLAYOUT] Segment ended early during DRAINING: reason=explicit_hard_stop, frames={frame_count}, expected_duration={expected_duration:.1f}s")
                        break
                    # Continue decoding - current segment must play to completion during DRAINING
                else:
                    # Normal operation: respect shutdown/stop requests
                    if self._shutdown_requested or not self._is_running or self._stop_event.is_set():
                        expected_duration = self._get_segment_duration(segment)
                        logger.info(f"[PLAYOUT] Stopping playback early: reason=normal_shutdown, frames={frame_count}, expected_duration={expected_duration:.1f}s")
                        break
                
                # PE6.5: Periodic buffer status update (non-blocking)
                # Poll /tower/buffer at configured intervals
                if self._pid_controller:
                    self._pid_controller.poll_buffer_status()
                
                # Clock A: Adaptive decode pacing with optional PID controller
                # PE6.5: PID controller ADJUSTS Clock A pacing, does not replace it
                now = time.monotonic()
                
                # Base Clock A pacing (always used for real-time decode pacing)
                clock_a_sleep = next_frame_time - now
                
                if self._pid_controller and self._pid_controller.enabled:
                    # PE6.5: PID controller provides sleep adjustment (not absolute duration)
                    # PID adjusts Clock A's base sleep duration
                    # When buffer is low: positive adjustment (slow decode) so Tower catches up
                    # When buffer is high: negative adjustment (fast decode) so Tower drains
                    pid_adjustment = self._pid_controller.get_sleep_adjustment(now)
                    sleep_duration = clock_a_sleep + pid_adjustment
                    # PE6.3: Clamp sleep duration to (min_sleep, max_sleep) bounds
                    sleep_duration = max(self._pid_controller.min_sleep, min(sleep_duration, self._pid_controller.max_sleep))
                    # Ensure sleep is non-negative
                    sleep_duration = max(0, sleep_duration)
                else:
                    # Fixed-rate Clock A pacing (original behavior)
                    sleep_duration = clock_a_sleep
                
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
                
                # Update Clock A timeline for next frame (always advance for segment timing)
                # PE6.7: Segment timing remains wall-clock based and NOT affected by PID controller
                next_frame_time += FRAME_DURATION
                
                # Apply gain via mixer
                processed_frame = self._mixer.mix(frame, gain=segment.gain)
                
                # Write frame immediately - no pacing on socket write, non-blocking
                # TowerPCMSink handles non-blocking writes and drop-oldest semantics
                # Clock A only paces decode consumption, NOT socket writes
                try:
                    self._output_sink.write(processed_frame)
                    frame_count += 1
                except Exception as e:
                    logger.error(f"[PLAYOUT] Error writing frame to output sink: {e}", exc_info=True)
                    # Continue decoding even if write fails (non-blocking behavior)
                
                
                # Log progress every 1000 frames
                if frame_count % 1000 == 0:
                    actual_elapsed = time.monotonic() - start_time
                    logger.debug(f"[PLAYOUT] Decoded {frame_count} frames ({actual_elapsed:.1f}s elapsed)")
            
            # Note: _segment_active remains True after decode completes
            # It will be set to False in finish_segment() after segment teardown completes
            # This ensures prefill cannot run between decode completion and segment teardown
            
            total_time = time.monotonic() - start_time
            expected_duration = self._get_segment_duration(segment)
            
            # Log if segment ended early (before expected duration)
            if total_time < expected_duration * 0.95:  # Allow 5% tolerance
                logger.warning(f"[PLAYOUT] Segment ended early: {segment.path} (decoded {frame_count} frames, {total_time:.1f}s, expected {expected_duration:.1f}s)")
                if self._is_draining:
                    logger.warning(f"[PLAYOUT] CRITICAL: Segment cut off during DRAINING - this should not happen unless explicit hard stop or timeout")
            else:
                logger.info(f"[PLAYOUT] Finished decoding {segment.path} ({frame_count} frames, {total_time:.1f}s, expected {expected_duration:.1f}s)")
            
            return frame_count
            
        except FileNotFoundError:
            logger.error(f"[PLAYOUT] Audio file not found: {segment.path}")
            raise
        except Exception as e:
            logger.error(f"[PLAYOUT] Error decoding/playing {segment.path}: {e}", exc_info=True)
            raise
        finally:
            # Note: _segment_active remains True even if decode fails
            # It will be set to False in finish_segment() after segment teardown completes
            # This ensures prefill cannot run between decode failure and segment teardown
            
            # Clear decoder reference when segment finishes (decoder.close() is called by read_frames() finally block)
            if self._current_decoder is decoder:
                self._current_decoder = None
    
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
