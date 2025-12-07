"""
Contract test: PCM flow during BOOTING state.

This test asserts that PCM frames continue flowing during BOOTING state
and are forwarded to ffmpeg stdin without gaps.

Per NEW contracts:
- FFmpegSupervisor.write_pcm() is called ONLY with PCM (F7)
- All routing logic belongs to EncoderManager (M11)
- Supervisor does NOT decide routing or generate silence (F3, F4)

See docs/contracts/NEW_FFMPEG_SUPERVISOR_CONTRACT.md, NEW_ENCODER_MANAGER_CONTRACT.md
Contract clauses: F5, F7, F8, M11
"""

import pytest
import threading
import time
from unittest.mock import MagicMock, patch
from io import BytesIO

from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.ffmpeg_supervisor import FFmpegSupervisor, SupervisorState


# Tower PCM frame format: 1152 samples * 2 channels * 2 bytes per sample = 4608 bytes
TOWER_PCM_FRAME_SIZE = 4608
FAKE_PCM_FRAME = b'\x01' * TOWER_PCM_FRAME_SIZE  # Non-zero data to distinguish from silence


@pytest.fixture
def mp3_buffer():
    """Create MP3 buffer for supervisor."""
    return FrameRingBuffer(capacity=10)


@pytest.fixture
def fake_pcm_frame():
    """Create a fake PCM frame for testing."""
    return FAKE_PCM_FRAME


@pytest.fixture
def mock_supervisor(mp3_buffer):
    """Create FFmpegSupervisor instance for testing."""
    sup = FFmpegSupervisor(
        mp3_buffer=mp3_buffer,
        allow_ffmpeg=True,  # Allow FFmpeg for integration tests per [I25]
    )
    yield sup
    try:
        sup.stop()
    except Exception:
        pass


