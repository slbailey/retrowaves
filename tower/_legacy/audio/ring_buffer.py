"""
Lock-protected ring buffer for audio frames and chunks.

Provides constant-time push/pop operations with overflow handling.
When buffer is full, push() drops the newest frame (never blocks).

Supports both single-item operations (pop) and byte-accumulating operations (read).
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class RingBuffer:
    """
    Thread-safe ring buffer for audio frames and chunks.
    
    Fixed size buffer that drops newest frame on overflow (never blocks).
    Optimized for constant-time push/pop operations.
    
    Supports two usage patterns:
    - Single-item: push()/pop() for fixed-size frames
    - Accumulating: write()/read(size) for variable-size chunks that need accumulation
    """
    
    def __init__(self, size: int = 50):
        """
        Initialize ring buffer.
        
        Args:
            size: Maximum number of frames/chunks (default: 50)
        """
        if size <= 0:
            raise ValueError(f"Ring buffer size must be > 0, got {size}")
        
        self._size = size
        self._buffer: list[Optional[bytes]] = [None] * size
        self._write_pos = 0  # Next position to write
        self._read_pos = 0   # Next position to read
        self._count = 0      # Number of frames/chunks currently in buffer
        self._lock = threading.RLock()
        self._frames_dropped = 0  # Counter for dropped frames/chunks
        self._writes_logged = 0  # Counter for logging first few writes
    
    def push(self, frame: bytes) -> None:
        """
        Push a frame into the buffer.
        
        NEVER blocks. If buffer is full, drops the newest frame (the one
        being pushed) and increments frames_dropped counter.
        
        Args:
            frame: Frame bytes to push (must not be None)
        """
        if frame is None:
            raise ValueError("Cannot push None frame")
        
        with self._lock:
            if self._count < self._size:
                # Buffer has space - add frame
                self._buffer[self._write_pos] = frame
                self._write_pos = (self._write_pos + 1) % self._size
                self._count += 1
            else:
                # Buffer is full - drop newest frame (the one being pushed)
                # This ensures writer never blocks and we preserve older frames
                self._frames_dropped += 1
    
    def write(self, data: bytes) -> None:
        """
        Write data to buffer (alias for push, with optional logging).
        
        This method is provided for compatibility with code that uses write()/read() pattern.
        It's identical to push() but includes logging for the first few writes.
        
        Args:
            data: Data bytes to write (must not be None)
        """
        if data is None:
            raise ValueError("Cannot write None chunk")
        
        with self._lock:
            if self._count < self._size:
                # Buffer has space - add chunk
                self._buffer[self._write_pos] = data
                self._write_pos = (self._write_pos + 1) % self._size
                self._count += 1
                # Log first few writes to verify buffer is being written to
                self._writes_logged += 1
                if self._writes_logged <= 5:
                    logger.info(
                        f"Ring buffer write: {len(data)} bytes "
                        f"(buffer now: {self._count}/{self._size} chunks, total writes: {self._writes_logged})"
                    )
            else:
                # Buffer is full - drop newest chunk (the one being written)
                # This ensures writer never blocks and we preserve older chunks
                self._frames_dropped += 1
    
    def pop(self) -> Optional[bytes]:
        """
        Pop a frame from the buffer.
        
        Returns:
            Frame bytes if available, None if buffer is empty
        """
        with self._lock:
            if self._count == 0:
                return None
            
            frame = self._buffer[self._read_pos]
            self._buffer[self._read_pos] = None  # Clear reference
            self._read_pos = (self._read_pos + 1) % self._size
            self._count -= 1
            
            return frame
    
    def read(self, size: int) -> Optional[bytes]:
        """
        Read data from buffer (non-blocking, accumulates chunks).
        
        Accumulates chunks until requested size is available.
        Returns None if buffer is empty (caller should handle underflow).
        
        This method is useful for variable-size chunks (e.g., MP3) where
        multiple chunks need to be combined to reach a target byte size.
        
        Args:
            size: Number of bytes to read
            
        Returns:
            bytes: Data of requested size (or partial if available), or None if buffer is empty
        """
        with self._lock:
            if self._count == 0:
                return None
            
            # Accumulate chunks until we have enough bytes
            result = bytearray()
            chunks_consumed = 0
            while len(result) < size and self._count > 0:
                chunk = self._buffer[self._read_pos]
                self._buffer[self._read_pos] = None  # Clear reference
                self._read_pos = (self._read_pos + 1) % self._size
                self._count -= 1
                chunks_consumed += 1
                
                if chunk:
                    result.extend(chunk)
            
            # Return exactly requested size, or partial data if we have some
            # CRITICAL: Always return data if we have any, even if less than requested
            # This ensures stream continues even if buffer is building up
            if len(result) >= size:
                # Have enough - return exactly requested size
                return bytes(result[:size])
            elif len(result) > 0:
                # Have some data but not enough - return what we have
                # This is valid for streaming - partial frames are OK
                return bytes(result)
            else:
                # No data at all - buffer was empty
                return None
    
    def clear(self) -> None:
        """Clear all frames from buffer."""
        with self._lock:
            self._buffer = [None] * self._size
            self._write_pos = 0
            self._read_pos = 0
            self._count = 0
    
    def __len__(self) -> int:
        """Return number of frames currently in buffer."""
        with self._lock:
            return self._count
    
    @property
    def size(self) -> int:
        """Return maximum buffer size."""
        return self._size
    
    @property
    def frames_dropped(self) -> int:
        """Return total number of frames dropped due to overflow."""
        with self._lock:
            return self._frames_dropped
    
    @property
    def chunks_dropped(self) -> int:
        """Return total number of chunks dropped due to overflow (alias for frames_dropped)."""
        return self.frames_dropped
    
    def get_stats(self) -> dict:
        """
        Get buffer statistics.
        
        Returns:
            dict with size, count, utilization, and frames_dropped
        """
        with self._lock:
            return {
                "size": self._size,
                "count": self._count,
                "utilization": self._count / self._size if self._size > 0 else 0.0,
                "frames_dropped": self._frames_dropped,
                "chunks_dropped": self._frames_dropped,  # Alias for compatibility
            }

