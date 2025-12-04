"""
EncoderManager for Retrowaves Tower Phase 4.

Manages FFmpeg encoder process lifecycle with restart logic and exponential backoff.
"""

import enum
import logging
import select
import subprocess
import threading
import time
from typing import Optional, BinaryIO

from tower.config import TowerConfig
from tower.encoder import Encoder

logger = logging.getLogger(__name__)


class EncoderState(enum.Enum):
    """EncoderManager state."""
    RUNNING = "running"
    RESTARTING = "restarting"
    FAILED = "failed"
    STOPPED = "stopped"


class EncoderManager:
    """
    Manages FFmpeg encoder process with restart logic.
    
    Responsibilities:
    - Start and monitor encoder process
    - Detect encoder failures (EOF, crashes)
    - Restart encoder with exponential backoff
    - Provide thread-safe interfaces for AudioPump and HTTPConnectionManager
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
        self._silent_mp3_chunk: Optional[bytes] = None  # Cached silent MP3 for RESTARTING/FAILED
        
        # Convert backoff delays from milliseconds to seconds
        self.backoff_delays = [d / 1000.0 for d in config.encoder_backoff_ms]
        self.max_restart_attempts = config.encoder_max_restarts
    
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
            self._silent_mp3_chunk = generate_silent_mp3_chunk(self.config, chunk_size=self.config.read_chunk_size)
            logger.debug(f"Generated silent MP3 chunk ({len(self._silent_mp3_chunk)} bytes)")
        except Exception as e:
            logger.warning(f"Failed to generate silent MP3 chunk: {e}")
            self._silent_mp3_chunk = None
        
        # Start initial encoder
        self._start_encoder()
        
        if self._state == EncoderState.RUNNING:
            # Start monitor thread to watch for failures
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
        Start encoder process.
        
        Returns:
            bool: True if encoder started successfully, False otherwise
        """
        try:
            # Clean up old encoder if it exists
            if self.encoder is not None:
                try:
                    self.encoder.stop()
                except Exception:
                    pass
                self.encoder = None
            
            # Create and start new encoder
            self.encoder = Encoder(self.config)
            self.encoder.start()
            
            # Add 10ms warm-up before first stdout read (fixes initial EOF-race)
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
            
            with self._state_lock:
                self._state = EncoderState.RUNNING
                self._restart_attempts = 0  # Reset on successful start
            
            logger.info("Encoder started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start encoder: {e}")
            self.encoder = None
            with self._state_lock:
                if self._restart_attempts < self.max_restart_attempts:
                    self._state = EncoderState.RESTARTING
                else:
                    self._state = EncoderState.FAILED
            return False
    
    def _monitor_loop(self) -> None:
        """Monitor encoder for failures."""
        logger.debug("Encoder monitor thread started")
        
        try:
            while not self._shutdown:
                with self._state_lock:
                    state = self._state
                    encoder = self.encoder
                
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
                
                # Check stdout for EOF (non-blocking check)
                # We can't easily check stdout EOF without blocking, so we rely on
                # the encoder reader thread to detect EOF and notify us
                # For now, we check process status periodically
                time.sleep(0.1)  # Check every 100ms
                
        except Exception as e:
            logger.error(f"Encoder monitor thread error: {e}")
        finally:
            logger.debug("Encoder monitor thread stopped")
    
    def _handle_encoder_failure(self) -> None:
        """Handle encoder failure and trigger restart if needed."""
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
            self._state = EncoderState.RESTARTING
            attempt_num = self._restart_attempts + 1
        
        # Get delay from config (already handles test mode)
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
        
        # Get backoff delays from config (handles test mode automatically)
        # Config has encoder_backoff_ms in milliseconds, convert to seconds
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
    
    def notify_stdout_eof(self) -> None:
        """
        Notify EncoderManager that encoder stdout EOF was detected.
        
        This should be called by the encoder reader thread when it detects EOF.
        """
        logger.warning("Encoder stdout EOF detected")
        self._handle_encoder_failure()
    
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
        Write PCM data to encoder stdin.
        
        In RESTARTING state, attempts to write but ignores BrokenPipeError
        (AudioPump must remain non-blocking and real-time).
        
        Args:
            data: PCM frame data
            
        Returns:
            bool: True if write succeeded or was ignored (RESTARTING), False if encoder is not available
        """
        with self._state_lock:
            state = self._state
            encoder = self.encoder
        
        # In RESTARTING state, try to write but don't fail on BrokenPipeError
        if state == EncoderState.RESTARTING:
            if encoder is not None and encoder.stdin is not None:
                try:
                    encoder.stdin.write(data)
                    encoder.stdin.flush()
                except (BrokenPipeError, OSError):
                    # Encoder is restarting - ignore pipe errors, AudioPump continues
                    pass
                except Exception:
                    pass
            # Return True to indicate AudioPump should continue (non-blocking)
            return True
        
        # In RUNNING state, normal write
        if state != EncoderState.RUNNING:
            return False
        
        if encoder is None or encoder.stdin is None:
            return False
        
        try:
            encoder.stdin.write(data)
            encoder.stdin.flush()
            logger.debug(f"Wrote {len(data)} bytes of PCM to encoder")
            return True
        except (BrokenPipeError, OSError):
            # Encoder died - notify failure
            self._handle_encoder_failure()
            return False
        except Exception as e:
            logger.error(f"Unexpected error writing to encoder: {e}")
            return False
    
    def get_chunk(self, size: int) -> bytes:
        """
        Get MP3 chunk - returns real MP3 if RUNNING, silent MP3 if RESTARTING/FAILED.
        
        This method ALWAYS returns data (never None) to ensure broadcast loop never starves.
        
        Args:
            size: Number of bytes to read/return
            
        Returns:
            bytes: MP3 data (real or silent)
        """
        with self._state_lock:
            state = self._state
        
        # If RESTARTING or FAILED, return silent MP3 immediately
        if state == EncoderState.RESTARTING or state == EncoderState.FAILED:
            if self._silent_mp3_chunk:
                return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
            # Fallback: minimal MP3 header
            return _minimal_mp3_chunk(size)
        
        # If RUNNING, try to read real MP3
        if state != EncoderState.RUNNING:
            # Should not happen, but return silent MP3 as fallback
            if self._silent_mp3_chunk:
                return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
            return _minimal_mp3_chunk(size)
        
        encoder = self.encoder
        if encoder is None or encoder.stdout is None:
            # Return silent MP3 if encoder not available
            if self._silent_mp3_chunk:
                return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
            return _minimal_mp3_chunk(size)
        
        # Check if encoder process is still running
        if not encoder.is_running():
            logger.warning("Encoder process not running during read")
            self.notify_stdout_eof()
            # Return silent MP3
            if self._silent_mp3_chunk:
                return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
            return _minimal_mp3_chunk(size)
        
        try:
            # Try to read from encoder - this may block briefly, but encoder should have data
            # If encoder just started, first read might block until PCM is written
            # We use select with a reasonable timeout to avoid blocking indefinitely
            # The encoder reader thread calls this every 10ms, so a brief block is acceptable
            # FFmpeg needs time to accumulate PCM and encode it, so we use a longer timeout
            try:
                ready, _, _ = select.select([encoder.stdout], [], [], 0.1)  # 100ms timeout - gives encoder time to encode
                if not ready:
                    # No data available yet - return silent MP3 to keep broadcast going
                    # This prevents blocking the broadcast loop indefinitely
                    # This is normal when encoder is starting up or between chunks
                    logger.debug("Encoder stdout not ready, returning silent MP3")
                    if self._silent_mp3_chunk:
                        return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
                    return _minimal_mp3_chunk(size)
            except (ValueError, OSError):
                # select() doesn't work on this file object - try direct read
                # This will block, but encoder should have data soon
                pass
            
            # Data available - read it (may block briefly, but that's OK in this thread)
            data = encoder.stdout.read(size)
            if not data:
                # EOF detected
                logger.warning("Encoder stdout EOF during read")
                self.notify_stdout_eof()
                # Return silent MP3
                if self._silent_mp3_chunk:
                    return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
                return _minimal_mp3_chunk(size)
            
            # Got real MP3 data - return it
            logger.debug(f"Read {len(data)} bytes of MP3 data from encoder")
            return data
        except (BrokenPipeError, OSError):
            # Encoder died
            logger.warning("Encoder pipe error during read")
            self.notify_stdout_eof()
            # Return silent MP3
            if self._silent_mp3_chunk:
                return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
            return _minimal_mp3_chunk(size)
        except Exception as e:
            logger.error(f"Unexpected error reading from encoder: {e}")
            # Return silent MP3 on error
            if self._silent_mp3_chunk:
                return self._silent_mp3_chunk[:size] if len(self._silent_mp3_chunk) >= size else self._silent_mp3_chunk
            return _minimal_mp3_chunk(size)
    
    def read_mp3(self, size: int) -> Optional[bytes]:
        """
        Read MP3 data from encoder stdout (legacy method for compatibility).
        
        Args:
            size: Number of bytes to read
            
        Returns:
            bytes: MP3 data, or None if encoder is not available or EOF
        """
        with self._state_lock:
            if self._state != EncoderState.RUNNING:
                return None
            encoder = self.encoder
        
        if encoder is None or encoder.stdout is None:
            return None
        
        # Check if encoder process is still running
        if not encoder.is_running():
            logger.warning("Encoder process not running during read")
            self.notify_stdout_eof()
            return None
        
        try:
            # Try to read (this may block, but that's OK for encoder reader thread)
            data = encoder.stdout.read(size)
            if not data:
                # EOF detected
                logger.warning("Encoder stdout EOF during read")
                self.notify_stdout_eof()
                return None
            return data
        except (BrokenPipeError, OSError):
            # Encoder died
            logger.warning("Encoder pipe error during read")
            self.notify_stdout_eof()
            return None
        except Exception as e:
            logger.error(f"Unexpected error reading from encoder: {e}")
            return None


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

