"""
Contract test: Strict PCM selection priority.

This test validates the PCM selection hierarchy: Station PCM > Grace Silence > Fallback

Per NEW_ENCODER_MANAGER_CONTRACT:
- Source selection priority belongs to EncoderManager (M6, M7, M11)
- PCM buffer → silence (grace period) → fallback (tone/file) rules per M6, M7, M16
- EncoderManager calls fallback_provider.next_frame() when grace period expires (M16)

See docs/contracts/NEW_ENCODER_MANAGER_CONTRACT.md, NEW_FALLBACK_PROVIDER_CONTRACT.md

Contract clauses: M6, M7, M11, M16, M-GRACE
"""

import os
import pytest
import time
from unittest.mock import MagicMock, patch

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
def fallback_provider():
    """Create a mock fallback provider per NEW_FALLBACK_PROVIDER_CONTRACT."""
    mock_fallback = MagicMock()
    mock_fallback.next_frame = MagicMock(return_value=b"\x00" * TOWER_PCM_FRAME_SIZE)
    return mock_fallback


@pytest.fixture
def encoder_manager(buffers, fallback_provider):
    """
    Create EncoderManager instance for testing per NEW_ENCODER_MANAGER_CONTRACT.
    
    IMPORTANT: This fixture does NOT call .start() to avoid spinning up threads.
    The test is a pure unit test of next_frame() selection logic.
    """
    pcm_buffer, mp3_buffer = buffers
    manager = EncoderManager(
        pcm_buffer=pcm_buffer,
        mp3_buffer=mp3_buffer,
        stall_threshold_ms=100,
        backoff_schedule_ms=[10, 20],
        max_restarts=0,
        allow_ffmpeg=True,
    )
    
    # Mock the supervisor to avoid starting real threads/processes
    # Per F7: Supervisor receives PCM via write_pcm()
    mock_supervisor = MagicMock()
    mock_supervisor.write_pcm = MagicMock()
    mock_supervisor.get_state = MagicMock(return_value=SupervisorState.RUNNING)
    manager._supervisor = mock_supervisor
    
    # Set up operational mode to LIVE_INPUT for selection hierarchy to apply
    # Mock _get_operational_mode to return LIVE_INPUT
    manager._get_operational_mode = MagicMock(return_value="LIVE_INPUT")
    
    # Set fallback provider per M16
    manager._fallback_generator = fallback_provider
    
    # Initialize grace period state per M-GRACE
    import time
    manager._fallback_grace_timer_start = None
    
    return manager


