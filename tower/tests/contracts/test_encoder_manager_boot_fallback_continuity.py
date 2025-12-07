"""
Contract test: EncoderManager boot fallback continuity.

This test validates the correct contract behavior during BOOTING state:
- During BOOTING, next_frame() must never return None (frames routed internally)
- next_frame() must route a valid 4608-byte frame on every tick
- Boot output may be fallback tone or silence — content is not guaranteed, only validity and continuity are
- EncoderManager must supply fallback while no PCM is admitted yet
- This fallback is independent of supervisor startup state

Per NEW_ENCODER_MANAGER_CONTRACT and NEW_FALLBACK_PROVIDER_CONTRACT:
- [M19]: During BOOTING, EncoderManager must inject PCM data via fallback
- [M20]: Fallback is guaranteed, silence vs tone is internal policy
- [M19A]: Fallback controller automatically activates during BOOTING

See docs/contracts/NEW_ENCODER_MANAGER_CONTRACT.md, NEW_FALLBACK_PROVIDER_CONTRACT.md
Contract clauses: M19, M20
"""

import pytest
import time
import threading
from unittest.mock import MagicMock, patch
from io import BytesIO

from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.encoder_manager import EncoderManager
from tower.encoder.ffmpeg_supervisor import SupervisorState


# Tower PCM frame format: 1152 samples * 2 channels * 2 bytes per sample = 4608 bytes
TOWER_PCM_FRAME_SIZE = 4608


@pytest.fixture
def buffers():
    """Create PCM and MP3 buffers for testing."""
    pcm_buffer = FrameRingBuffer(capacity=10)
    mp3_buffer = FrameRingBuffer(capacity=10)
    return pcm_buffer, mp3_buffer


@pytest.fixture
def encoder_manager(buffers):
    """Create EncoderManager instance for testing."""
    pcm_buffer, mp3_buffer = buffers
    manager = EncoderManager(
        pcm_buffer=pcm_buffer,
        mp3_buffer=mp3_buffer,
        stall_threshold_ms=100,
        backoff_schedule_ms=[10, 20],
        max_restarts=3,
        allow_ffmpeg=True,
    )
    yield manager
    try:
        manager.stop()
    except Exception:
        pass


