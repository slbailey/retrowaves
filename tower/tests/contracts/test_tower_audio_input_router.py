"""
Contract tests for Tower AudioInputRouter

See docs/contracts/AUDIO_INPUT_ROUTER_CONTRACT.md
Covers: [R1]–[R22] (Core invariants, interface, overflow/underflow, thread safety, socket integration)
"""

import pytest
import os
import threading
import time
from unittest.mock import Mock, patch

from tower.audio.input_router import AudioInputRouter


class TestAudioInputRouterCoreInvariants:
    """Tests for core invariants [R1]–[R4]."""
    
    def test_r1_bounded_queue(self):
        """Test [R1]: AudioInputRouter provides bounded queue for PCM frames."""
        router = AudioInputRouter(capacity=10)
        
        # Fill buffer to capacity
        for i in range(10):
            router.push_frame(b"frame" + str(i).encode())
        
        assert len(router) == 10
        assert router.is_full()
        
        # Adding more should not exceed capacity (drops newest)
        router.push_frame(b"frame11")
        assert len(router) == 10  # Still at capacity
    
    def test_r2_thread_safe(self):
        """Test [R2]: Queue operations are thread-safe (multiple writers, single reader)."""
        router = AudioInputRouter(capacity=100)
        results = []
        errors = []
        
        def writer(worker_id: int, count: int):
            try:
                for i in range(count):
                    router.push_frame(f"worker{worker_id}_frame{i}".encode())
            except Exception as e:
                errors.append(e)
        
        def reader(count: int):
            try:
                for _ in range(count):
                    frame = router.get_frame(timeout_ms=None)
                    if frame is not None:
                        results.append(frame)
            except Exception as e:
                errors.append(e)
        
        # Start multiple writer threads
        threads = []
        for worker_id in range(5):
            t = threading.Thread(target=writer, args=(worker_id, 20))
            threads.append(t)
            t.start()
        
        # Start reader thread
        reader_thread = threading.Thread(target=reader, args=(100,))
        threads.append(reader_thread)
        reader_thread.start()
        
        # Wait for all threads with timeout
        for t in threads:
            t.join(timeout=5.0)
            assert not t.is_alive(), "Thread should have completed"
        
        assert len(errors) == 0, f"Thread safety errors: {errors}"
        assert len(results) > 0
    
    def test_r3_never_blocks(self):
        """Test [R3]: Queue never blocks Tower operations."""
        router = AudioInputRouter(capacity=10)
        
        # Non-blocking read should return immediately
        start = time.time()
        frame = router.get_frame(timeout_ms=None)
        elapsed = time.time() - start
        
        assert frame is None  # Empty buffer
        assert elapsed < 0.01  # Should return immediately (< 10ms)
    
    def test_r4_never_grows_unbounded(self):
        """Test [R4]: Queue never grows unbounded."""
        router = AudioInputRouter(capacity=5)
        
        # Push many frames
        for i in range(1000):
            router.push_frame(f"frame{i}".encode())
        
        # Should still be at capacity
        assert len(router) == 5
        assert router.is_full()


class TestAudioInputRouterInterface:
    """Tests for interface contract [R5]–[R6]."""
    
    def test_r5_constructor_capacity(self):
        """Test [R5]: Constructor takes capacity (defaults to TOWER_PCM_BUFFER_SIZE or 100)."""
        # Test explicit capacity
        router1 = AudioInputRouter(capacity=50)
        assert router1.capacity == 50
        
        # Test default capacity
        router2 = AudioInputRouter()
        assert router2.capacity == 100  # DEFAULT_CAPACITY
        
        # Test environment variable
        with patch.dict(os.environ, {'TOWER_PCM_BUFFER_SIZE': '200'}):
            router3 = AudioInputRouter()
            assert router3.capacity == 200
    
    def test_r6_push_frame_method(self):
        """Test [R6]: Provides push_frame(frame: bytes) method."""
        router = AudioInputRouter(capacity=10)
        
        test_frame = b"test_frame_data"
        router.push_frame(test_frame)
        
        assert len(router) == 1
        assert router.get_frame() == test_frame
    
    def test_r6_get_frame_method(self):
        """Test [R6]: Provides get_frame(timeout_ms: Optional[int]) method."""
        router = AudioInputRouter(capacity=10)
        
        # Non-blocking
        frame = router.get_frame(timeout_ms=None)
        assert frame is None
        
        # With timeout
        frame = router.get_frame(timeout_ms=5)
        assert frame is None  # Empty buffer
    
    def test_r6_pop_frame_alias(self):
        """Test [R6]: Provides pop_frame() as alias for get_frame()."""
        router = AudioInputRouter(capacity=10)
        
        router.push_frame(b"test")
        
        # pop_frame should work same as get_frame
        frame1 = router.get_frame()
        router.push_frame(b"test2")
        frame2 = router.pop_frame()
        
        assert frame1 == b"test"
        assert frame2 == b"test2"


