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

from tower.audio.ring_buffer import FrameRingBuffer

logger = logging.getLogger(__name__)


class EncoderOutputDrainThread(threading.Thread):
    """
    Dedicated thread that continuously drains encoder stdout (MP3 output boundary).
    
    Reads MP3 bytes from FFmpeg stdout as fast as possible and buffers them for HTTP output.
    The internal pipeline remains 100% PCM-only. MP3 only exists at this output boundary.
    Per contract F9.1: FFmpeg handles MP3 packetization entirely.
    Detects stalls when no data is received for a threshold duration.
    
    Attributes:
        stdout: FFmpeg stdout pipe (BinaryIO)
        mp3_buffer: FrameRingBuffer to push MP3 bytes to
        stall_threshold_ms: Stall detection threshold in milliseconds
        on_stall: Callback when stall is detected
        shutdown_event: Event to signal thread shutdown
    """
    
    def __init__(
        self,
        stdout: BinaryIO,
        mp3_buffer: FrameRingBuffer,
        stall_threshold_ms: int,
        on_stall: Callable[[], None],
        shutdown_event: threading.Event,
    ) -> None:
        """
        Initialize drain thread.
        
        Args:
            stdout: FFmpeg stdout pipe (must be readable)
            mp3_buffer: FrameRingBuffer to push MP3 bytes to
            stall_threshold_ms: Stall detection threshold in milliseconds
            on_stall: Callback when stall is detected (called from this thread)
            shutdown_event: Event to signal thread shutdown
        """
        super().__init__(name="EncoderOutputDrain", daemon=False)
        self.stdout = stdout
        self.mp3_buffer = mp3_buffer
        self.stall_threshold_ms = stall_threshold_ms
        self.on_stall = on_stall
        self.shutdown_event = shutdown_event
        
        self._last_data_time: Optional[float] = None
        self._read_size = 4096  # Read ~4KB per poll
        
        # Per contract F9: MP3 frame boundary detection and accumulation
        # MP3 frame size for 128kbps @ 48kHz: (144 * bitrate_bps) / sample_rate = (144 * 128000) / 48000 = 384 bytes
        # Note: Actual MP3 frames can vary by 1 byte due to padding bit, so we use dynamic detection
        self._accumulator = bytearray()
    
    def run(self) -> None:
        """
        Main drain loop.
        
        Continuously reads MP3 from FFmpeg stdout (output boundary only) using select() for non-blocking I/O,
        and buffers for HTTP output. The internal pipeline is 100% PCM-only.
        Per contract F9.1: FFmpeg handles MP3 packetization entirely.
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
                    
                    # Per contract F9: Accumulate bytes and detect frame boundaries
                    # Append new bytes to accumulator
                    self._accumulator.extend(data)
                    
                    # Process complete frames from accumulator
                    frames_pushed = 0
                    while True:
                        # Find next MP3 frame by looking for sync word
                        sync_pos = self._find_mp3_sync(self._accumulator)
                        if sync_pos is None:
                            # No sync word found - need more data
                            break
                        
                        # Remove any data before sync word (garbage/incomplete data)
                        if sync_pos > 0:
                            self._accumulator = self._accumulator[sync_pos:]
                        
                        # Try to detect frame size starting at sync word
                        frame_size = self._detect_mp3_frame_size(self._accumulator)
                        if frame_size is None:
                            # Can't determine frame size yet - need more data
                            break
                        
                        if len(self._accumulator) < frame_size:
                            # Not enough data for this frame yet
                            break
                        
                        # Extract complete frame
                        frame = bytes(self._accumulator[:frame_size])
                        self._accumulator = self._accumulator[frame_size:]
                        
                        # Push complete frame to output buffer (per contract F9)
                        self.mp3_buffer.push_frame(frame)
                        frames_pushed += 1
                    
                    # Update last data timestamp if we pushed frames
                    if frames_pushed > 0:
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
    
    def _find_mp3_sync(self, data: bytearray) -> Optional[int]:
        """
        Find MP3 sync word position in accumulator.
        
        MP3 sync word: 0xFF followed by byte with top 3 bits = 0xE0 (0xFB-0xFF).
        
        Args:
            data: Bytearray to search for sync word
            
        Returns:
            Index of sync word if found, None otherwise
        """
        if len(data) < 2:
            return None
        
        # Search for sync word pattern: 0xFF followed by valid header byte
        for i in range(len(data) - 1):
            if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
                return i
        
        return None
    
    def _detect_mp3_frame_size(self, data: bytearray) -> Optional[int]:
        """
        Detect MP3 frame size by parsing frame header.
        
        Per contract F9: Must detect frame boundaries correctly.
        MP3 frame starts with sync word 0xFF followed by valid header byte (0xFB-0xFF).
        Frame size = (144 * bitrate_bps) / sample_rate + padding
        
        Args:
            data: Bytearray with potential MP3 frame starting at index 0
            
        Returns:
            Frame size in bytes if valid frame detected, None otherwise
        """
        if len(data) < 4:
            return None  # Need at least 4 bytes for header
        
        # Check for MP3 sync word: 0xFF followed by 0xFB-0xFF (top 3 bits must be 0xE0)
        if data[0] != 0xFF:
            return None
        
        second_byte = data[1]
        if (second_byte & 0xE0) != 0xE0:
            return None  # Invalid sync word
        
        # Parse header to get bitrate and sample rate
        # Byte 2: bitrate index (bits 4-7), sample rate index (bits 2-3), padding (bit 1)
        header_byte2 = data[2]
        
        # Extract bitrate index (bits 4-7)
        bitrate_index = (header_byte2 >> 4) & 0x0F
        # Extract sample rate index (bits 2-3)
        sample_rate_index = (header_byte2 >> 2) & 0x03
        # Extract padding bit (bit 1)
        padding = (header_byte2 >> 1) & 0x01
        
        # Bitrate lookup table (kbps)
        BITRATE_TABLE = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
        # Sample rate lookup table (Hz)
        SAMPLE_RATE_TABLE = [44100, 48000, 32000, 0]
        
        if bitrate_index >= len(BITRATE_TABLE) or sample_rate_index >= len(SAMPLE_RATE_TABLE):
            return None
        
        bitrate_kbps = BITRATE_TABLE[bitrate_index]
        sample_rate = SAMPLE_RATE_TABLE[sample_rate_index]
        
        if bitrate_kbps == 0 or sample_rate == 0:
            return None  # Invalid bitrate or sample rate
        
        # Calculate frame size: (144 * bitrate_bps) / sample_rate + padding
        bitrate_bps = bitrate_kbps * 1000
        frame_size = int((144 * bitrate_bps) / sample_rate) + padding
        
        if frame_size < 4:
            return None  # Invalid frame size
        
        return frame_size

