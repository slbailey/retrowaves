"""
Playout Engine for Appalachia Radio 3.1.

Non-blocking, frame-based playout engine that emits lifecycle events
and plays audio segments from the queue.

Architecture 3.1 Reference:
- Section 2.2: Playback Engine Is the Metronome
- Section 2.7: Frame-Based Audio Pipeline
- Section 5: Updated Playout Engine Flow (Event-Driven, Intent-Aware)
"""

import logging
import os
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional, Protocol

from station.broadcast_core.audio_event import AudioEvent
from station.broadcast_core.playout_queue import PlayoutQueue
from station.broadcast_core.ffmpeg_decoder import FFmpegDecoder
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
            tower_control: Optional TowerControlClient (deprecated - not used for timing)
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
        
        # Emit segment_started heartbeat event to Tower (per contract PE4.1)
        # Optional: Suppress heartbeat events during shutdown for strict "no events after shutdown" semantics
        # (Not required by contract - heartbeat events are transport-level and observational)
        if self._tower_control and not self._shutdown_requested:
            try:
                expected_duration = self._get_segment_duration(segment)
                segment_id = f"{segment.type}_{os.path.basename(segment.path)}_{int(time.monotonic() * 1000)}"
                self._tower_control.send_event(
                    event_type="segment_started",
                    timestamp=time.monotonic(),
                    metadata={
                        "segment_id": segment_id,
                        "expected_duration": expected_duration,
                        "audio_event": {
                            "type": segment.type,
                            "path": segment.path,
                            "gain": segment.gain
                        }
                    }
                )
            except Exception as e:
                logger.debug(f"Error sending segment_started event: {e}")
        
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
        
        # Emit segment_finished heartbeat event to Tower (per contract PE4.3)
        # Optional: Suppress heartbeat events during shutdown for strict "no events after shutdown" semantics
        # (Not required by contract - heartbeat events are transport-level and observational)
        if self._tower_control and not self._shutdown_requested:
            try:
                total_duration = time.monotonic() - getattr(self, '_segment_start_time', time.monotonic())
                segment_id = getattr(self, '_current_segment_id', f"{segment.type}_{os.path.basename(segment.path)}")
                self._tower_control.send_event(
                    event_type="segment_finished",
                    timestamp=time.monotonic(),
                    metadata={
                        "segment_id": segment_id,
                        "total_duration": total_duration,
                        "audio_event": {
                            "type": segment.type,
                            "path": segment.path,
                            "gain": segment.gain
                        }
                    }
                )
            except Exception as e:
                logger.debug(f"Error sending segment_finished event: {e}")
        
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
            if self._is_playing and self._current_segment == segment:
                self.finish_segment(segment)
        
        logger.info("Playout loop stopped")
    
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
            
            # Decode and write frames with Clock A pacing
            # Clock A paces consumption to ensure real-time playback duration
            # Socket writes fire immediately (non-blocking, no pacing on writes)
            for frame in decoder.read_frames():
                # Per contract SL2.2: Check shutdown_requested in playback loop
                # Check if we should stop (shutdown or stop event)
                if self._shutdown_requested or not self._is_running or self._stop_event.is_set():
                    logger.info(f"[PLAYOUT] Stopping playback early (shutdown={self._shutdown_requested}, stop requested)")
                    break
                
                # Clock A: Pace decode consumption for real-time playback
                # This ensures songs take their real duration (e.g., 200-second MP3 takes 200 seconds)
                now = time.monotonic()
                sleep_duration = next_frame_time - now
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
                # Update Clock A timeline for next frame (allow drift correction)
                next_frame_time += FRAME_DURATION
                
                # Apply gain via mixer
                processed_frame = self._mixer.mix(frame, gain=segment.gain)
                
                # Write frame immediately - no pacing on socket write, non-blocking
                # TowerPCMSink handles non-blocking writes and drop-oldest semantics
                # Clock A only paces decode consumption, NOT socket writes
                self._output_sink.write(processed_frame)
                frame_count += 1
                
                # Emit segment_progress heartbeat event at least once per second (per contract PE4.2)
                # Optional: Suppress heartbeat events during shutdown for strict "no events after shutdown" semantics
                # (Not required by contract - heartbeat events are transport-level and observational)
                now = time.monotonic()
                if now - getattr(self, '_last_progress_event_time', now) >= 1.0:
                    if self._tower_control and self._current_segment and not self._shutdown_requested:
                        try:
                            elapsed_time = now - getattr(self, '_segment_start_time', now)
                            expected_duration = self._get_segment_duration(self._current_segment)
                            progress_percent = (elapsed_time / expected_duration * 100.0) if expected_duration > 0 else 0.0
                            segment_id = getattr(self, '_current_segment_id', f"{self._current_segment.type}_{os.path.basename(self._current_segment.path)}")
                            self._tower_control.send_event(
                                event_type="segment_progress",
                                timestamp=now,
                                metadata={
                                    "segment_id": segment_id,
                                    "elapsed_time": elapsed_time,
                                    "expected_duration": expected_duration,
                                    "progress_percent": progress_percent
                                }
                            )
                            self._last_progress_event_time = now
                        except Exception as e:
                            logger.debug(f"Error sending segment_progress event: {e}")
                
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