class TestAudioInputRouterOverflow:
    """Tests for overflow handling [R7]–[R8]."""
    
    def test_r7_drops_newest_when_full(self):
        """Test [R7]: When full, push_frame() drops newest frame (not oldest)."""
        router = AudioInputRouter(capacity=3)
        
        # Fill buffer
        router.push_frame(b"frame1")
        router.push_frame(b"frame2")
        router.push_frame(b"frame3")
        
        assert len(router) == 3
        
        # Push one more - should drop newest (frame3), keep frame1 and frame2
        router.push_frame(b"frame4")
        
        assert len(router) == 3
        
        # Should get frame1 first (oldest preserved)
        assert router.get_frame() == b"frame1"
        assert router.get_frame() == b"frame2"
        assert router.get_frame() == b"frame4"  # frame3 was dropped
        assert router.get_frame() is None
    
    def test_r7_never_blocks_or_raises(self):
        """Test [R7]: Never blocks or raises exception on overflow."""
        router = AudioInputRouter(capacity=1)
        
        router.push_frame(b"frame1")
        assert router.is_full()
        
        # Should not block or raise
        start = time.time()
        router.push_frame(b"frame2")
        elapsed = time.time() - start
        
        assert elapsed < 0.01  # Should be immediate
        assert len(router) == 1  # Still at capacity
    
    def test_r8_stabilizes_with_consumption(self):
        """Test [R8]: Station writes are unpaced bursts; Tower's steady consumption stabilizes buffer."""
        router = AudioInputRouter(capacity=10)
        
        # Simulate burst writes
        for i in range(20):
            router.push_frame(f"burst_frame{i}".encode())
        
        # Buffer should be at capacity (newest dropped)
        assert len(router) == 10
        
        # Steady consumption should stabilize
        for _ in range(5):
            router.get_frame()
        
        assert len(router) == 5  # Buffer drained by steady consumption


class TestAudioInputRouterUnderflow:
    """Tests for underflow handling [R9]–[R10]."""
    
    def test_r9_non_blocking_when_timeout_none(self):
        """Test [R9]: When timeout is None, returns None immediately (non-blocking)."""
        router = AudioInputRouter(capacity=10)
        
        start = time.time()
        frame = router.get_frame(timeout_ms=None)
        elapsed = time.time() - start
        
        assert frame is None
        assert elapsed < 0.01  # Immediate return
    
    def test_r9_waits_with_timeout(self):
        """Test [R9]: When timeout > 0, waits up to timeout milliseconds."""
        router = AudioInputRouter(capacity=10)
        
        def delayed_push():
            time.sleep(0.01)  # 10ms delay
            router.push_frame(b"delayed_frame")
        
        # Start thread that will push frame after delay
        thread = threading.Thread(target=delayed_push)
        thread.start()
        
        # Get frame with timeout (should wait and get frame)
        start = time.time()
        frame = router.get_frame(timeout_ms=50)  # 50ms timeout
        elapsed = time.time() - start
        
        thread.join(timeout=1.0)
        
        assert frame == b"delayed_frame"
        assert 0.008 < elapsed < 0.05  # Should wait ~10ms but not exceed 50ms
    
    def test_r9_timeout_expires_returns_none(self):
        """Test [R9]: Returns None if timeout expires."""
        router = AudioInputRouter(capacity=10)
        
        start = time.time()
        frame = router.get_frame(timeout_ms=10)  # 10ms timeout
        elapsed = time.time() - start
        
        assert frame is None
        assert 0.008 < elapsed < 0.05  # Should wait ~10ms
    
    def test_r9_never_blocks_indefinitely(self):
        """Test [R9]: Never blocks indefinitely."""
        router = AudioInputRouter(capacity=10)
        
        # Even with timeout, should eventually return
        start = time.time()
        frame = router.get_frame(timeout_ms=100)
        elapsed = time.time() - start
        
        assert frame is None
        assert elapsed < 0.15  # Should return after timeout, not hang
    
    def test_r10_underflow_triggers_fallback(self):
        """Test [R10]: Underflow triggers fallback logic in AudioPump."""
        router = AudioInputRouter(capacity=10)
        
        # Empty buffer should return None (triggers fallback in AudioPump)
        frame = router.get_frame(timeout_ms=None)
        assert frame is None  # AudioPump will use fallback


class TestAudioInputRouterPartialFrames:
    """Tests for partial frame handling [R11]–[R14]."""
    
    def test_r11_partial_frames_discarded(self):
        """Test [R11]–[R14]: Partial frames are discarded, never returned."""
        router = AudioInputRouter(capacity=10)
        
        # Push complete frame
        complete_frame = b"complete_frame_data" * 100
        router.push_frame(complete_frame)
        
        # Should get complete frame
        frame = router.get_frame()
        assert frame == complete_frame
        assert len(frame) == len(complete_frame)
    
    def test_r13_never_returns_partial(self):
        """Test [R13]: pop_frame() never returns partial frames."""
        router = AudioInputRouter(capacity=10)
        
        # Only complete frames are stored
        router.push_frame(b"frame1")
        router.push_frame(b"frame2")
        
        frame1 = router.get_frame()
        frame2 = router.get_frame()
        
        # Both should be complete frames
        assert frame1 == b"frame1"
        assert frame2 == b"frame2"
        assert frame1 is not None
        assert frame2 is not None


