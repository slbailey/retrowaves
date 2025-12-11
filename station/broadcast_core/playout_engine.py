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

from station.broadcast_core.audio_event import AudioEvent
from station.broadcast_core.playout_queue import PlayoutQueue
from station.broadcast_core.ffmpeg_decoder import FFmpegDecoder
from station.broadcast_core.buffer_pid_controller import BufferPIDController
from station.mixer.mixer import Mixer
from station.outputs.base_sink import BaseSink

logger = logging.getLogger(__name__)


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
        self._mixer = Mixer()
        self._shutdown_requested = False  # Per contract SL2.2: Prevent THINK/DO after shutdown
        
        # Track talking state to avoid multiple dj_talking events for consecutive talk files
        self._is_in_talking_sequence = False
        
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
        
        logger.info(f"Starting segment: {segment.type} - {segment.path}")
        
        # Emit appropriate event based on segment type
        if self._tower_control and not self._shutdown_requested:
            try:
                if segment.type == "song":
                    # Emit new_song event with MP3 metadata
                    # Metadata should have been extracted during THINK phase and stored in AudioEvent
                    # If not available, fall back to extracting it now (shouldn't happen in normal flow)
                    if segment.metadata:
                        metadata = segment.metadata
                    else:
                        logger.warning(f"Metadata not found for {segment.path}, extracting during DO phase (should be done in THINK)")
                        metadata = _get_mp3_metadata(segment.path)
                    
                    self._tower_control.send_event(
                        event_type="new_song",
                        timestamp=time.monotonic(),
                        metadata={
                            "file_path": segment.path,
                            "title": metadata.get("title") if metadata else None,
                            "artist": metadata.get("artist") if metadata else None,
                            "album": metadata.get("album") if metadata else None,
                            "duration": metadata.get("duration") if metadata else None
                        }
                    )
                    # Reset talking sequence flag when a song starts
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
        # Per contract SL2.2: No DO events MAY fire after shutdown begins
        # Per contract SL2.2: Check both shutdown_requested and callback existence
        if not self._shutdown_requested and self._dj_callback:
            try:
                self._dj_callback.on_segment_finished(segment)
            except Exception as e:
                logger.error(f"Error in DJ callback on_segment_finished: {e}")
        
        # Clear current segment
        self._current_segment = None
        self._is_playing = False
    
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
        
        # Per contract SL2.2: Check shutdown_requested in loop condition
        while self._is_running and not self._stop_event.is_set() and not self._shutdown_requested:
            # Periodic queue monitoring (every 5 seconds)
            now = time.time()
            if now - self._last_queue_log_time >= self._queue_log_interval:
                queue_size = self._queue.size()
                logger.info(
                    f"[QUEUE_MONITOR] PlayoutQueue: {queue_size} segments waiting"
                )
                self._last_queue_log_time = now
            
            # Per contract SL2.2: Check shutdown before dequeueing new segment
            if self._shutdown_requested:
                logger.info("Playout loop stopping: shutdown requested")
                break
            
            # Try to get next segment from queue
            segment = self._queue.dequeue()
            
            if segment is None:
                # Queue is empty, wait a bit before checking again
                # Per contract SL2.2: Check shutdown during wait
                if self._shutdown_requested:
                    break
                time.sleep(0.1)
                continue
            
            # Per contract SL2.2: Check shutdown before THINK phase (on_segment_started)
            if self._shutdown_requested:
                logger.info("Playout loop stopping: shutdown requested before THINK phase")
                break
            
            # Start the segment (triggers on_segment_started - THINK phase)
            # start_segment() internally checks shutdown_requested before firing callback
            self.start_segment(segment)
            
            # Per contract SL2.2: Check shutdown after THINK, before playback
            if self._shutdown_requested:
                logger.info("Playout loop stopping: shutdown requested after THINK phase")
                break
            
            # Decode and play the audio segment
            try:
                self._play_audio_segment(segment)
            except Exception as e:
                logger.error(f"[PLAYOUT] Error playing segment {segment.path}: {e}", exc_info=True)
                # Don't continue to finish_segment if playback failed
                continue
            
            # Per contract SL2.2: Check shutdown before DO phase (on_segment_finished)
            if self._shutdown_requested:
                logger.info("Playout loop stopping: shutdown requested before DO phase")
                break
            
            # Finish the segment (triggers on_segment_finished - DO phase)
            # finish_segment() internally checks shutdown_requested before firing callback
            # Note: finish_segment() will verify the segment is still current, so we can call it directly
            self.finish_segment(segment)
        
        logger.info("Playout loop stopped")
    
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
        decoder: FFmpegDecoder,
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
        - Decodes and sends frames as fast as possible (no Clock A sleep)
        - Monitors buffer fill level periodically
        - Exits when buffer reaches target or timeout elapses
        
        Pre-fill MUST NOT:
        - Change segment timing logic (elapsed = time.monotonic() - segment_start)
        - Reset or manipulate Clock A's internal next_frame_time
        - Introduce any pacing on socket writes (writes remain immediate + non-blocking)
        
        Args:
            decoder: FFmpegDecoder instance for decoding frames
            segment: AudioEvent being played
            start_time: Segment start time (Clock A baseline, MUST NOT be modified)
            next_frame_time: Clock A's next_frame_time (MUST NOT be modified)
        
        Returns:
            True if pre-fill was executed (decoder consumed), False if skipped
        """
        # C8: Pre-fill is optional and implementation-defined
        # Check if pre-fill should run
        prefill_enabled = os.getenv("PREFILL_ENABLED", "true").lower() == "true"
        if not prefill_enabled:
            return False
        
        # C8: Check Tower buffer status via /tower/buffer endpoint
        buffer_status = self._get_tower_buffer_status()
        if buffer_status is None:
            # C8: If endpoint unavailable, skip pre-fill and fall back to normal pacing
            logger.debug("[PREFILL] Tower buffer endpoint unavailable, skipping pre-fill")
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
            logger.debug(f"[PREFILL] Buffer ratio {ratio:.3f} >= target {target_ratio}, skipping pre-fill")
            return False
        
        # C8: Enter pre-fill mode - decode and send frames as fast as possible
        # Pre-fill is "front-load the first chunk(s) of the current segment"
        # NOT "decode the whole thing" - we want to leave most of the segment for normal playback
        logger.info(f"[PREFILL] Starting pre-fill (buffer ratio {ratio:.3f} < target {target_ratio})")
        prefill_start_time = time.monotonic()
        frame_count = 0
        last_poll_time = prefill_start_time
        
        # C8: Safety limit - don't pre-fill more than a reasonable chunk of the segment
        # Pre-fill should be a "front-load" operation, not consume the entire segment
        # Limit to ~10 seconds of audio (approximately 470 frames at 48kHz)
        max_prefill_frames = int(10.0 * 48000.0 / 1024.0)  # ~470 frames = ~10 seconds
        
        try:
            for frame in decoder.read_frames():
                # Check shutdown
                if self._shutdown_requested or not self._is_running or self._stop_event.is_set():
                    logger.info("[PREFILL] Stopping pre-fill early (shutdown requested)")
                    break
                
                # C8: Safety check - don't consume entire segment in pre-fill
                if frame_count >= max_prefill_frames:
                    logger.info(f"[PREFILL] Pre-fill frame limit ({max_prefill_frames} frames) reached, exiting pre-fill")
                    break
                
                # C8: Check timeout
                elapsed = time.monotonic() - prefill_start_time
                if elapsed >= prefill_timeout:
                    logger.warning(f"[PREFILL] Pre-fill timeout ({prefill_timeout}s) reached, exiting pre-fill")
                    break
                
                # C8: Poll buffer status periodically (every ~50-100ms)
                now = time.monotonic()
                if now - last_poll_time >= prefill_poll_interval:
                    buffer_status = self._get_tower_buffer_status()
                    if buffer_status is not None:
                        ratio = self._get_buffer_ratio(buffer_status)
                        # C8: Exit pre-fill when buffer reaches target
                        if ratio >= target_ratio:
                            logger.info(f"[PREFILL] Buffer ratio {ratio:.3f} >= target {target_ratio}, pre-fill complete ({frame_count} frames)")
                            break
                    last_poll_time = now
                
                # C8: Apply gain and write frame immediately (no sleep, no pacing)
                # Pre-fill MUST NOT affect segment timing or Clock A timeline
                processed_frame = self._mixer.mix(frame, gain=segment.gain)
                try:
                    self._output_sink.write(processed_frame)
                    frame_count += 1
                except Exception as e:
                    logger.error(f"[PREFILL] Error writing frame: {e}", exc_info=True)
                    # Continue even if write fails (non-blocking behavior)
            
            prefill_duration = time.monotonic() - prefill_start_time
            logger.info(f"[PREFILL] Pre-fill complete ({frame_count} frames in {prefill_duration:.2f}s)")
            return True  # Decoder was consumed
            
        except Exception as e:
            logger.error(f"[PREFILL] Error during pre-fill: {e}", exc_info=True)
            return True  # Decoder may have been partially consumed
    
    def _play_audio_segment(self, segment: AudioEvent) -> None:
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
            return
        
        # Get expected duration for logging
        expected_duration = self._get_segment_duration(segment)
        logger.info(f"[PLAYOUT] Decoding and playing: {segment.path} (expected duration: {expected_duration:.1f}s)")
        
        start_time = time.monotonic()  # Use monotonic clock for Clock A
        frame_count = 0
        
        # Clock A: Decode pacing metronome
        # Target: ~21.333 ms per 1024-sample frame (1024 samples / 48000 Hz)
        FRAME_DURATION = 1024.0 / 48000.0  # ~0.021333 seconds
        next_frame_time = start_time  # Initialize Clock A timeline
        
        try:
            # Create decoder for this segment
            # Note: decoder.read_frames() handles cleanup automatically via finally block
            decoder = FFmpegDecoder(segment.path, frame_size=1024)
            logger.debug(f"[PLAYOUT] FFmpegDecoder created for {segment.path}")
            
            # C8: Pre-Fill Stage - build up Tower buffer before normal pacing
            # Pre-fill MUST NOT affect Clock A timeline or segment timing
            # Pre-fill decodes and sends frames as fast as possible (no sleep)
            # After pre-fill, normal decode loop continues with Clock A + PID pacing
            prefill_consumed_decoder = self._run_prefill_if_needed(decoder, segment, start_time, next_frame_time)
            
            # If pre-fill consumed the decoder, recreate it for normal decode loop
            # (decoder.read_frames() is an iterator that can only be consumed once)
            if prefill_consumed_decoder:
                decoder = FFmpegDecoder(segment.path, frame_size=1024)
                logger.debug(f"[PLAYOUT] Recreated FFmpegDecoder after pre-fill for normal decode loop")
            
            # Decode and write frames with Clock A pacing
            # Clock A paces consumption to ensure real-time playback duration
            # Socket writes fire immediately (non-blocking, no pacing on writes)
            for frame in decoder.read_frames():
                # Per contract SL2.2: Check shutdown_requested in playback loop
                # Check if we should stop (shutdown or stop event)
                if self._shutdown_requested or not self._is_running or self._stop_event.is_set():
                    logger.info(f"[PLAYOUT] Stopping playback early (shutdown={self._shutdown_requested}, stop requested)")
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
            
            total_time = time.monotonic() - start_time
            logger.info(f"[PLAYOUT] Finished decoding {segment.path} ({frame_count} frames, {total_time:.1f}s)")
            
        except FileNotFoundError:
            logger.error(f"[PLAYOUT] Audio file not found: {segment.path}")
            raise
        except Exception as e:
            logger.error(f"[PLAYOUT] Error decoding/playing {segment.path}: {e}", exc_info=True)
            raise
    
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
        
        # Start playout loop in background thread
        self._play_thread = threading.Thread(target=self._playout_loop, daemon=True)
        self._play_thread.start()
    
    def stop(self) -> None:
        """
        Stop the playout engine gracefully.
        
        Waits for current segment to finish, then stops.
        """
        if not self._is_running:
            return
        
        logger.info("Stopping playout engine")
        self._is_running = False
        self._stop_event.set()
        
        # Wait for playout thread to finish
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=5.0)
            if self._play_thread.is_alive():
                logger.warning("Playout thread did not stop within timeout")
        
        logger.info("Playout engine stopped")
    
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
