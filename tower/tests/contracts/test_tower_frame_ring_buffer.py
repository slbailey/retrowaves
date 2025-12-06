"""
Contract tests for Tower FrameRingBuffer

See docs/contracts/FRAME_RING_BUFFER_CONTRACT.md
Covers: [B1]–[B21] (Core invariants, thread safety, overflow/underflow, interface, frame semantics, statistics)
"""

import pytest
import threading
import time
from typing import List

from tower.audio.ring_buffer import FrameRingBuffer, FrameRingBufferStats


class TestFrameRingBufferCoreInvariants:
    """Tests for core invariants [B1]–[B4]."""
    
    def test_b1_complete_frames_only(self):
        """Test [B1]: FrameRingBuffer stores complete frames only."""
        buffer = FrameRingBuffer(capacity=10)
        
        # Push complete frames
        frame1 = b"complete_frame_1" * 100
        frame2 = b"complete_frame_2" * 100
        
        buffer.push_frame(frame1)
        buffer.push_frame(frame2)
        
        # Pop should return complete frames
        popped1 = buffer.pop_frame()
        popped2 = buffer.pop_frame()
        
        assert popped1 == frame1
        assert popped2 == frame2
        assert len(popped1) == len(frame1)
        assert len(popped2) == len(frame2)
    
    def test_b2_bounded(self):
        """Test [B2]: FrameRingBuffer is bounded (fixed capacity)."""
        buffer = FrameRingBuffer(capacity=5)
        
        # Fill to capacity
        for i in range(5):
            buffer.push_frame(f"frame{i}".encode())
        
        assert len(buffer) == 5
        assert buffer.is_full()
        
        # Push more - should not exceed capacity
        buffer.push_frame(b"frame6")
        assert len(buffer) == 5  # Still at capacity
    
    def test_b3_thread_safe(self):
        """Test [B3]: FrameRingBuffer is thread-safe."""
        buffer = FrameRingBuffer(capacity=100)
        errors = []
        
        def worker(worker_id: int, count: int):
            try:
                for i in range(count):
                    buffer.push_frame(f"w{worker_id}_f{i}".encode())
                    buffer.pop_frame()
            except Exception as e:
                errors.append(e)
        
        threads = []
        for worker_id in range(10):
            t = threading.Thread(target=worker, args=(worker_id, 20))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join(timeout=10.0)
            assert not t.is_alive(), "Thread should have completed"
        
        assert len(errors) == 0, f"Thread safety errors: {errors}"
    
    def test_b4_non_blocking(self):
        """Test [B4]: FrameRingBuffer operations are non-blocking."""
        buffer = FrameRingBuffer(capacity=10)
        
        # Pop from empty should return immediately
        start = time.time()
        frame = buffer.pop_frame()
        elapsed = time.time() - start
        
        assert frame is None
        assert elapsed < 0.01  # Should return immediately


class TestFrameRingBufferThreadSafety:
    """Tests for thread safety model [B5]–[B8]."""
    
    def test_b5_multi_producer_multi_consumer(self):
        """Test [B5]: Supports multi-producer, multi-consumer model."""
        buffer = FrameRingBuffer(capacity=200)
        results: List[bytes] = []
        errors: List[Exception] = []
        
        def producer(worker_id: int, count: int):
            try:
                for i in range(count):
                    buffer.push_frame(f"p{worker_id}_f{i}".encode())
            except Exception as e:
                errors.append(e)
        
        def consumer(count: int):
            try:
                for _ in range(count):
                    frame = buffer.pop_frame()
                    if frame is not None:
                        results.append(frame)
            except Exception as e:
                errors.append(e)
        
        # Multiple producers
        prod_threads = []
        for worker_id in range(5):
            t = threading.Thread(target=producer, args=(worker_id, 40))
            prod_threads.append(t)
            t.start()
        
        # Multiple consumers
        cons_threads = []
        for _ in range(3):
            t = threading.Thread(target=consumer, args=(70,))
            cons_threads.append(t)
            t.start()
        
        # Wait for all
        for t in prod_threads + cons_threads:
            t.join(timeout=10.0)
            assert not t.is_alive()
        
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) > 0
    
    def test_b6_rlock_protection(self):
        """Test [B6]: All operations are protected by a reentrant lock."""
        buffer = FrameRingBuffer(capacity=10)
        
        # Verify lock exists per contract [B6]
        assert hasattr(buffer, '_lock'), \
            "Contract [B6] requires self._lock to exist"
        
        # Validate reentrancy: acquire lock multiple times in same thread
        # Per contract [B6], tests MUST validate reentrancy rather than class identity
        lock = buffer._lock
        
        # First acquire
        lock.acquire()
        try:
            # Second acquire (reentrant) - should not deadlock
            lock.acquire()
            try:
                # Third acquire (reentrant) - should not deadlock
                lock.acquire()
                try:
                    # Lock is held 3 times - verify we can still use buffer
                    buffer.push_frame(b"test_frame")
                    stats = buffer.stats()
                    assert stats.count == 1
                finally:
                    # Release third acquire
                    lock.release()
            finally:
                # Release second acquire
                lock.release()
        finally:
            # Release first acquire
            lock.release()
        
        # Verify lock is fully released and buffer is still accessible
        assert buffer.pop_frame() == b"test_frame"
    
    def test_b7_no_deadlock(self):
        """Test [B7]: push_frame() and pop_frame() can be called concurrently without deadlock."""
        buffer = FrameRingBuffer(capacity=100)
        completed = threading.Event()
        
        def pusher():
            for i in range(100):
                buffer.push_frame(f"frame{i}".encode())
            completed.set()
        
        def popper():
            count = 0
            while count < 100 or not completed.is_set():
                frame = buffer.pop_frame()
                if frame is not None:
                    count += 1
                if completed.is_set() and len(buffer) == 0:
                    break
        
        push_thread = threading.Thread(target=pusher)
        pop_thread = threading.Thread(target=popper)
        
        push_thread.start()
        pop_thread.start()
        
        push_thread.join(timeout=5.0)
        pop_thread.join(timeout=5.0)
        
        assert not push_thread.is_alive()
        assert not pop_thread.is_alive()
    
    def test_b8_explicit_thread_safety(self):
        """Test [B8]: Thread safety is explicitly guaranteed."""
        # Verified by RLock usage in implementation
        buffer = FrameRingBuffer(capacity=10)
        assert hasattr(buffer, '_lock')


