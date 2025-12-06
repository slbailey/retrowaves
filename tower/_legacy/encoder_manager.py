"""
EncoderManager for Retrowaves Tower - Broadcast-Grade Audio Encoding Subsystem.

Manages FFmpeg encoder process lifecycle with:
- Continuous stdout draining in dedicated thread
- Stall detection (0 bytes for N ms = restart)
- Non-blocking MP3 output from ring buffer
- Fire-and-forget PCM writes
- Smooth restart without interrupting playback
"""

import enum
import logging
import select
import subprocess
import threading
import time
from typing import Optional, BinaryIO, Callable

from tower.audio.ring_buffer import RingBuffer
from tower.config import TowerConfig
from tower.encoder import Encoder

logger = logging.getLogger(__name__)


class EncoderState(enum.Enum):
    """EncoderManager state."""
    RUNNING = "running"
    RESTARTING = "restarting"
    FAILED = "failed"
    STOPPED = "stopped"


class EncoderOutputDrainThread:
    """
    Dedicated thread that continuously drains encoder stdout.
    
    Continuously reads MP3 chunks from FFmpeg stdout and feeds them to
    the MP3 ring buffer. Detects stalls (0 bytes for threshold time) and
    notifies EncoderManager to restart.
    """
    
    def __init__(
        self,
        encoder: Encoder,
        mp3_buffer: RingBuffer,
        chunk_size: int,
        stall_threshold_ms: int,
        on_stall: Callable[[], None],
        shutdown_event: threading.Event,
        last_data_timestamp_ref: Optional[list] = None,
        last_stdout_time_ref: Optional[list] = None
    ):
        """
        Initialize drain thread.
        
        Args:
            encoder: Encoder instance to read from
            mp3_buffer: Ring buffer to write to
            chunk_size: Size of chunks to read
            stall_threshold_ms: Stall threshold in milliseconds
            on_stall: Callback when stall detected
            shutdown_event: Event to signal shutdown
            last_data_timestamp_ref: Optional mutable reference (list) to update last data timestamp
            last_stdout_time_ref: Optional mutable reference (list) to update last stdout read time
        """
        self.encoder = encoder
        self.mp3_buffer = mp3_buffer
        self.chunk_size = chunk_size
        self.stall_threshold_ms = stall_threshold_ms
        self.on_stall = on_stall
        self.shutdown_event = shutdown_event
        self._last_data_timestamp_ref = last_data_timestamp_ref  # Reference to update EncoderManager's timestamp
        self._last_stdout_time_ref = last_stdout_time_ref  # Reference to update EncoderManager's last_stdout_time
        
        self._last_data_time = time.monotonic()
        self._startup_time = time.monotonic()  # Track when drain thread started
        self._has_received_data = False  # Track if we've received any data yet
        self._thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        """Start drain thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        
        self._last_data_time = time.monotonic()
        self._startup_time = time.monotonic()
        self._has_received_data = False
        self._thread = threading.Thread(
            target=self._drain_loop,
            daemon=False,
            name="EncoderOutputDrain"
        )
        self._thread.start()
        logger.debug("Encoder output drain thread started")
    
    def stop(self, timeout: float = 2.0) -> None:
        """Stop drain thread."""
        if self._thread is None:
            return
        
        self.shutdown_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("Drain thread did not stop within timeout")
        
        self._thread = None
        logger.debug("Encoder output drain thread stopped")
    
    def _drain_loop(self) -> None:
        """
        Main drain loop - continuously reads from encoder stdout.
        
        Uses select() with timeout to:
        1. Check for shutdown
        2. Detect stalls (no data for threshold time)
        3. Read data when available
        """
        logger.info("Encoder output drain loop started")
        
        try:
            while not self.shutdown_event.is_set():
                # Check if encoder is still running
                if not self.encoder.is_running():
                    logger.warning("Encoder process not running, stopping drain")
                    break
                
                stdout = self.encoder.stdout
                if stdout is None:
                    logger.error("Encoder stdout is None, stopping drain - this should not happen!")
                    break
                
                try:
                    # Use select() with 50ms timeout to avoid blocking indefinitely
                    # This allows shutdown checks and responsive stall detection
                    ready, _, _ = select.select([stdout], [], [], 0.05)
                    
                    if ready:
                        # Data available - read small chunks (256-1024 bytes)
                        # FFmpeg outputs MP3 frames in variable sizes, so we read small chunks
                        # The ring buffer will accumulate these chunks for get_chunk()
                        # Use smaller read size for better responsiveness
                        read_size = min(1024, self.chunk_size)  # Read 256-1024 bytes
                        data = stdout.read(read_size)
                        
                        if not data:
                            # EOF detected - encoder died
                            logger.warning("[DRAIN] Encoder stdout EOF - encoder died")
                            # Signal encoder failure
                            self.on_stall()  # Use stall handler to trigger restart
                            break
                        
                        # Write to MP3 buffer (non-blocking)
                        # Each write is a chunk - ring buffer accumulates them
                        self.mp3_buffer.write(data)
                        now_mono = time.monotonic()
                        now_time = time.time()
                        self._last_data_time = now_mono
                        self._has_received_data = True  # Mark that we've received data
                        
                        # Update debug metrics in EncoderManager
                        if self._last_data_timestamp_ref is not None:
                            self._last_data_timestamp_ref[0] = now_mono
                        # Update last stdout time for stall detection (use time.time() for absolute time)
                        if self._last_stdout_time_ref is not None:
                            self._last_stdout_time_ref[0] = now_time
                        
                        # Track when buffer first gets data (for startup grace period)
                        if not hasattr(self.mp3_buffer, '_first_data_time'):
                            self.mp3_buffer._first_data_time = now
                        
                        # Log first chunk and occasionally after that
                        if not hasattr(self, '_chunks_drained'):
                            self._chunks_drained = 0
                        self._chunks_drained += 1
                        buffer_stats = self.mp3_buffer.get_stats()
                        if self._chunks_drained <= 5 or self._chunks_drained % 100 == 0:
                            logger.info(
                                f"[DRAIN] Drained {len(data)} bytes from encoder stdout "
                                f"(total: {self._chunks_drained}, "
                                f"buffer: {buffer_stats['count']}/{buffer_stats['size']} chunks, "
                                f"dropped: {buffer_stats.get('frames_dropped', 0)})"
                            )
                        else:
                            logger.debug(f"[DRAIN] Drained {len(data)} bytes from encoder stdout")
                        
                    else:
                        # No data available - check for stall
                        now = time.monotonic()
                        elapsed_ms = (now - self._last_data_time) * 1000.0
                        
                        # Don't check for stall until we've received at least one chunk
                        # OR until startup grace period has passed (3x stall threshold)
                        startup_grace_period_ms = self.stall_threshold_ms * 3
                        startup_elapsed_ms = (now - self._startup_time) * 1000.0
                        
                        if not self._has_received_data and startup_elapsed_ms < startup_grace_period_ms:
                            # Still in startup grace period - don't check for stall yet
                            logger.debug(
                                f"Startup grace period: {startup_elapsed_ms:.0f}ms elapsed, "
                                f"waiting up to {startup_grace_period_ms}ms for first data"
                            )
                            continue
                        
                        if elapsed_ms >= self.stall_threshold_ms:
                            # Stall detected - encoder is running but not producing data
                            logger.warning(
                                f"Encoder stall detected: {elapsed_ms:.0f}ms without data "
                                f"(threshold: {self.stall_threshold_ms}ms)"
                            )
                            self.on_stall()
                            break
                        
                except (BrokenPipeError, OSError) as e:
                    # Encoder pipe error - encoder died
                    logger.warning(f"Encoder pipe error in drain thread: {e}")
                    break
                except Exception as e:
                    logger.error(f"Unexpected error in drain thread: {e}", exc_info=True)
                    time.sleep(0.01)  # Brief sleep before retry
                    continue
                    
        except Exception as e:
            logger.error(f"Drain loop error: {e}", exc_info=True)
        finally:
            logger.debug("Encoder output drain loop stopped")


class EncoderManager:
    """
    Manages FFmpeg encoder process with restart logic and stall detection.
    
    Broadcast-grade implementation:
    - Continuous stdout draining in dedicated thread
    - Stall detection (0 bytes for N ms = restart)
    - Non-blocking MP3 output from ring buffer
    - Fire-and-forget PCM writes
    - Smooth restart without interrupting playback
    """
    
    def __init__(self, config: TowerConfig):
        """
        Initialize EncoderManager.
        
        Args:
            config: Tower configuration
        """
        self.config = config
        self.encoder: Optional[Encoder] = None
        self._state = EncoderState.STOPPED
        self._state_lock = threading.Lock()
        self._restart_attempts = 0
        self._shutdown = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._restart_thread: Optional[threading.Thread] = None
        self._drain_thread: Optional[EncoderOutputDrainThread] = None
        self._silent_mp3_chunk: Optional[bytes] = None
        
        # MP3 output ring buffer - shared between drain thread and get_chunk()
        # Size: configurable, default 100 chunks (~1-2 seconds of MP3 at 128kbps)
        # Each chunk is typically 256-1024 bytes, so 100 chunks ≈ 25-100KB buffer
        mp3_buffer_size = getattr(config, 'mp3_buffer_size', 100)
        self._mp3_buffer = RingBuffer(size=mp3_buffer_size)
        logger.debug(f"MP3 ring buffer initialized with size: {mp3_buffer_size} chunks")
        self._drain_shutdown = threading.Event()
        
        # Debug metrics
        self._last_data_timestamp: Optional[float] = None  # Last time data was written to buffer
        self._chunks_read_count = 0
        self._chunks_dropped_count = 0
        
        # Convert backoff delays from milliseconds to seconds
        self.backoff_delays = [d / 1000.0 for d in config.encoder_backoff_ms]
        self.max_restart_attempts = config.encoder_max_restarts
        self.stall_threshold_ms = config.encoder_stall_threshold_ms
        self.stall_ms = config.encoder_stall_ms
        
        # Stall detection: track last time data was read from stdout
        self.last_stdout_time: Optional[float] = None
        
        # Jitter buffer state
        self._jitter_streaming_started = False  # True once buffer reaches min_chunks
        self._jitter_last_read_time: Optional[float] = None  # Last time we read from buffer
        self._jitter_read_interval = config.encoder_jitter_read_interval_ms / 1000.0  # Convert ms to seconds
        self._jitter_min_chunks = config.encoder_jitter_min_chunks
        self._jitter_recover_chunks = config.encoder_jitter_recover_chunks
        self._jitter_target_chunk_rate = config.encoder_target_chunk_rate
        self._jitter_debug_log_counter = 0  # Counter for periodic debug logging
    
    def start(self) -> None:
        """
        Start encoder process and monitoring.
        
        Raises:
            RuntimeError: If encoder fails to start
        """
        if self._state != EncoderState.STOPPED:
            raise RuntimeError(f"EncoderManager already started (state: {self._state})")
        
        logger.info("Starting EncoderManager...")
        
        # Generate silent MP3 chunk for RESTARTING/FAILED states
        try:
            from tower.silent_mp3 import generate_silent_mp3_chunk
            self._silent_mp3_chunk = generate_silent_mp3_chunk(
                self.config, 
                chunk_size=self.config.read_chunk_size
            )
            logger.debug(f"Generated silent MP3 chunk ({len(self._silent_mp3_chunk)} bytes)")
        except Exception as e:
            logger.warning(f"Failed to generate silent MP3 chunk: {e}")
            self._silent_mp3_chunk = None
        
        # Start initial encoder
        self._start_encoder()
        
        if self._state == EncoderState.RUNNING:
            # Start monitor thread to watch for process failures
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=False,
                name="EncoderMonitor"
            )
            self._monitor_thread.start()
            logger.info("EncoderManager started")
        else:
            raise RuntimeError("Failed to start encoder")
    
    def _start_encoder(self) -> bool:
        """
        Start encoder process and drain thread.
        
        Returns:
            bool: True if encoder started successfully, False otherwise
        """
        try:
            # Clean up old encoder if it exists
            if self.encoder is not None:
                try:
                    self._stop_drain_thread()
                    self.encoder.stop()
                except Exception:
                    pass
                self.encoder = None
            
            # Create and start new encoder
            self.encoder = Encoder(self.config)
            self.encoder.start()
            
            # Add brief warm-up before starting drain thread
            time.sleep(0.01)
            
            # Verify encoder is actually running
            if not self.encoder.is_running():
                logger.error("Encoder process did not start properly")
                self.encoder = None
                with self._state_lock:
                    if self._restart_attempts < self.max_restart_attempts:
                        self._state = EncoderState.RESTARTING
                    else:
                        self._state = EncoderState.FAILED
                return False
            
            # Initialize last_stdout_time when encoder starts
            self.last_stdout_time = time.time()
            
            # Reset jitter buffer state for new encoder
            self._jitter_streaming_started = False
            self._jitter_last_read_time = None
            
            # Start stdout drain thread
            self._start_drain_thread()
            
            with self._state_lock:
                self._state = EncoderState.RUNNING
                self._restart_attempts = 0  # Reset on successful start
            
            logger.info("Encoder started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start encoder: {e}", exc_info=True)
            self.encoder = None
            with self._state_lock:
                if self._restart_attempts < self.max_restart_attempts:
                    self._state = EncoderState.RESTARTING
                else:
                    self._state = EncoderState.FAILED
            return False
    
    def _start_drain_thread(self) -> None:
        """Start the stdout drain thread."""
        if self.encoder is None or self.encoder.stdout is None:
            return
        
        # Stop old thread if it exists
        self._stop_drain_thread()
        
        # Clear buffer for new encoder
        self._mp3_buffer.clear()
        
        # Create and start new drain thread
        # Use smaller chunk size (512-1024 bytes) for better responsiveness
        drain_chunk_size = min(1024, self.config.read_chunk_size)
        self._drain_shutdown.clear()
        # Use list to pass mutable reference for last_data_timestamp and last_stdout_time
        last_data_timestamp_ref = [self._last_data_timestamp]
        last_stdout_time_ref = [self.last_stdout_time]
        self._drain_thread = EncoderOutputDrainThread(
            encoder=self.encoder,
            mp3_buffer=self._mp3_buffer,
            chunk_size=drain_chunk_size,
            stall_threshold_ms=self.stall_threshold_ms,
            on_stall=self._handle_stall,
            shutdown_event=self._drain_shutdown,
            last_data_timestamp_ref=last_data_timestamp_ref,
            last_stdout_time_ref=last_stdout_time_ref
        )
        # Initialize last_stdout_time when encoder starts
        self.last_stdout_time = time.time()
        self._drain_thread.start()
        logger.info(f"Encoder stdout drain thread started (chunk_size: {drain_chunk_size} bytes)")
    
    def _stop_drain_thread(self) -> None:
        """Stop the stdout drain thread."""
        if self._drain_thread is not None:
            self._drain_thread.stop()
            self._drain_thread = None
        
        self._drain_shutdown.set()
        self._drain_shutdown.clear()
    
    def _handle_stall(self) -> None:
        """
        Handle encoder stall detection.
        
        Called by drain thread when stall is detected (0 bytes for threshold time).
        Triggers async restart without interrupting playback.
        """
        logger.warning("Encoder stall detected - triggering restart")
        self._handle_encoder_failure()
    
    def _monitor_loop(self) -> None:
        """Monitor encoder process for failures."""
        logger.debug("Encoder monitor thread started")
        
        # Debug logging: print stats every 2 seconds
        _debug_log_counter = 0
        _debug_log_interval = 20  # 20 * 0.1s = 2 seconds
        
        try:
            while not self._shutdown:
                with self._state_lock:
                    state = self._state
                    encoder = self.encoder
                
                # Periodic debug logging every 2 seconds (before early exits)
                _debug_log_counter += 1
                if _debug_log_counter >= _debug_log_interval:
                    _debug_log_counter = 0
                    buffer_stats = self._mp3_buffer.get_stats()
                    # Get state name safely (EncoderState is an Enum)
                    try:
                        state_name = state.name if hasattr(state, 'name') else str(state)
                    except AttributeError:
                        state_name = str(state)
                    logger.info(
                        f"[DEBUG] buffer: {buffer_stats['count']}/{buffer_stats['size']}, "
                        f"dropped={buffer_stats.get('frames_dropped', 0)}, "
                        f"state={state_name}"
                    )
                
                if state == EncoderState.STOPPED or state == EncoderState.FAILED:
                    break
                
                if encoder is None:
                    time.sleep(0.1)
                    continue
                
                # Check if encoder process is still running
                if not encoder.is_running():
                    logger.warning("Encoder process exited (detected via poll)")
                    self._handle_encoder_failure()
                    continue
                
                # Periodic stall detection check
                # If encoder is running but no data read from stdout for stall_ms, trigger restart
                if state == EncoderState.RUNNING and self.last_stdout_time is not None:
                    elapsed = time.time() - self.last_stdout_time
                    if elapsed > (self.stall_ms / 1000.0):
                        logger.warning(
                            f"STALL DETECTED: No stdout data for {elapsed:.1f}s "
                            f"(threshold: {self.stall_ms}ms)"
                        )
                        self._handle_encoder_failure()
                        continue
                
                time.sleep(0.1)  # Check every 100ms
                
        except Exception as e:
            logger.error(f"Encoder monitor thread error: {e}", exc_info=True)
        finally:
            logger.debug("Encoder monitor thread stopped")
    
    def _handle_encoder_failure(self) -> None:
        """
        Handle encoder failure and trigger restart if needed.
        
        This is called for both crashes and stalls.
        Restart happens asynchronously without interrupting playback.
        """
        # Stop drain thread
        self._stop_drain_thread()
        
        with self._state_lock:
            if self._state == EncoderState.FAILED or self._state == EncoderState.STOPPED:
                return
            
            if self._restart_attempts >= self.max_restart_attempts:
                logger.error(
                    f"Encoder failed after {self.max_restart_attempts} restart attempts. "
                    "Entering FAILED state."
                )
                self._state = EncoderState.FAILED
                return
            
            # Transition to RESTARTING state
            # Playback continues from buffer (or silent MP3 if buffer empty)
            self._state = EncoderState.RESTARTING
            attempt_num = self._restart_attempts + 1
        
        # Get delay from config
        backoff_ms = self.config.encoder_backoff_ms
        attempt_idx = min(attempt_num - 1, len(backoff_ms) - 1)
        delay = backoff_ms[attempt_idx] / 1000.0  # Convert ms to seconds
        
        logger.warning(
            f"Encoder failure detected. Restart attempt {attempt_num}/{self.max_restart_attempts} "
            f"after {delay}s delay"
        )
        
        # Start restart thread if not already running
        if self._restart_thread is None or not self._restart_thread.is_alive():
            self._restart_thread = threading.Thread(
                target=self._restart_with_backoff,
                daemon=False,
                name="EncoderRestart"
            )
            self._restart_thread.start()
    
    def _restart_with_backoff(self) -> None:
        """Restart encoder with exponential backoff."""
        with self._state_lock:
            if self._state != EncoderState.RESTARTING:
                return
            attempt_num = self._restart_attempts + 1
        
        # Get backoff delays from config
        backoff_ms = self.config.encoder_backoff_ms
        attempt_idx = min(attempt_num - 1, len(backoff_ms) - 1)
        delay = backoff_ms[attempt_idx] / 1000.0  # Convert ms to seconds
        
        # Wait for backoff delay
        logger.info(f"Waiting {delay}s before restart attempt {attempt_num}")
        time.sleep(delay)
        
        # Attempt restart
        with self._state_lock:
            self._restart_attempts = attempt_num
        
        success = self._start_encoder()
        
        if not success:
            # Restart failed - will trigger another attempt if under limit
            with self._state_lock:
                if self._restart_attempts < self.max_restart_attempts:
                    self._state = EncoderState.RESTARTING
                    # Trigger another restart attempt
                    self._handle_encoder_failure()
                else:
                    self._state = EncoderState.FAILED
                    logger.error(
                        f"Encoder failed after {self.max_restart_attempts} restart attempts. "
                        "Stopping restart attempts."
                    )
    
    def get_state(self) -> EncoderState:
        """
        Get current encoder state.
        
        Returns:
            EncoderState: Current state
        """
        with self._state_lock:
            return self._state
    
    def is_running(self) -> bool:
        """
        Check if encoder is running.
        
        Returns:
            bool: True if encoder is in RUNNING state
        """
        with self._state_lock:
            return self._state == EncoderState.RUNNING
    
    def is_failed(self) -> bool:
        """
        Check if encoder is in FAILED state.
        
        Returns:
            bool: True if encoder is in FAILED state
        """
        with self._state_lock:
            return self._state == EncoderState.FAILED
    
    def write_pcm(self, data: bytes) -> bool:
        """
        Write PCM data to encoder stdin (fire-and-forget, non-blocking).
        
        CRITICAL: Tower must NEVER wait for FFmpeg.
        Encoder stdin is set to non-blocking mode, so writes either succeed
        immediately or raise BlockingIOError (which we catch and drop the frame).
        
        AudioPump relies on absolute time-based pacing. Any blocking (even 3-4ms)
        will accumulate drift over minutes. This method guarantees zero blocking.
        
        In RESTARTING state, attempts to write but ignores all errors
        (AudioPump must remain non-blocking and real-time).
        
        Args:
            data: PCM frame data
            
        Returns:
            bool: True if write succeeded or was dropped (non-blocking), False if encoder is not available
        """
        with self._state_lock:
            state = self._state
            encoder = self.encoder
        
        # In RESTARTING state, try to write but don't fail on any errors
        if state == EncoderState.RESTARTING:
            if encoder is not None and encoder.stdin is not None:
                try:
                    # Fire-and-forget: try to write, ignore all errors
                    encoder.stdin.write(data)
                    # Don't flush() - can block if buffer is full
                except (BlockingIOError, BrokenPipeError, OSError):
                    # Encoder is restarting or buffer full - ignore, AudioPump continues
                    pass
                except Exception:
                    # Any other error - ignore, AudioPump continues
                    pass
            # Return True to indicate AudioPump should continue (non-blocking)
            return True
        
        # In RUNNING state, fire-and-forget write
        if state != EncoderState.RUNNING:
            return False
        
        if encoder is None or encoder.stdin is None:
            return False
        
        try:
            # Fire-and-forget: always try to write, never wait
            # If stdin buffer is full, write() raises BlockingIOError (non-blocking mode)
            # We catch it and drop the frame - AudioPump timing remains intact
            encoder.stdin.write(data)
            # Don't call flush() - it can block if FFmpeg's stdin buffer is full
            # The OS pipe buffer will handle buffering, and FFmpeg will consume at its own rate
            if not hasattr(self, '_pcm_writes_logged'):
                self._pcm_writes_logged = 0
            self._pcm_writes_logged += 1
            if self._pcm_writes_logged <= 10:
                logger.info(f"Wrote {len(data)} bytes of PCM to encoder (total writes: {self._pcm_writes_logged})")
            else:
                logger.debug(f"Wrote {len(data)} bytes of PCM to encoder")
            return True
        except BlockingIOError:
            # Stdin buffer is full - drop frame to avoid blocking AudioPump
            # Frame is dropped, but AudioPump timing remains intact
            logger.debug(f"Encoder stdin buffer full, dropping frame ({len(data)} bytes) - AudioPump continues")
            return True  # Return True to indicate AudioPump should continue
        except (BrokenPipeError, OSError):
            # Encoder died - notify failure
            self._handle_encoder_failure()
            return False
        except Exception as e:
            logger.error(f"Unexpected error writing to encoder: {e}")
            return False
    
    def get_chunk(self, size: int) -> bytes:
        """
        Get MP3 chunk from ring buffer with jitter buffer logic.
        
        CRITICAL: This method NEVER touches encoder.stdout directly.
        Only the drain thread reads from encoder.stdout.
        
        Architecture:
        - PCM writer loop → encoder.stdin (real-time paced, source clock)
        - Encoder stdout → drain thread → MP3 ring buffer → get_chunk() → HTTP clients (consumer clock)
        
        Jitter Buffer Logic:
        - Waits until buffer reaches min_chunks before starting streaming
        - Reads at fixed intervals (not as fast as possible) for steady output
        - On underflow, pauses and waits for recovery threshold (no immediate silence)
        - Only returns silent MP3 if encoder is dead (STOPPED/FAILED/RESTARTING)
        
        Args:
            size: Number of bytes to read/return (uses encoder_target_chunk_rate if larger)
            
        Returns:
            bytes: MP3 data (real or silent)
        """
        with self._state_lock:
            state = self._state
        
        # If STOPPED, RESTARTING, or FAILED, return silent MP3 immediately
        # This ensures continuous output even during encoder lifecycle transitions
        if state in (EncoderState.STOPPED, EncoderState.RESTARTING, EncoderState.FAILED):
            if self._silent_mp3_chunk:
                return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
            return _minimal_mp3_chunk(size)
        
        # If RUNNING, implement jitter buffer logic
        if state == EncoderState.RUNNING:
            buffer_stats = self._mp3_buffer.get_stats()
            buffer_count = buffer_stats['count']
            
            # Periodic debug logging every second
            # Calculate interval: 1 second / read_interval (e.g., 1.0 / 0.015 ≈ 66 reads/second)
            debug_interval = int(1.0 / self._jitter_read_interval) if self._jitter_read_interval > 0 else 100
            self._jitter_debug_log_counter += 1
            if self._jitter_debug_log_counter >= debug_interval:
                self._jitter_debug_log_counter = 0
                jitter_state = "STREAMING" if self._jitter_streaming_started else "FILLING"
                logger.info(
                    f"[JITTER] buffer={buffer_count}/{buffer_stats['size']}, "
                    f"state={jitter_state}"
                )
            
            # Phase 1: Pre-streaming - wait for minimum waterline
            if not self._jitter_streaming_started:
                if buffer_count < self._jitter_min_chunks:
                    # Buffer not ready - wait with small intervals (2-5ms) and recheck
                    # Try to fill buffer first before giving up
                    max_wait_iterations = 10  # ~30ms total wait (10 * 3ms)
                    for _ in range(max_wait_iterations):
                        time.sleep(0.003)  # 3ms wait
                        buffer_stats_retry = self._mp3_buffer.get_stats()
                        if buffer_stats_retry['count'] >= self._jitter_min_chunks:
                            # Buffer filled - proceed to start streaming
                            break
                    
                    # Check again after wait
                    buffer_stats_final = self._mp3_buffer.get_stats()
                    if buffer_stats_final['count'] < self._jitter_min_chunks:
                        # Still not ready - return minimal silent to maintain stream continuity
                        # This should be rare if drain thread is working and encoder is producing data
                        if self._silent_mp3_chunk:
                            return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
                        return _minimal_mp3_chunk(size)
                
                # Buffer reached minimum - start streaming
                self._jitter_streaming_started = True
                self._jitter_last_read_time = time.time()
                logger.info(f"[JITTER] Streaming started (buffer: {buffer_count}/{buffer_stats['size']} chunks)")
            
            # Phase 2: Normal streaming - fixed-rate reading
            # Enforce fixed read interval for steady output (not as fast as possible)
            now = time.time()
            if self._jitter_last_read_time is not None:
                elapsed = now - self._jitter_last_read_time
                if elapsed < self._jitter_read_interval:
                    # Wait until next read interval
                    time.sleep(self._jitter_read_interval - elapsed)
                    now = time.time()
            
            # Check for underflow during streaming
            if buffer_count < self._jitter_recover_chunks:
                # Underflow detected - pause output and wait for recovery
                # Do NOT inject silence - wait for buffer to refill
                logger.warning(
                    f"[JITTER] Underflow detected - pausing output "
                    f"(buffer: {buffer_count}/{buffer_stats['size']} chunks, "
                    f"recover threshold: {self._jitter_recover_chunks})"
                )
                # Wait for buffer to recover (sleep and retry)
                time.sleep(0.005)  # 5ms wait
                buffer_stats_recover = self._mp3_buffer.get_stats()
                if buffer_stats_recover['count'] < self._jitter_recover_chunks:
                    # Still below recovery threshold - return minimal silent to maintain stream
                    # but this should be temporary if encoder is producing data
                    if self._silent_mp3_chunk:
                        return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
                    return _minimal_mp3_chunk(size)
                # Buffer recovered - continue streaming
                logger.info(f"[JITTER] Buffer recovered - resuming output (buffer: {buffer_stats_recover['count']}/{buffer_stats['size']} chunks)")
            
            # Read fixed chunk size at regular intervals
            # Use target chunk rate, but don't exceed requested size
            read_size = min(self._jitter_target_chunk_rate, size)
            chunk = self._mp3_buffer.read(read_size)
            
            if chunk is not None and len(chunk) > 0:
                # Got data - update metrics and return
                self._chunks_read_count += 1
                self._last_data_timestamp = time.monotonic()
                self._jitter_last_read_time = time.time()
                
                # Log real audio chunk (reduced verbosity)
                if self._chunks_read_count <= 5 or self._chunks_read_count % 100 == 0:
                    logger.debug(
                        f"[STREAM] real audio chunk {len(chunk)} bytes "
                        f"(total: {self._chunks_read_count}, "
                        f"buffer: {buffer_stats['count']}/{buffer_stats['size']} chunks)"
                    )
                
                return chunk
            else:
                # No data available - this shouldn't happen if buffer is above recover threshold
                # but handle gracefully
                logger.warning(
                    f"[JITTER] No data available despite buffer count {buffer_count} "
                    f"(recover threshold: {self._jitter_recover_chunks})"
                )
                # Return minimal silent to maintain stream continuity
                if self._silent_mp3_chunk:
                    return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
                return _minimal_mp3_chunk(size)
        
        # Not RUNNING - return silent MP3
        logger.warning(f"[STREAM] underflow -> silent fallback (state: {state.name})")
        if self._silent_mp3_chunk:
            return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
        return _minimal_mp3_chunk(size)
    
    @property
    def stdin(self) -> Optional[BinaryIO]:
        """
        Get encoder stdin for direct access (for compatibility).
        
        Returns:
            BinaryIO: Encoder stdin, or None if not available
        """
        with self._state_lock:
            if self._state != EncoderState.RUNNING:
                return None
            if self.encoder is None:
                return None
            return self.encoder.stdin
    
    @property
    def stdout(self) -> Optional[BinaryIO]:
        """
        Get encoder stdout for direct access (for compatibility).
        
        Returns:
            BinaryIO: Encoder stdout, or None if not available
        """
        with self._state_lock:
            if self._state != EncoderState.RUNNING:
                return None
            if self.encoder is None:
                return None
            return self.encoder.stdout
    
    def get_debug_metrics(self) -> dict:
        """
        Get debug metrics for monitoring.
        
        Returns:
            dict with buffer occupancy, chunks dropped, last data timestamp, etc.
        """
        buffer_stats = self._mp3_buffer.get_stats()
        return {
            "state": self._state.name,
            "buffer_occupancy": buffer_stats.get('utilization', 0.0),
            "buffer_count": buffer_stats.get('count', 0),
            "buffer_size": buffer_stats.get('size', 0),
            "chunks_dropped": buffer_stats.get('frames_dropped', 0),
            "chunks_read": getattr(self, '_chunks_read_count', 0),
            "last_data_timestamp": getattr(self, '_last_data_timestamp', None),
            "restart_attempts": self._restart_attempts,
        }
    
    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop encoder and monitoring.
        
        Args:
            timeout: Maximum time to wait for encoder to stop
        """
        logger.info("Stopping EncoderManager...")
        
        self._shutdown = True
        
        with self._state_lock:
            self._state = EncoderState.STOPPED
        
        # Reset jitter buffer state
        self._jitter_streaming_started = False
        self._jitter_last_read_time = None
        self._jitter_debug_log_counter = 0
        
        # Stop drain thread
        self._stop_drain_thread()
        
        # Stop encoder
        if self.encoder is not None:
            try:
                self.encoder.stop(timeout=timeout)
            except Exception as e:
                logger.warning(f"Error stopping encoder: {e}")
        
        # Wait for threads
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2.0)
        
        if self._restart_thread is not None:
            self._restart_thread.join(timeout=2.0)
        
        logger.info("EncoderManager stopped")


def _minimal_mp3_chunk(size: int) -> bytes:
    """Generate minimal MP3 chunk as fallback."""
    # Minimal MP3 sync frame header
    header = bytes([0xFF, 0xFB, 0x94, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    # Pad to requested size
    if len(header) >= size:
        return header[:size]
    return header + b'\x00' * (size - len(header))
