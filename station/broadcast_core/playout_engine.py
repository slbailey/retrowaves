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
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional, Protocol

from broadcast_core.audio_event import AudioEvent
from broadcast_core.playout_queue import PlayoutQueue
from broadcast_core.ffmpeg_decoder import FFmpegDecoder
from mixer.mixer import Mixer
from outputs.base_sink import BaseSink

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
    
    def __init__(self, dj_callback: Optional[DJCallback] = None, output_sink: Optional[BaseSink] = None):
        """
        Initialize the playout engine.
        
        Args:
            dj_callback: Optional DJ callback object that implements
                        on_segment_started and on_segment_finished methods
            output_sink: Output sink to write audio frames to (required for real audio playback)
        """
        self._queue = PlayoutQueue()
        self._dj_callback = dj_callback
        self._output_sink = output_sink
        self._current_segment: Optional[AudioEvent] = None
        self._is_playing = False
        self._is_running = False
        self._stop_event = threading.Event()
        self._play_thread: Optional[threading.Thread] = None
        self._mixer = Mixer()
        
        # Fallback segment durations (in seconds) if we can't detect real duration
        self._default_segment_duration = 180.0  # 3 minutes default for songs
        self._fallback_durations = {
            "song": 180.0,      # 3 minutes
            "intro": 5.0,       # 5 seconds
            "outro": 10.0,      # 10 seconds
            "talk": 30.0,       # 30 seconds
            "id": 5.0,          # 5 seconds
        }
    
    def set_dj_callback(self, dj_callback: DJCallback) -> None:
        """
        Set the DJ callback object.
        
        Args:
            dj_callback: DJ callback object implementing on_segment_started
                        and on_segment_finished methods
        """
        self._dj_callback = dj_callback
    
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
        
        logger.info(f"Starting segment: {segment.type} - {segment.path}")
        
        # Emit on_segment_started callback
        if self._dj_callback:
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
        
        # Emit on_segment_finished callback
        if self._dj_callback:
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
        """
        logger.info("Playout loop started")
        
        while self._is_running and not self._stop_event.is_set():
            # Try to get next segment from queue
            segment = self._queue.dequeue()
            
            if segment is None:
                # Queue is empty, wait a bit before checking again
                time.sleep(0.1)
                continue
            
            # Start the segment (triggers on_segment_started)
            self.start_segment(segment)
            
            # Decode and play the audio segment
            try:
                self._play_audio_segment(segment)
            except Exception as e:
                logger.error(f"[PLAYOUT] Error playing segment {segment.path}: {e}", exc_info=True)
                # Don't continue to finish_segment if playback failed
                continue
            
            # Finish the segment (triggers on_segment_finished)
            if self._is_playing and self._current_segment == segment:
                self.finish_segment(segment)
        
        logger.info("Playout loop stopped")
    
    def _play_audio_segment(self, segment: AudioEvent) -> None:
        """
        Decode and play an audio segment.
        
        The decoder reads frames as fast as possible, but we need to rate-limit
        playback to real-time. We calculate the expected duration and ensure
        we don't finish until that time has elapsed.
        
        Args:
            segment: AudioEvent to play
        """
        if not self._output_sink:
            logger.warning("No output sink configured - cannot play audio")
            # Fall back to simulated playback
            duration = self._get_segment_duration(segment)
            logger.debug(f"Simulating playback for {duration:.1f} seconds (no sink)")
            elapsed = 0.0
            check_interval = 0.1
            while elapsed < duration and self._is_running and not self._stop_event.is_set():
                sleep_time = min(check_interval, duration - elapsed)
                time.sleep(sleep_time)
                elapsed += sleep_time
            return
        
        # Get expected duration for rate-limiting
        expected_duration = self._get_segment_duration(segment)
        logger.info(f"[PLAYOUT] Decoding and playing: {segment.path} (expected duration: {expected_duration:.1f}s)")
        
        start_time = time.time()
        frame_count = 0
        frame_size = 1024  # samples per frame
        sample_rate = 48000  # Hz
        frames_per_second = sample_rate / frame_size  # ~46.875 frames/sec
        
        try:
            # Create decoder for this segment
            # Note: decoder.read_frames() handles cleanup automatically via finally block
            decoder = FFmpegDecoder(segment.path, frame_size=frame_size)
            logger.debug(f"[PLAYOUT] FFmpegDecoder created for {segment.path}")
            
            # Decode and play frames with rate limiting
            for frame in decoder.read_frames():
                # Check if we should stop
                if not self._is_running or self._stop_event.is_set():
                    logger.info(f"[PLAYOUT] Stopping playback early (stop requested)")
                    break
                
                # Apply gain via mixer
                processed_frame = self._mixer.mix(frame, gain=segment.gain)
                
                # Write to output sink (non-blocking, sink handles buffering)
                self._output_sink.write(processed_frame)
                frame_count += 1
                
                # Rate limit: calculate when this frame should be played
                # We want to play frames at real-time speed
                expected_elapsed = frame_count / frames_per_second
                actual_elapsed = time.time() - start_time
                
                # If we're ahead of schedule, sleep a bit
                if expected_elapsed > actual_elapsed:
                    sleep_time = expected_elapsed - actual_elapsed
                    if sleep_time > 0.001:  # Only sleep if more than 1ms
                        time.sleep(sleep_time)
                
                # Log progress every 1000 frames (~20 seconds at 48kHz)
                if frame_count % 1000 == 0:
                    logger.debug(f"[PLAYOUT] Played {frame_count} frames ({actual_elapsed:.1f}s elapsed)")
            
            # Wait for remaining duration if we finished decoding early
            actual_elapsed = time.time() - start_time
            if actual_elapsed < expected_duration:
                remaining = expected_duration - actual_elapsed
                logger.debug(f"[PLAYOUT] Decoding finished early, waiting {remaining:.1f}s for playback to complete")
                time.sleep(remaining)
            
            total_time = time.time() - start_time
            logger.info(f"[PLAYOUT] Finished playing {segment.path} ({frame_count} frames, {total_time:.1f}s)")
            
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