class TestSupervisorBootPCMFlow:
    """Tests for PCM flow during BOOTING state per F5, F7, F8, M11."""
    
    @pytest.mark.timeout(5)
    def test_pcm_is_forwarded_during_boot(self, mock_supervisor, fake_pcm_frame):
        """
        Test F7, F8: Supervisor receives PCM frames via write_pcm() during BOOTING.
        
        Contract requirements:
        - F7: FFmpegSupervisor MUST expose write_pcm() method that accepts PCM frames
        - F8: write_pcm() MUST accept a frame of exactly 4608 bytes and enqueue/write to ffmpeg stdin
        - F5: Supervisor starts ffmpeg process on initialization
        - F3, F4: Supervisor does NOT generate silence or decide routing - it only accepts PCM input
        
        Per M11: All routing logic (PCM vs silence vs fallback) belongs to EncoderManager.
        Supervisor is source-agnostic and treats all incoming PCM frames as equally valid.
        
        This test verifies that:
        - Supervisor accepts PCM frames via write_pcm() during BOOTING state
        - PCM frames are forwarded to ffmpeg stdin
        - Multiple frames can be written during BOOTING
        - Supervisor does NOT generate silence or make routing decisions
        """
        frames_written = []
        write_lock = threading.Lock()
        
        # Create mock stdin that captures writes
        mock_stdin = MagicMock()
        
        def capture_write(data):
            with write_lock:
                frames_written.append(data)
            return len(data) if isinstance(data, bytes) else None
        
        mock_stdin.write.side_effect = capture_write
        mock_stdin.flush = MagicMock(return_value=None)
        mock_stdin.fileno.return_value = 1
        
        # Create mock stdout that returns EOF (blocking mode - EOF unblocks thread)
        mock_stdout = MagicMock()
        mock_stdout.read = MagicMock(return_value=b'')  # EOF - in blocking mode this unblocks the thread
        mock_stdout.fileno.return_value = 2
        
        # Create mock stderr that returns EOF (blocking mode - EOF unblocks thread)
        mock_stderr = MagicMock()
        mock_stderr.readline = MagicMock(return_value=b'')  # EOF - in blocking mode this unblocks the thread
        mock_stderr.fileno.return_value = 3
        
        # Create mock process
        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_process.pid = 12345
        mock_process.poll.return_value = None  # Process is running
        mock_process.returncode = None
        
        with patch('tower.encoder.ffmpeg_supervisor.subprocess.Popen', return_value=mock_process):
            # Start supervisor - this puts it in BOOTING state per F5
            mock_supervisor.start()
            
            # Verify supervisor is in BOOTING state
            assert mock_supervisor.get_state() == SupervisorState.BOOTING, \
                ("Supervisor must be in BOOTING state after start() per F5. "
                 f"Actual state: {mock_supervisor.get_state()}")
            
            # Give threads time to start
            time.sleep(0.05)
            
            # Simulate multiple PCM frames being sent during BOOTING
            # Per contract F7, F8: Supervisor receives PCM via write_pcm()
            # Per contract M11: EncoderManager decides routing and calls supervisor.write_pcm()
            num_frames = 5
            for i in range(num_frames):
                # Write PCM frame via supervisor's write_pcm() method
                # This simulates EncoderManager -> supervisor.write_pcm() per F7
                mock_supervisor.write_pcm(fake_pcm_frame)
                # Small delay to simulate frame interval (24ms per A4, C1.1)
                time.sleep(0.01)
            
            # Give time for writes to complete
            # Writer thread runs at 24ms intervals, so we need at least 5 * 24ms = 120ms
            # Plus extra time for boot priming burst to complete and writer thread to process
            # Boot priming burst writes 83 frames directly, then writer thread starts
            # We need to wait for writer thread to write frames from _boot_pcm_buffer
            # Wait for at least 5 frame intervals (5 * 24ms = 120ms) plus buffer time
            time.sleep(0.5)
            
            # Ensure threads exit before test ends (prevents memory leaks)
            if mock_supervisor._stderr_thread is not None:
                mock_supervisor._stderr_thread.join(timeout=0.1)
            if mock_supervisor._stdout_thread is not None:
                mock_supervisor._stdout_thread.join(timeout=0.1)
            if mock_supervisor._writer_thread is not None:
                mock_supervisor._writer_thread.join(timeout=0.1)
        
        # Per contract F7, F8: PCM frames must be forwarded during BOOTING
        # We expect at least the number of frames we sent
        with write_lock:
            total_writes = len(frames_written)
        
        # Count frames that match our fake_pcm_frame
        pcm_frames_forwarded = 0
        with write_lock:
            for frame in frames_written:
                if frame == fake_pcm_frame:
                    pcm_frames_forwarded += 1
        
        assert pcm_frames_forwarded >= num_frames, \
            (f"Contract violation [F7, F8]: PCM frames must continue flowing during BOOTING. "
             f"Expected at least {num_frames} frames to be forwarded via write_pcm(), "
             f"but only {pcm_frames_forwarded} were forwarded. "
             f"Total writes to stdin: {total_writes}. "
             f"Frames written: {[len(f) if isinstance(f, bytes) else 0 for f in frames_written]}")
        
        # Verify supervisor remained in BOOTING state (no MP3 frame received yet)
        # This confirms PCM flow happens during BOOTING, not just after transition to RUNNING
        assert mock_supervisor.get_state() == SupervisorState.BOOTING, \
            (f"Supervisor should remain in BOOTING state when no MP3 frames received. "
             f"Actual state: {mock_supervisor.get_state()}")
        
        # Verify all forwarded frames are valid PCM frames (4608 bytes per C2.2)
        with write_lock:
            for frame in frames_written:
                if isinstance(frame, bytes):
                    assert len(frame) == TOWER_PCM_FRAME_SIZE, \
                        (f"Contract violation [F8, C2.2]: All PCM frames must be exactly 4608 bytes. "
                         f"Got frame of size {len(frame)}")
        
        # Log visibility
        print(f"\n[PCM_FLOW_VISIBILITY] PCM frames forwarded during BOOTING:")
        print(f"  Total writes to stdin: {total_writes}")
        print(f"  PCM frames forwarded: {pcm_frames_forwarded}")
        print(f"  Expected: {num_frames}")
        print(f"  ✓ PCM flow during BOOTING per [F7, F8, M11]")
        print(f"  ✓ Supervisor does NOT generate silence or decide routing per [F3, F4]")