class TestFrameRingBufferOverflow:
    """Tests for overflow strategy [B9]–[B11]."""
    
    def test_b9_mp3_buffer_drops_oldest(self):
        """Test [B9]: MP3 buffer drops oldest frame when full."""
        buffer = FrameRingBuffer(capacity=3)
        
        # Fill buffer
        buffer.push_frame(b"frame1")
        buffer.push_frame(b"frame2")
        buffer.push_frame(b"frame3")
        
        assert len(buffer) == 3
        
        # Push one more - should drop oldest (frame1)
        buffer.push_frame(b"frame4")
        
        assert len(buffer) == 3
        assert buffer.pop_frame() == b"frame2"  # frame1 was dropped
        assert buffer.pop_frame() == b"frame3"
        assert buffer.pop_frame() == b"frame4"
    
    def test_b10_never_blocks_or_raises(self):
        """Test [B10]: Never blocks or raises exception on overflow."""
        buffer = FrameRingBuffer(capacity=1)
        
        buffer.push_frame(b"frame1")
        assert buffer.is_full()
        
        # Should not block
        start = time.time()
        buffer.push_frame(b"frame2")
        elapsed = time.time() - start
        
        assert elapsed < 0.01
        assert len(buffer) == 1
    
    def test_b11_overflow_counter_tracked(self):
        """Test [B11]: Overflow counter is tracked for monitoring."""
        buffer = FrameRingBuffer(capacity=2)
        
        # Fill and overflow
        buffer.push_frame(b"frame1")
        buffer.push_frame(b"frame2")
        buffer.push_frame(b"frame3")  # Should drop frame1
        
        stats = buffer.stats()
        assert stats.overflow_count > 0  # Per contract [B20]


class TestFrameRingBufferUnderflow:
    """Tests for underflow strategy [B12]–[B13]."""
    
    def test_b12_returns_none_immediately(self):
        """Test [B12]: Returns None immediately when empty (non-blocking)."""
        buffer = FrameRingBuffer(capacity=10)
        
        start = time.time()
        frame = buffer.pop_frame()
        elapsed = time.time() - start
        
        assert frame is None
        assert elapsed < 0.01  # Immediate return
    
    def test_b12_with_timeout_waits(self):
        """Test [B12]: With timeout, waits for frame."""
        buffer = FrameRingBuffer(capacity=10)
        
        def delayed_push():
            time.sleep(0.01)
            buffer.push_frame(b"delayed")
        
        thread = threading.Thread(target=delayed_push)
        thread.start()
        
        start = time.time()
        frame = buffer.pop_frame(timeout=0.05)
        elapsed = time.time() - start
        
        thread.join(timeout=1.0)
        
        assert frame == b"delayed"
        assert 0.008 < elapsed < 0.1
    
    def test_b13_underflow_expected(self):
        """Test [B13]: Underflow is expected behavior (not an error)."""
        buffer = FrameRingBuffer(capacity=10)
        
        # Empty buffer returning None is normal
        frame = buffer.pop_frame()
        assert frame is None  # Not an error condition


