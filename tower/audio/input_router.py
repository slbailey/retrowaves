"""
AudioInputRouter for Tower PCM input buffering.

This module provides AudioInputRouter, a thread-safe ring buffer for PCM frames
that buffers input from Station before feeding to the encoder. The router never
blocks Tower operations and provides a clean interface for frame retrieval with
optional timeout.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Optional


class AudioInputRouter:
    """
    Thread-safe ring buffer for PCM frames.
    
    Buffers PCM frames from Station (or other sources) before they are consumed
    by the encoder. When full, push_frame() drops the newest frame (not oldest)
    to maintain low latency. get_frame() supports optional timeout for blocking
    operations.
    
    Attributes:
        capacity: Maximum number of frames the buffer can hold
    """
    
    # Default capacity: 100 frames
    # At 48kHz, 1024 samples/frame = ~21.3ms per frame
    # 100 frames = ~2.13 seconds of audio
    DEFAULT_CAPACITY = 100
    
    def __init__(self, capacity: Optional[int] = None) -> None:
        """
        Initialize AudioInputRouter.
        
        Capacity is read from TOWER_PCM_BUFFER_SIZE environment variable,
        or defaults to DEFAULT_CAPACITY if not set.
        
        Args:
            capacity: Maximum number of frames (overrides env var if provided)
            
        Raises:
            ValueError: If capacity <= 0
        """
        if capacity is None:
            env_capacity = os.getenv("TOWER_PCM_BUFFER_SIZE")
            if env_capacity:
                try:
                    capacity = int(env_capacity)
                except ValueError:
                    capacity = self.DEFAULT_CAPACITY
            else:
                capacity = self.DEFAULT_CAPACITY
        
        if capacity <= 0:
            raise ValueError(f"AudioInputRouter capacity must be > 0, got {capacity}")
        
        self._capacity = capacity
        # Use deque without maxlen so we can control drop behavior
        # We manually drop newest when full
        self._buffer: deque[bytes] = deque()
        self._lock = threading.RLock()  # Reentrant lock for thread-safety
        self._condition = threading.Condition(self._lock)  # For timeout support
    
    def push_frame(self, frame: bytes) -> None:
        """
        Push a PCM frame into the buffer.
        
        If the buffer is full, the newest frame is dropped (maintains low latency
        by keeping older frames). This operation never blocks.
        
        Args:
            frame: Complete PCM frame bytes to push (must not be None or empty)
            
        Raises:
            ValueError: If frame is None or empty
        """
        if not frame:
            raise ValueError("Cannot push None or empty frame")
        
        with self._lock:
            # If full, drop newest (pop from right)
            if len(self._buffer) >= self._capacity:
                self._buffer.pop()
            
            # Append to right (FIFO: oldest at left, newest at right)
            self._buffer.append(frame)
            
            # Notify any waiting get_frame() calls
            self._condition.notify_all()
    
    def get_frame(self, timeout_ms: Optional[int] = None) -> Optional[bytes]:
        """
        Get a PCM frame from the buffer.
        
        Returns the oldest frame if available. If the buffer is empty:
        - If timeout_ms is None: returns None immediately (indicates fallback)
        - If timeout_ms is provided: waits up to timeout_ms milliseconds for a frame
        
        Args:
            timeout_ms: Optional timeout in milliseconds. None means non-blocking.
            
        Returns:
            Frame bytes if available, None if buffer is empty (or timeout expires)
        """
        with self._lock:
            # If frame available, return immediately
            if self._buffer:
                return self._buffer.popleft()  # Pop from left (oldest)
            
            # If timeout is None, return None immediately (non-blocking)
            if timeout_ms is None:
                return None
            
            # Wait for frame with timeout
            timeout_sec = timeout_ms / 1000.0
            end_time = time.monotonic() + timeout_sec
            
            while not self._buffer:
                remaining = end_time - time.monotonic()
                if remaining <= 0:
                    return None  # Timeout expired
                
                # Wait with remaining timeout
                self._condition.wait(timeout=remaining)
            
            # Frame available now
            if self._buffer:
                return self._buffer.popleft()
            
            return None
    
    def pop_frame(self, timeout_ms: Optional[int] = None) -> Optional[bytes]:
        """
        Pop a PCM frame from the buffer (alias for get_frame).
        
        Returns the oldest frame if available. If the buffer is empty:
        - If timeout_ms is None: returns None immediately (indicates fallback)
        - If timeout_ms is provided: waits up to timeout_ms milliseconds for a frame
        
        Args:
            timeout_ms: Optional timeout in milliseconds. None means non-blocking.
            
        Returns:
            Frame bytes if available, None if buffer is empty (or timeout expires)
        """
        return self.get_frame(timeout_ms=timeout_ms)
    
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

