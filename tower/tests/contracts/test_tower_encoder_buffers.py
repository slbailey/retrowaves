"""
Contract tests for Tower Encoder Buffers

See docs/contracts/TOWER_ENCODER_CONTRACT.md
Covers: [E4]–[E6] (Dual-buffer Model)
"""

import pytest
import random
import threading
from typing import List

from tower.audio.ring_buffer import FrameRingBuffer


class TestFrameRingBuffer:
    """Tests for FrameRingBuffer covering contract [E4]–[E6]."""
    
    def test_push_pop_fifo(self):
        """Test that push/pop returns same objects in FIFO order."""
        buffer = FrameRingBuffer(capacity=10)
        
        # Push frames
        frame1 = b"frame1"
        frame2 = b"frame2"
        frame3 = b"frame3"
        
        buffer.push(frame1)
        buffer.push(frame2)
        buffer.push(frame3)
        
        # Pop should return in FIFO order
        assert buffer.pop() == frame1
        assert buffer.pop() == frame2
        assert buffer.pop() == frame3
        assert buffer.pop() is None  # Empty now
    
    def test_overflow_drops_oldest(self):
        """Test that overflow drops oldest frame [E6.3]."""
        buffer = FrameRingBuffer(capacity=3)
        
        # Fill buffer
        buffer.push(b"frame1")
        buffer.push(b"frame2")
        buffer.push(b"frame3")
        
        # Buffer is full, oldest is frame1
        assert len(buffer) == 3
        assert buffer.is_full()
        
        # Push one more - should drop frame1
        buffer.push(b"frame4")
        
        # frame1 should be gone, frame2 should be oldest
        assert len(buffer) == 3
        assert buffer.pop() == b"frame2"
        assert buffer.pop() == b"frame3"
        assert buffer.pop() == b"frame4"
        assert buffer.pop() is None
    
    def test_len_updates_correctly(self):
        """Test that len() updates correctly."""
        buffer = FrameRingBuffer(capacity=5)
        
        assert len(buffer) == 0
        assert buffer.is_empty()
        assert not buffer.is_full()
        
        buffer.push(b"frame1")
        assert len(buffer) == 1
        assert not buffer.is_empty()
        assert not buffer.is_full()
        
        buffer.push(b"frame2")
        assert len(buffer) == 2
        
        buffer.push(b"frame3")
        buffer.push(b"frame4")
        buffer.push(b"frame5")
        assert len(buffer) == 5
        assert buffer.is_full()
        
        buffer.pop()
        assert len(buffer) == 4
        assert not buffer.is_full()
        
        buffer.pop()
        buffer.pop()
        buffer.pop()
        buffer.pop()
        assert len(buffer) == 0
        assert buffer.is_empty()
    
    def test_no_blocking_behavior(self):
        """Test that operations never block [E6.3], [E6.4]."""
        buffer = FrameRingBuffer(capacity=2)
        
        # Pop from empty buffer should return None immediately (non-blocking)
        result = buffer.pop()
        assert result is None
        
        # Push when full should drop oldest immediately (non-blocking)
        buffer.push(b"frame1")
        buffer.push(b"frame2")
        assert buffer.is_full()
        
        # This should not block, just drop oldest
        buffer.push(b"frame3")
        assert len(buffer) == 2
        assert buffer.pop() == b"frame2"  # frame1 was dropped
    
    def test_handles_thousands_of_operations(self):
        """Test that buffer handles thousands of pushes/pops correctly."""
        buffer = FrameRingBuffer(capacity=100)
        
        # Push 1000 frames (buffer will drop oldest after 100)
        for i in range(1000):
            buffer.push(f"frame{i}".encode())
        
        # Should only have last 100 frames
        assert len(buffer) == 100
        assert buffer.is_full()
        
        # First frame should be frame900 (oldest of the 100)
        first = buffer.pop()
        assert first == b"frame900"
        
        # Pop all remaining
        count = 1
        while buffer.pop() is not None:
            count += 1
        
        assert count == 100
        assert buffer.is_empty()
        
        # Now push and pop many times
        for i in range(500):
            buffer.push(f"test{i}".encode())
            if i % 2 == 0:
                popped = buffer.pop()
                assert popped is not None
    
    def test_thread_safety_smoke(self):
        """Simple thread-safety smoke test with concurrent pushes."""
        buffer = FrameRingBuffer(capacity=100)
        results: List[bytes] = []
        errors: List[Exception] = []
        
        def push_worker(worker_id: int, count: int):
            """Worker that pushes frames."""
            try:
                for i in range(count):
                    buffer.push(f"worker{worker_id}_frame{i}".encode())
            except Exception as e:
                errors.append(e)
        
        def pop_worker(count: int):
            """Worker that pops frames."""
            try:
                for _ in range(count):
                    frame = buffer.pop()
                    if frame is not None:
                        results.append(frame)
            except Exception as e:
                errors.append(e)
        
        # Start multiple push threads
        threads = []
        for worker_id in range(5):
            t = threading.Thread(target=push_worker, args=(worker_id, 50))
            threads.append(t)
            t.start()
        
        # Start a pop thread
        pop_thread = threading.Thread(target=pop_worker, args=(250,))
        threads.append(pop_thread)
        pop_thread.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Should have no errors
        assert len(errors) == 0, f"Thread safety errors: {errors}"
        
        # Pop remaining frames
        while True:
            frame = buffer.pop()
            if frame is None:
                break
            results.append(frame)
        
        # Should have received some frames (exact count depends on timing)
        assert len(results) > 0
    
    def test_capacity_property(self):
        """Test capacity property."""
        buffer = FrameRingBuffer(capacity=42)
        assert buffer.capacity == 42
    
    def test_empty_frame_rejected(self):
        """Test that empty frames are rejected."""
        buffer = FrameRingBuffer(capacity=10)
        
        with pytest.raises(ValueError, match="Cannot push None or empty frame"):
            buffer.push(b"")
        
        with pytest.raises(ValueError, match="Cannot push None or empty frame"):
            buffer.push(None)  # type: ignore
    
    def test_zero_capacity_rejected(self):
        """Test that zero or negative capacity is rejected."""
        with pytest.raises(ValueError, match="capacity must be > 0"):
            FrameRingBuffer(capacity=0)
        
        with pytest.raises(ValueError, match="capacity must be > 0"):
            FrameRingBuffer(capacity=-1)