class TestPCMSelectionPriority:
    """
    Tests for PCM selection priority per NEW_ENCODER_MANAGER_CONTRACT (M6, M7, M11, M16).
    
    Per contract M11: EncoderManager is the only component responsible for implementing
    grace-period logic and deciding when to output program vs grace-period silence vs fallback.
    
    Per contract F3, F4: Supervisor is source-agnostic and treats all incoming PCM frames
    as equally valid. Supervisor does NOT decide routing.
    
    This test verifies that EncoderManager's next_frame() method implements the selection
    hierarchy correctly WITHOUT starting any threads or processes.
    """
    
    @pytest.mark.timeout(5)
    def test_pcm_selected_above_grace_silence_and_fallback(self, encoder_manager, fallback_provider):
        """
        Contract: M6, M7, M11, M16, M-GRACE
        
        Verifies the PCM selection hierarchy: Station PCM > Grace Silence > Fallback.
        
        Per M6: If pcm_from_upstream is present and valid → EncoderManager MUST return pcm_from_upstream.
        Per M7: If pcm_from_upstream is absent:
          - M7.1: If since <= GRACE_SEC → return canonical silence_frame (GRACE_SILENCE)
          - M7.2: If since > GRACE_SEC → call fallback_provider.next_frame() and return result (FALLBACK)
        Per M16: EncoderManager calls fallback_provider.next_frame() when grace period expires.
        
        NOTE: Selection hierarchy is implemented in EncoderManager.next_frame(), not Supervisor.
        Supervisor is source-agnostic per F3, F4 and forwards frames as provided.
        
        This is a pure unit test - no threads, no processes, no .start() calls.
        """
        pcm_buffer = encoder_manager.pcm_buffer
        mock_supervisor = encoder_manager._supervisor
        
        # Define test frames
        pcm_frame = b"pcm_frame" + b"\x00" * (TOWER_PCM_FRAME_SIZE - len(b"pcm_frame"))
        silence_frame = b"\x00" * TOWER_PCM_FRAME_SIZE
        
        # Set threshold to 1 for testing (so first PCM frame meets threshold)
        encoder_manager._pcm_validity_threshold_frames = 1
        encoder_manager._pcm_consecutive_frames = 0
        encoder_manager._pcm_last_frame_time = None
        
        # Set up grace period state per M-GRACE
        encoder_manager._fallback_grace_timer_start = None
        
        # Clear supervisor write history
        mock_supervisor.write_pcm.reset_mock()
        fallback_provider.next_frame.reset_mock()
        
        # Test 1: Station PCM available → must be selected (highest priority per M6)
        pcm_buffer.push_frame(pcm_frame)
        encoder_manager.next_frame(pcm_buffer)
        
        # Verify supervisor.write_pcm() was called with Station PCM per F7
        assert mock_supervisor.write_pcm.called, \
            ("Contract violation [M6, F7]: EncoderManager must forward frames to supervisor. "
             "supervisor.write_pcm() was not called.")
        
        # Get the frame that was written
        written_frame = mock_supervisor.write_pcm.call_args[0][0]
        assert written_frame == pcm_frame, \
            ("Contract violation [M6]: Station PCM must have highest priority. "
             f"Expected Station PCM frame when available, got {written_frame[:20]}")
        
        # Verify fallback_provider was NOT called when PCM is available (per M6)
        assert not fallback_provider.next_frame.called, \
            ("Contract violation [M6]: When Station PCM is available, "
             "fallback_provider.next_frame() should NOT be called.")
        
        # Test 2: No Station PCM → grace silence must be used first (per M7.1, M-GRACE)
        # Empty PCM buffer (no Station PCM available)
        while True:
            frame = pcm_buffer.pop_frame(timeout=0)
            if frame is None:
                break  # Buffer is empty
        
        # Reset counters since we're testing fallback selection
        encoder_manager._pcm_consecutive_frames = 0
        encoder_manager._pcm_last_frame_time = None
        
        # Set grace period to active (within grace period)
        encoder_manager._fallback_grace_timer_start = time.monotonic()
        
        # Clear previous call
        mock_supervisor.write_pcm.reset_mock()
        fallback_provider.next_frame.reset_mock()
        
        # Call next_frame() - should select grace silence (per M7.1)
        encoder_manager.next_frame(pcm_buffer)
        
        # Verify supervisor.write_pcm() was called (per F7)
        assert mock_supervisor.write_pcm.called, \
            ("Contract violation [M7.1, F7]: When Station PCM unavailable but within grace period, "
             "grace silence must be selected. No frame was forwarded.")
        
        # Get the frame that was written (should be silence, not Station PCM)
        grace_frame = mock_supervisor.write_pcm.call_args[0][0]
        assert grace_frame != pcm_frame, \
            ("Contract violation [M7.1]: When Station PCM unavailable but within grace, "
             "grace silence must be used, not Station PCM")
        
        # Verify it's a valid silence frame (4608 bytes, all zeros)
        assert len(grace_frame) == TOWER_PCM_FRAME_SIZE, \
            ("Contract violation [M-GRACE2]: Grace silence frame must be correct size. "
             f"Expected {TOWER_PCM_FRAME_SIZE}, got {len(grace_frame)}")
        assert grace_frame == silence_frame, \
            ("Contract violation [M-GRACE2]: Grace silence frame must be precomputed silence. "
             f"Expected all zeros, got {grace_frame[:20]}")
        
        # Verify fallback_provider was NOT called during grace period (per M7.1)
        assert not fallback_provider.next_frame.called, \
            ("Contract violation [M7.1]: During grace period, fallback_provider.next_frame() "
             "should NOT be called. Grace silence should be used instead.")
        
        # Test 3: No Station PCM and grace period expired → fallback must be used (per M7.2, M16)
        # Set grace period to expired (beyond GRACE_SEC)
        import os
        grace_sec = float(os.getenv("TOWER_PCM_GRACE_SEC", "5.0"))
        encoder_manager._fallback_grace_timer_start = time.monotonic() - (grace_sec + 1.0)
        
        # Clear previous call
        mock_supervisor.write_pcm.reset_mock()
        fallback_provider.next_frame.reset_mock()
        
        # Call next_frame() - should call fallback_provider.next_frame() (per M7.2, M16)
        encoder_manager.next_frame(pcm_buffer)
        
        # Verify fallback_provider.next_frame() was called (per M16.1)
        assert fallback_provider.next_frame.called, \
            ("Contract violation [M7.2, M16.1]: When Station PCM unavailable and grace expired, "
             "fallback_provider.next_frame() must be called.")
        
        # Verify supervisor.write_pcm() was called with fallback frame (per F7)
        assert mock_supervisor.write_pcm.called, \
            ("Contract violation [M7.2, F7]: When fallback is selected, "
             "supervisor.write_pcm() must be called with fallback frame.")
        
        # Get the frame that was written (should be fallback, not Station PCM or grace silence)
        fallback_frame = mock_supervisor.write_pcm.call_args[0][0]
        assert fallback_frame != pcm_frame, \
            ("Contract violation [M7.2]: When Station PCM unavailable and grace expired, "
             "fallback must be used, not Station PCM")
        
        # Verify it's a valid frame (4608 bytes)
        assert len(fallback_frame) == TOWER_PCM_FRAME_SIZE, \
            ("Contract violation [FP2.1]: Fallback frame must be correct size. "
             f"Expected {TOWER_PCM_FRAME_SIZE}, got {len(fallback_frame)}")
        
        # Log visibility
        print(f"\n[PCM_SELECTION_PRIORITY_VISIBILITY] PCM selection hierarchy tested:")
        print(f"  ✓ Selection happens in EncoderManager per [M11], [F3], [F4]")
        print(f"  ✓ Station PCM has priority over grace silence per [M6]")
        print(f"  ✓ Grace silence used before fallback per [M7.1], [M-GRACE]")
        print(f"  ✓ Fallback provider called after grace expires per [M7.2], [M16]")
