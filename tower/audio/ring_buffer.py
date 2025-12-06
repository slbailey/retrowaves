"""
Thread-safe frame-based ring buffer for MP3 frames.

This module provides FrameRingBuffer, a production-quality ring buffer
designed for the Tower encoding subsystem. It stores complete MP3 frames
only (no partials) and never blocks on operations.

This buffer is the "MP3 output buffer" described in the Tower Unified
Architecture and BROADCAST ENCODER ARCHITECTURE. It provides ~5 seconds
of buffering depth (~400 frames at ~66 frames/second) to handle network
jitter, encoder restarts, and system scheduling delays.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class FrameRingBufferStats:
    """
    Statistics for FrameRingBuffer.
    
    Per contract [B20]: Returns count, capacity, overflow_count.
    
    Attributes:
        capacity: Maximum number of frames the buffer can hold
        count: Current number of frames in the buffer (per contract [B20])
        overflow_count: Total number of frames dropped due to buffer being full (per contract [B20])
    """
    capacity: int
    count: int  # Per contract [B20]
    overflow_count: int  # Per contract [B20]


class FrameRingBuffer:
    """
    Thread-safe frame-based ring buffer for MP3 frames.
    
    This is the "MP3 output buffer" described in the Tower Unified Architecture
    and BROADCAST ENCODER ARCHITECTURE. It provides ~5 seconds of buffering depth
    (~400 frames at ~66 frames/second) to handle:
    - Network jitter (client connection delays)
    - Encoder restart delays (1-10 seconds)
    - FFmpeg processing latency
    - System scheduling delays
    
    Stores complete MP3 frames only (no partials). Frame boundaries are preserved
    throughout the pipeline. Multiple frames can be joined only at the socket edge
    (when writing to clients).
    
    Thread-safe and non-blocking. All operations are O(1).
    Safe for concurrent access from multiple threads (drain thread + tick loop).
    
    When full, push_frame() drops the oldest frame (not the new one) to maintain
    low latency while preserving buffering depth.
    
    Attributes:
        capacity: Maximum number of frames the buffer can hold
    """
    
    def __init__(self, capacity: int) -> None:
        """
        Initialize MP3 frame ring buffer.
        
        Args:
            capacity: Maximum number of frames (must be > 0)
                     Typical value: 400 frames (~5 seconds @ ~66 fps)
            
        Raises:
            ValueError: If capacity <= 0
        """
        if capacity <= 0:
            raise ValueError(f"FrameRingBuffer capacity must be > 0, got {capacity}")
        
        self._capacity = capacity
        # Use deque with maxlen for automatic oldest-frame dropping
        # When full, append() automatically removes oldest (popleft())
        # This is O(1) and thread-safe with our RLock
        self._buffer: deque[bytes] = deque(maxlen=capacity)
        self._lock = threading.RLock()  # Reentrant lock for thread-safety
        self._condition = threading.Condition(self._lock)  # Condition variable for timeout support
        
        # Statistics tracking
        self._total_pushed = 0
        self._total_dropped = 0
    
    def push_frame(self, frame: bytes) -> None:
        """
        Push a complete MP3 frame into the buffer.
        
        If the buffer is full, the oldest frame is automatically discarded
        (deque with maxlen handles this). This operation never blocks.
        
        This method tracks statistics: increments total_pushed, and if a frame
        was dropped, increments total_dropped.
        
        Args:
            frame: Complete MP3 frame bytes to push (must not be None or empty)
            
        Raises:
            ValueError: If frame is None or empty
        """
        if not frame:
            raise ValueError("Cannot push None or empty frame")
        
        with self._lock:
            # Check if buffer is full before appending
            # If full, deque will drop oldest automatically
            was_full = len(self._buffer) >= self._capacity
            
            # Append frame (drops oldest if full)
            self._buffer.append(frame)
            
            # Notify any waiting threads that a frame is available
            self._condition.notify_all()
            
            # Update statistics
            self._total_pushed += 1
            if was_full:
                self._total_dropped += 1
    
    def pop_frame(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """
        Pop a complete MP3 frame from the buffer.
        
        Returns the oldest frame if available, None if buffer is empty.
        
        Args:
            timeout: Optional timeout in seconds. If None, returns immediately (non-blocking).
                    If timeout > 0, waits up to timeout seconds for a frame to arrive.
        
        Returns:
            Complete MP3 frame bytes if available, None if buffer is empty (or timeout expires)
        """
        with self._lock:
            # If frame available, return immediately
            if self._buffer:
                return self._buffer.popleft()
            
            # If timeout is None, return None immediately (non-blocking)
            if timeout is None or timeout <= 0:
                return None
            
            # Wait for frame with timeout using condition variable
            end_time = time.monotonic() + timeout
            
            while not self._buffer:
                remaining = end_time - time.monotonic()
                if remaining <= 0:
                    return None  # Timeout expired
                
                # Wait with remaining timeout (condition variable is already associated with _lock)
                self._condition.wait(timeout=remaining)
            
            # Frame available now
            if self._buffer:
                return self._buffer.popleft()
            
            return None
    
    def clear(self) -> None:
        """
        Clear all frames from the buffer.
        
        Resets the buffer to empty state. Statistics (total_pushed, total_dropped)
        are preserved.
        """
        with self._lock:
            self._buffer.clear()
    
    def stats(self) -> FrameRingBufferStats:
        """
        Get buffer statistics.
        
        Returns a snapshot of current buffer state and statistics.
        Thread-safe.
        
        Returns:
            FrameRingBufferStats with capacity, count, overflow_count (per contract [B20])
        """
        with self._lock:
            return FrameRingBufferStats(
                capacity=self._capacity,
                count=len(self._buffer),  # Per contract [B20]
                overflow_count=self._total_dropped,  # Per contract [B20]
            )
    
    # Backwards compatibility methods (delegate to new API)
    def push(self, frame: bytes) -> None:
        """
        Push a frame (backwards compatibility).
        
        Delegates to push_frame(). Use push_frame() for new code.
        
        Args:
            frame: Complete frame bytes to push
        """
        self.push_frame(frame)
    
    def pop(self) -> Optional[bytes]:
        """
        Pop a frame (backwards compatibility).
        
        Delegates to pop_frame(). Use pop_frame() for new code.
        
        Returns:
            Frame bytes if available, None if empty
        """
        return self.pop_frame()
    
    def __len__(self) -> int:
        """
        Return the number of frames currently in the buffer.
        
        Returns:
            Number of frames (0 to capacity)
        """
        with self._lock:
            return len(self._buffer)
    
    def is_full(self) -> bool:
        """
        Check if the buffer is full.
        
        Returns:
            True if buffer is at capacity, False otherwise
        """
        with self._lock:
            return len(self._buffer) >= self._capacity
    
    def is_empty(self) -> bool:
        """
        Check if the buffer is empty.
        
        Returns:
            True if buffer is empty, False otherwise
        """
        with self._lock:
            return len(self._buffer) == 0
    
    @property
    def capacity(self) -> int:
        """
        Get the buffer capacity.
        
        Returns:
            Maximum number of frames the buffer can hold
        """
        return self._capacity
