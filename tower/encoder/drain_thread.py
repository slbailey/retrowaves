"""
Encoder output drain thread.

This module provides EncoderOutputDrainThread, a dedicated thread that
continuously drains FFmpeg stdout, packetizes MP3 frames, and feeds them
to the MP3 buffer. It also detects encoder stalls.
"""

from __future__ import annotations

import logging
import select
import threading
import time
from typing import BinaryIO, Callable, Optional

from tower.audio.mp3_packetizer import MP3Packetizer
from tower.audio.ring_buffer import FrameRingBuffer

logger = logging.getLogger(__name__)


class EncoderOutputDrainThread(threading.Thread):
    """
    Dedicated thread that continuously drains encoder stdout.
    
    Reads MP3 bytes from FFmpeg stdout as fast as possible, feeds them
    to MP3Packetizer, and pushes complete frames to the MP3 buffer.
    Detects stalls when no data is received for a threshold duration.
    
    Attributes:
        stdout: FFmpeg stdout pipe (BinaryIO)
        mp3_buffer: FrameRingBuffer to push complete frames to
        packetizer: MP3Packetizer instance
        stall_threshold_ms: Stall detection threshold in milliseconds
        on_stall: Callback when stall is detected
        shutdown_event: Event to signal thread shutdown
    """
    
    def __init__(
        self,
        stdout: BinaryIO,
        mp3_buffer: FrameRingBuffer,
        packetizer: MP3Packetizer,
        stall_threshold_ms: int,
        on_stall: Callable[[], None],
        shutdown_event: threading.Event,
    ) -> None:
        """
        Initialize drain thread.
        
        Args:
            stdout: FFmpeg stdout pipe (must be readable)
            mp3_buffer: FrameRingBuffer to push complete frames to
            packetizer: MP3Packetizer instance
            stall_threshold_ms: Stall detection threshold in milliseconds
            on_stall: Callback when stall is detected (called from this thread)
            shutdown_event: Event to signal thread shutdown
        """
        super().__init__(name="EncoderOutputDrain", daemon=False)
        self.stdout = stdout
        self.mp3_buffer = mp3_buffer
        self.packetizer = packetizer
        self.stall_threshold_ms = stall_threshold_ms
        self.on_stall = on_stall
        self.shutdown_event = shutdown_event
        
        self._last_data_time: Optional[float] = None
        self._read_size = 4096  # Read ~4KB per poll
    
    def run(self) -> None:
        """
        Main drain loop.
        
        Continuously reads from stdout using select() for non-blocking I/O,
        feeds bytes to packetizer, and pushes complete frames to buffer.
        Detects stalls and notifies EncoderManager.
        """
        logger.info("Encoder output drain thread started")
        
        try:
            while not self.shutdown_event.is_set():
                # Use select() with timeout for non-blocking I/O
                # Timeout allows periodic stall checks and shutdown checks
                try:
                    ready, _, _ = select.select([self.stdout], [], [], 0.1)  # 100ms timeout
                except (OSError, ValueError) as e:
                    # stdout closed or invalid
                    logger.warning(f"Select error in drain thread: {e}")
                    break
                
                if ready:
                    # Data available - read bytes
                    try:
                        data = self.stdout.read(self._read_size)
                    except (OSError, ValueError) as e:
                        logger.warning(f"Read error in drain thread: {e}")
                        break
                    
                    if not data:
                        # EOF - encoder died
                        logger.warning("Encoder stdout EOF - encoder process ended")
                        self.on_stall()
                        break
                    
                    # Feed bytes to packetizer and get complete frames
                    for frame in self.packetizer.feed(data):
                        # Push complete frames to buffer
                        self.mp3_buffer.push_frame(frame)
                    
                    # Update last data timestamp
                    self._last_data_time = time.monotonic()
                    
                else:
                    # No data available - check for stall
                    if self._last_data_time is not None:
                        now = time.monotonic()
                        elapsed_ms = (now - self._last_data_time) * 1000.0
                        
                        if elapsed_ms >= self.stall_threshold_ms:
                            logger.warning(
                                f"Encoder stall detected: {elapsed_ms:.0f}ms without data "
                                f"(threshold: {self.stall_threshold_ms}ms)"
                            )
                            self.on_stall()
                            break
        except Exception as e:
            logger.error(f"Unexpected error in drain thread: {e}", exc_info=True)
        finally:
            logger.debug("Encoder output drain thread stopped")
    
    def stop(self, timeout: float = 2.0) -> None:
        """
        Stop drain thread.
        
        Args:
            timeout: Maximum time to wait for thread to stop
        """
        self.shutdown_event.set()
        if self.is_alive():
            self.join(timeout=timeout)
            if self.is_alive():
                logger.warning("Drain thread did not stop within timeout")