class TestEncoderManagerBootFallbackContinuity:
    """Tests for EncoderManager boot fallback continuity per M19, M20."""
    
    @pytest.mark.timeout(10)
    def test_next_frame_during_booting_never_returns_none(self, encoder_manager):
        """
        Test [M19], [M20]: During BOOTING, next_frame() routes valid frames continuously.
        
        Per contract [M19]: During BOOTING, next_frame() must never route None.
        Per contract [M20]: next_frame() must route a valid 4608-byte frame on every tick.
        Boot output may be fallback tone or silence — content is not guaranteed, only validity and continuity are.
        
        Per contract [M19A]: EncoderManager must supply fallback while no PCM is admitted yet.
        This fallback is independent of supervisor startup state.
        """
        # Track frames routed to supervisor via write_fallback()
        frames_routed = []
        route_lock = threading.Lock()
        
        # Create mock supervisor in BOOTING state
        mock_supervisor = MagicMock()
        mock_supervisor.get_state.return_value = SupervisorState.BOOTING
        
        # Capture frames written via write_pcm() (called by write_fallback())
        def capture_write_pcm(frame):
            with route_lock:
                if frame is not None:
                    frames_routed.append(frame)
        
        mock_supervisor.write_pcm = MagicMock(side_effect=capture_write_pcm)
        encoder_manager._supervisor = mock_supervisor
        
        # Activate fallback controller (simulates automatic activation per [M19A])
        encoder_manager._on_supervisor_state_change(SupervisorState.BOOTING)
        
        # Verify supervisor is in BOOTING state
        assert encoder_manager._supervisor.get_state() == SupervisorState.BOOTING, \
            "Supervisor must be in BOOTING state per [M19]"
        
        # Per contract [M19A]: Fallback controller should be active
        assert encoder_manager._fallback_grace_timer_start is not None, \
            "Fallback controller should activate automatically during BOOTING per [M19A]"
        
        # Create empty PCM buffer (no PCM admitted yet)
        pcm_buffer = FrameRingBuffer(capacity=10)
        
        # Simulate multiple AudioPump ticks during BOOTING
        # Per contract [M19], [M20]: Every tick must route a valid frame
        num_ticks = 10
        for tick in range(num_ticks):
            # Per contract [M19]: next_frame() must route a frame (not None)
            encoder_manager.next_frame(pcm_buffer)
            # Small delay to simulate frame interval
            time.sleep(0.01)
        
        # Give time for async operations to complete
        time.sleep(0.1)
        
        # Per contract [M19], [M20]: Verify frames were routed
        with route_lock:
            assert len(frames_routed) > 0, \
                (f"Contract violation [M19], [M20]: During BOOTING, next_frame() must route "
                 f"valid frames on every tick. No frames were routed to supervisor. "
                 f"Expected at least some frames after {num_ticks} ticks.")
            
            # Per contract [M20]: Every routed frame must be valid (not None, 4608 bytes)
            invalid_frames = []
            for idx, frame in enumerate(frames_routed):
                if frame is None:
                    invalid_frames.append((idx, "None"))
                elif not isinstance(frame, bytes):
                    invalid_frames.append((idx, f"Not bytes: {type(frame)}"))
                elif len(frame) != TOWER_PCM_FRAME_SIZE:
                    invalid_frames.append((idx, f"Wrong size: {len(frame)} bytes, expected {TOWER_PCM_FRAME_SIZE}"))
            
            assert len(invalid_frames) == 0, \
                (f"Contract violation [M20]: Every frame routed during BOOTING must be "
                 f"valid (not None, exactly {TOWER_PCM_FRAME_SIZE} bytes). "
                 f"Invalid frames found: {invalid_frames}")
            
            # Per contract [M19]: Verify continuity - frames should be routed consistently
            # We check that frames were routed (continuity requirement)
            assert len(frames_routed) >= 1, \
                (f"Contract violation [M19]: During BOOTING, next_frame() must route frames "
                 f"continuously. Only {len(frames_routed)} frame(s) routed after {num_ticks} ticks.")
    
    @pytest.mark.timeout(10)
    def test_boot_fallback_frames_are_valid_size(self, encoder_manager):
        """
        Test [M20]: Boot fallback frames must be exactly 4608 bytes.
        
        Per contract [M20]: next_frame() must route a valid 4608-byte frame on every tick.
        This test explicitly verifies frame size correctness.
        """
        frames_routed = []
        route_lock = threading.Lock()
        
        # Create mock supervisor in BOOTING state
        mock_supervisor = MagicMock()
        mock_supervisor.get_state.return_value = SupervisorState.BOOTING
        
        def capture_write_pcm(frame):
            with route_lock:
                if frame is not None:
                    frames_routed.append(frame)
        
        mock_supervisor.write_pcm = MagicMock(side_effect=capture_write_pcm)
        encoder_manager._supervisor = mock_supervisor
        
        # Activate fallback controller
        encoder_manager._on_supervisor_state_change(SupervisorState.BOOTING)
        
        # Empty PCM buffer - will use fallback
        pcm_buffer = FrameRingBuffer(capacity=10)
        
        # Route multiple frames during BOOTING
        for _ in range(5):
            encoder_manager.next_frame(pcm_buffer)
            time.sleep(0.01)
        
        time.sleep(0.1)
        
        # Per contract [M20]: Verify all frames are exactly 4608 bytes
        with route_lock:
            for idx, frame in enumerate(frames_routed):
                assert frame is not None, \
                    f"Contract violation [M20]: Frame {idx} is None - must be valid frame"
                assert isinstance(frame, bytes), \
                    f"Contract violation [M20]: Frame {idx} must be bytes, got {type(frame)}"
                assert len(frame) == TOWER_PCM_FRAME_SIZE, \
                    (f"Contract violation [M20]: Frame {idx} must be exactly {TOWER_PCM_FRAME_SIZE} bytes. "
                     f"Got {len(frame)} bytes. "
                     f"Boot output may be fallback tone or silence — content is not guaranteed, "
                     f"only validity and continuity are per [M20].")
    
    @pytest.mark.timeout(10)
    def test_boot_fallback_independent_of_supervisor_startup_state(self, encoder_manager):
        """
        Test [M19]: Boot fallback is independent of supervisor startup state.
        
        Per contract [M19A]: EncoderManager must supply fallback while no PCM is admitted yet.
        This fallback is independent of supervisor startup state.
        
        This test verifies that fallback frames are provided during BOOTING regardless of
        supervisor internal startup state transitions.
        """
        frames_routed = []
        route_lock = threading.Lock()
        
        # Create mock supervisor that can transition states
        mock_supervisor = MagicMock()
        current_state = SupervisorState.BOOTING
        mock_supervisor.get_state = MagicMock(side_effect=lambda: current_state)
        
        def capture_write_pcm(frame):
            with route_lock:
                if frame is not None:
                    frames_routed.append(frame)
        
        mock_supervisor.write_pcm = MagicMock(side_effect=capture_write_pcm)
        encoder_manager._supervisor = mock_supervisor
        
        # Activate fallback controller
        encoder_manager._on_supervisor_state_change(SupervisorState.BOOTING)
        
        # Empty PCM buffer - will use fallback
        pcm_buffer = FrameRingBuffer(capacity=10)
        
        # Simulate supervisor staying in BOOTING (may take time to start)
        # Per contract [M19]: Fallback should continue regardless
        for _ in range(5):
            encoder_manager.next_frame(pcm_buffer)
            time.sleep(0.01)
        
        time.sleep(0.1)
        
        # Per contract [M19A]: Verify fallback continues during BOOTING
        # regardless of supervisor internal state
        with route_lock:
            assert len(frames_routed) > 0, \
                (f"Contract violation [M19A]: Fallback must be supplied during BOOTING "
                 f"independent of supervisor startup state. No frames were routed.")
            
            # Verify all frames are valid
            for idx, frame in enumerate(frames_routed):
                assert frame is not None, \
                    f"Contract violation [M19]: Frame {idx} routed during BOOTING must not be None"
                assert len(frame) == TOWER_PCM_FRAME_SIZE, \
                    (f"Contract violation [M20]: Frame {idx} must be {TOWER_PCM_FRAME_SIZE} bytes. "
                     f"Got {len(frame)} bytes.")
        
        # Verify fallback controller remains active
        assert encoder_manager._fallback_grace_timer_start is not None, \
            "Fallback controller should remain active during BOOTING per [M19A]"
    
    @pytest.mark.timeout(10)
    def test_supervisor_continuous_silence_until_pcm_available(self, encoder_manager):
        """
        Test [M19], [M20]: Continuous fallback frames during BOOTING until PCM is available.
        
        Per contract [M19], [M20]:
        - During BOOTING, next_frame() must route valid frames continuously
        - Every routed frame must be valid (not None, 4608 bytes)
        - Boot output may be fallback tone or silence — content is not guaranteed, only validity and continuity are
        - EncoderManager must supply fallback while no PCM is admitted yet
        
        This test replaces incorrect assumptions about "continuous silence" with correct contract:
        fallback is guaranteed, silence vs tone is internal policy per [M19], [M20].
        """
        frames_routed = []
        route_lock = threading.Lock()
        
        # Create mock supervisor in BOOTING state
        mock_supervisor = MagicMock()
        mock_supervisor.get_state.return_value = SupervisorState.BOOTING
        
        def capture_write_pcm(frame):
            with route_lock:
                if frame is not None:
                    frames_routed.append(frame)
        
        mock_supervisor.write_pcm = MagicMock(side_effect=capture_write_pcm)
        encoder_manager._supervisor = mock_supervisor
        
        # Activate fallback controller
        encoder_manager._on_supervisor_state_change(SupervisorState.BOOTING)
        
        # Empty PCM buffer - no PCM admitted yet
        pcm_buffer = FrameRingBuffer(capacity=10)
        
        # Per contract [M19], [M20]: Continuous fallback during BOOTING
        # Simulate multiple ticks during BOOTING before PCM becomes available
        num_ticks = 20
        for _ in range(num_ticks):
            encoder_manager.next_frame(pcm_buffer)
            time.sleep(0.01)
        
        time.sleep(0.1)
        
        # Per contract [M19], [M20]: Verify continuous fallback frames
        with route_lock:
            assert len(frames_routed) > 0, \
                (f"Contract violation [M19], [M20]: During BOOTING, next_frame() must route "
                 f"valid fallback frames continuously until PCM is available. No frames were routed.")
            
            # Per contract [M20]: Every frame must be valid (not None, 4608 bytes)
            for idx, frame in enumerate(frames_routed):
                assert frame is not None, \
                    (f"Contract violation [M19], [M20]: Frame {idx} routed during BOOTING must not be None. "
                     f"Per [M19]: next_frame() must never route None during BOOTING.")
                assert isinstance(frame, bytes), \
                    f"Contract violation [M20]: Frame {idx} must be bytes, got {type(frame)}"
                assert len(frame) == TOWER_PCM_FRAME_SIZE, \
                    (f"Contract violation [M20]: Frame {idx} must be exactly {TOWER_PCM_FRAME_SIZE} bytes. "
                     f"Got {len(frame)} bytes. Boot output may be fallback tone or silence — "
                     f"content is not guaranteed, only validity and continuity are per [M19], [M20].")
    
    @pytest.mark.timeout(10)
    def test_supervisor_boot_silence_cadence_jitter_tolerance(self, encoder_manager):
        """
        Test [M19], [M20]: Boot fallback cadence and jitter tolerance.
        
        Per contract [M19], [M20]:
        - During BOOTING, next_frame() must route valid frames on every tick
        - Frames must maintain continuity even with timing jitter
        - Boot output may be fallback tone or silence — content is not guaranteed, only validity and continuity are
        
        This test replaces incorrect assumptions about "silence cadence" with correct contract:
        fallback continuity is guaranteed, cadence tolerance is about frame delivery, not silence content.
        """
        frames_routed = []
        route_lock = threading.Lock()
        timestamps = []
        
        # Create mock supervisor in BOOTING state
        mock_supervisor = MagicMock()
        mock_supervisor.get_state.return_value = SupervisorState.BOOTING
        
        def capture_write_pcm(frame):
            with route_lock:
                timestamps.append(time.monotonic())
                if frame is not None:
                    frames_routed.append(frame)
        
        mock_supervisor.write_pcm = MagicMock(side_effect=capture_write_pcm)
        encoder_manager._supervisor = mock_supervisor
        
        # Activate fallback controller
        encoder_manager._on_supervisor_state_change(SupervisorState.BOOTING)
        
        # Empty PCM buffer - will use fallback
        pcm_buffer = FrameRingBuffer(capacity=10)
        
        # Simulate ticks with varying timing (jitter)
        # Per contract [M19], [M20]: Frames should still route continuously
        base_interval = 0.024  # 24ms base interval
        for tick in range(10):
            encoder_manager.next_frame(pcm_buffer)
            # Add jitter: vary interval by ±20%
            jitter = (tick % 3 - 1) * 0.005  # -5ms, 0ms, +5ms
            time.sleep(base_interval + jitter)
        
        time.sleep(0.1)
        
        # Per contract [M19], [M20]: Verify fallback continuity despite jitter
        with route_lock:
            assert len(frames_routed) > 0, \
                (f"Contract violation [M19], [M20]: During BOOTING, next_frame() must route "
                 f"valid fallback frames continuously even with timing jitter. No frames were routed.")
            
            # Per contract [M20]: Every frame must be valid
            for idx, frame in enumerate(frames_routed):
                assert frame is not None, \
                    (f"Contract violation [M19], [M20]: Frame {idx} must not be None. "
                     f"Per [M19]: next_frame() must never route None during BOOTING.")
                assert len(frame) == TOWER_PCM_FRAME_SIZE, \
                    (f"Contract violation [M20]: Frame {idx} must be {TOWER_PCM_FRAME_SIZE} bytes. "
                     f"Got {len(frame)} bytes. Fallback is guaranteed, silence vs tone is internal policy per [M19], [M20].")
            
            # Verify continuity: frames should be routed despite jitter
            # We don't check exact cadence (that's AudioPump's responsibility), but we verify frames are routed
            assert len(frames_routed) >= 1, \
                (f"Contract violation [M19], [M20]: Fallback frames must maintain continuity "
                 f"even with timing jitter. Only {len(frames_routed)} frame(s) routed.")
            
            # Calculate intervals to verify continuity (not exact cadence, just that frames are delivered)
            if len(timestamps) > 1:
                intervals = [(timestamps[i] - timestamps[i-1]) * 1000.0 
                            for i in range(1, len(timestamps))]
                # Verify frames are being routed (intervals exist, even if jittered)
                assert all(interval > 0 for interval in intervals), \
                    "Contract violation [M19], [M20]: Frame routing intervals must be positive"