class TestFrameRingBufferInterface:
    """Tests for interface contract [B14]–[B16]."""
    
    def test_b14_constructor_capacity(self):
        """Test [B14]: Constructor takes capacity: int."""
        buffer = FrameRingBuffer(capacity=42)
        assert buffer.capacity == 42
    
    def test_b15_push_frame_method(self):
        """Test [B15]: Provides push_frame(frame: bytes) method."""
        buffer = FrameRingBuffer(capacity=10)
        
        buffer.push_frame(b"test_frame")
        assert len(buffer) == 1
    
    def test_b15_pop_frame_method(self):
        """Test [B15]: Provides pop_frame() -> Optional[bytes] method."""
        buffer = FrameRingBuffer(capacity=10)
        
        buffer.push_frame(b"test")
        frame = buffer.pop_frame()
        assert frame == b"test"
    
    def test_b15_clear_method(self):
        """Test [B15]: Provides clear() -> None method."""
        buffer = FrameRingBuffer(capacity=10)
        
        buffer.push_frame(b"frame1")
        buffer.push_frame(b"frame2")
        assert len(buffer) == 2
        
        buffer.clear()
        assert len(buffer) == 0
    
    def test_b15_stats_method(self):
        """Test [B15]: Provides stats() -> FrameRingBufferStats method."""
        buffer = FrameRingBuffer(capacity=10)
        
        stats = buffer.stats()
        assert isinstance(stats, FrameRingBufferStats)
        assert stats.capacity == 10
        assert stats.count == 0  # Per contract [B20]
    
    def test_b16_o1_time_complexity(self):
        """Test [B16]: All methods are O(1) time complexity."""
        buffer = FrameRingBuffer(capacity=1000)
        
        # Push many frames - should be fast
        start = time.time()
        for i in range(1000):
            buffer.push_frame(f"frame{i}".encode())
        elapsed = time.time() - start
        
        # Should complete quickly (O(1) per operation)
        assert elapsed < 0.1  # 1000 operations should be < 100ms


class TestFrameRingBufferFrameSemantics:
    """Tests for frame semantics [B17]–[B19]."""
    
    def test_b17_arbitrary_bytes(self):
        """Test [B17]: FrameRingBuffer stores arbitrary non-empty bytes."""
        buffer = FrameRingBuffer(capacity=10)
        
        # Can store any non-empty bytes per contract [B17]
        buffer.push_frame(b"any_bytes")
        buffer.push_frame(b"\x00\x01\x02\xff")
        buffer.push_frame(b"x")  # Single byte is valid
        
        # Empty frame MUST be rejected per contract [B17]
        with pytest.raises(ValueError, match="empty frame"):
            buffer.push_frame(b"")
        
        # None MUST be rejected per contract [B17]
        with pytest.raises(ValueError, match="None or empty"):
            buffer.push_frame(None)
    
    def test_b18_no_format_validation(self):
        """Test [B18]: No format validation (caller responsible)."""
        buffer = FrameRingBuffer(capacity=10)
        
        # Can push any bytes - no validation
        buffer.push_frame(b"not_mp3_frame")
        buffer.push_frame(b"also_not_mp3")
        
        frame = buffer.pop_frame()
        assert frame == b"not_mp3_frame"
    
    def test_b19_frame_boundaries_preserved(self):
        """Test [B19]: Frame boundaries are preserved."""
        buffer = FrameRingBuffer(capacity=10)
        
        frame1 = b"frame1_data"
        frame2 = b"frame2_data"
        
        buffer.push_frame(frame1)
        buffer.push_frame(frame2)
        
        popped1 = buffer.pop_frame()
        popped2 = buffer.pop_frame()
        
        assert popped1 == frame1
        assert popped2 == frame2
        # Frames are never split or merged
        assert len(popped1) == len(frame1)
        assert len(popped2) == len(frame2)


class TestFrameRingBufferStatistics:
    """Tests for statistics [B20]–[B21]."""
    
    def test_b20_stats_returns_count_capacity_overflow(self):
        """Test [B20]: stats() returns count, capacity, overflow_count."""
        buffer = FrameRingBuffer(capacity=5)
        
        stats = buffer.stats()
        assert stats.capacity == 5
        assert stats.count == 0  # Per contract [B20]
        assert stats.overflow_count == 0  # Per contract [B20]
        
        # Push frames
        buffer.push_frame(b"frame1")
        buffer.push_frame(b"frame2")
        
        stats = buffer.stats()
        assert stats.count == 2  # Per contract [B20]
        
        # Overflow
        buffer.push_frame(b"frame3")
        buffer.push_frame(b"frame4")
        buffer.push_frame(b"frame5")
        buffer.push_frame(b"frame6")  # Should drop frame1
        
        stats = buffer.stats()
        assert stats.overflow_count > 0  # Per contract [B20]
    
    def test_b21_stats_thread_safe(self):
        """Test [B21]: Statistics are thread-safe."""
        buffer = FrameRingBuffer(capacity=100)
        errors = []
        
        def worker():
            try:
                for i in range(50):
                    buffer.push_frame(f"frame{i}".encode())
                    buffer.stats()  # Call stats concurrently
            except Exception as e:
                errors.append(e)
        
        threads = []
        for _ in range(10):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join(timeout=10.0)
        
        assert len(errors) == 0, f"Errors: {errors}"