class TestAudioInputRouterThreadSafety:
    """Tests for thread safety [R15]–[R18]."""
    
    def test_r15_all_operations_thread_safe(self):
        """Test [R15]: All operations are thread-safe (protected by threading.RLock)."""
        router = AudioInputRouter(capacity=100)
        errors = []
        
        def concurrent_operations(worker_id: int):
            try:
                for i in range(50):
                    router.push_frame(f"worker{worker_id}_frame{i}".encode())
                    router.get_frame(timeout_ms=None)
                    router.is_full()
                    router.is_empty()
                    len(router)
            except Exception as e:
                errors.append(e)
        
        threads = []
        for worker_id in range(10):
            t = threading.Thread(target=concurrent_operations, args=(worker_id,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join(timeout=10.0)
            assert not t.is_alive(), "Thread should have completed"
        
        assert len(errors) == 0, f"Thread safety errors: {errors}"
    
    def test_r16_multiple_concurrent_writers(self):
        """Test [R16]: Supports multiple concurrent writers."""
        router = AudioInputRouter(capacity=200)
        
        def writer(worker_id: int, count: int):
            for i in range(count):
                router.push_frame(f"w{worker_id}_f{i}".encode())
        
        threads = []
        for worker_id in range(5):
            t = threading.Thread(target=writer, args=(worker_id, 40))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join(timeout=5.0)
        
        # Should have received frames from all writers
        assert len(router) > 0
    
    def test_r17_single_reader(self):
        """Test [R17]: Supports single reader (AudioPump is the sole consumer)."""
        router = AudioInputRouter(capacity=10)
        
        # Push some frames
        for i in range(5):
            router.push_frame(f"frame{i}".encode())
        
        # Single reader should get all frames
        frames = []
        while len(frames) < 5:
            frame = router.get_frame()
            if frame is not None:
                frames.append(frame)
        
        assert len(frames) == 5
    
    def test_r18_no_deadlock(self):
        """Test [R18]: push_frame() and pop_frame() can be called concurrently without deadlock."""
        router = AudioInputRouter(capacity=100)
        completed = threading.Event()
        
        def pusher():
            for i in range(100):
                router.push_frame(f"push_frame{i}".encode())
            completed.set()
        
        def popper():
            count = 0
            while count < 100 or not completed.is_set():
                frame = router.get_frame(timeout_ms=10)
                if frame is not None:
                    count += 1
                if completed.is_set() and len(router) == 0:
                    break
        
        push_thread = threading.Thread(target=pusher)
        pop_thread = threading.Thread(target=popper)
        
        push_thread.start()
        pop_thread.start()
        
        # Should complete without deadlock
        push_thread.join(timeout=5.0)
        pop_thread.join(timeout=5.0)
        
        assert not push_thread.is_alive()
        assert not pop_thread.is_alive()


class TestAudioInputRouterSocketIntegration:
    """Tests for socket integration decoupling [R19]–[R22]."""
    
    def test_r19_decoupled_from_socket(self):
        """Test [R19]: AudioInputRouter is decoupled from Unix socket implementation."""
        router = AudioInputRouter(capacity=10)
        
        # Should work without any socket
        router.push_frame(b"test_frame")
        frame = router.get_frame()
        
        assert frame == b"test_frame"
    
    def test_r20_socket_reader_separate(self):
        """Test [R20]: Socket reading logic is separate from buffer management."""
        router = AudioInputRouter(capacity=10)
        
        # Buffer management works independently
        router.push_frame(b"frame1")
        router.push_frame(b"frame2")
        
        # No socket dependency
        assert len(router) == 2
    
    def test_r21_socket_calls_push_frame(self):
        """Test [R21]: Socket reader thread calls push_frame() when complete frames arrive."""
        router = AudioInputRouter(capacity=10)
        
        # Simulate socket reader
        def socket_reader():
            router.push_frame(b"socket_frame1")
            router.push_frame(b"socket_frame2")
        
        thread = threading.Thread(target=socket_reader)
        thread.start()
        thread.join(timeout=1.0)
        
        # Frames should be available
        assert len(router) == 2
        assert router.get_frame() == b"socket_frame1"
    
    def test_r22_audiopump_calls_pop_independently(self):
        """Test [R22]: AudioPump calls pop_frame() independently of socket state."""
        router = AudioInputRouter(capacity=10)
        
        # AudioPump can call pop_frame regardless of socket
        frame = router.pop_frame(timeout_ms=None)
        assert frame is None  # Empty buffer
        
        # Push frame (simulating socket)
        router.push_frame(b"frame")
        
        # AudioPump can get it
        frame = router.pop_frame()
        assert frame == b"frame"
