"""
Contract test: Drain thread ordering before initial PCM write.

This test asserts that stdout/stderr drain threads MUST be running
before the initial PCM write to prevent FFmpeg deadlock.

Per NEW_FFMPEG_SUPERVISOR_CONTRACT: F7, F8, F9
- F7, F8: Supervisor accepts PCM via write_pcm()
- F9: Drain threads handle stdout/stderr
- Drain threads must start before PCM write to prevent deadlock
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
EXPECTED_SILENCE_FRAME = b'\x00' * TOWER_PCM_FRAME_SIZE


@pytest.fixture
def mp3_buffer():
    """Create MP3 buffer for supervisor."""
    return FrameRingBuffer(capacity=10)


@pytest.fixture
def supervisor(mp3_buffer):
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


class TestDrainThreadOrderingBeforePCMWrite:
    """Tests for drain thread ordering requirement per F7, F8, F9."""
    
    @pytest.mark.timeout(5)
    def test_stdout_stderr_drain_threads_start_before_initial_pcm_write(self, supervisor):
        """
        Test F7, F8, F9: Stdout/stderr drain threads MUST be running before initial PCM write.
        
        Contract requirement F7, F8, F9:
        The supervisor MUST attach stdout/stderr drain threads BEFORE writing initial PCM
        into stdin. Rationale: FFmpeg output buffers can deadlock or close early if no
        reader is attached, causing firmware-level shutdown.
        
        This test exposes the violation where the initial silence frame is written
        before drain threads are started, which can cause FFmpeg to deadlock or exit.
        
        Expected behavior:
        - Process spawned
        - Stdout drain thread started
        - Stderr drain thread started
        - THEN initial silence frame written to stdin
        """
        # Track the order of operations
        operation_order = []
        operation_lock = threading.Lock()
        
        # Create mock stdin that captures writes
        mock_stdin = MagicMock()
        
        def capture_write(data):
            with operation_lock:
                operation_order.append(("pcm_write", data))
            return len(data) if isinstance(data, bytes) else None
        
        mock_stdin.write.side_effect = capture_write
        mock_stdin.flush = MagicMock(return_value=None)
        mock_stdin.fileno.return_value = 1
        
        # Create mock stdout that tracks when drain thread starts
        mock_stdout = MagicMock()
        stdout_thread_started = threading.Event()
        
        def mock_stdout_read(*args, **kwargs):
            # Signal that stdout drain thread is running
            if not stdout_thread_started.is_set():
                with operation_lock:
                    operation_order.append(("stdout_drain_started", None))
                stdout_thread_started.set()
            raise BlockingIOError()  # Simulate non-blocking pipe with no data
        
        mock_stdout.read.side_effect = mock_stdout_read
        mock_stdout.fileno.return_value = 2
        
        # Create mock stderr that tracks when drain thread starts
        stderr_thread_started = threading.Event()
        
        def mock_stderr_readline():
            # Signal that stderr drain thread is running
            if not stderr_thread_started.is_set():
                with operation_lock:
                    operation_order.append(("stderr_drain_started", None))
                stderr_thread_started.set()
            return b''  # EOF - in blocking mode this unblocks the thread
        
        mock_stderr = MagicMock()
        mock_stderr.readline.side_effect = mock_stderr_readline
        mock_stderr.fileno.return_value = 3
        
        # Create mock process
        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_process.pid = 12345
        mock_process.poll.return_value = None  # Process is running
        mock_process.returncode = None
        
        # Set up state change callback to trigger priming (simulating EncoderManager behavior)
        original_callback = supervisor._on_state_change
        def state_change_with_priming(new_state):
            # Call original callback
            if original_callback:
                original_callback(new_state)
            # Simulate EncoderManager priming burst when entering BOOTING
            if new_state == SupervisorState.BOOTING:
                # Write initial PCM frame (simulating priming burst)
                silence_frame = b'\x00' * TOWER_PCM_FRAME_SIZE
                with operation_lock:
                    operation_order.append(("pcm_write", silence_frame))
                supervisor.write_pcm(silence_frame)
        
        supervisor._on_state_change = state_change_with_priming
        
        with patch('tower.encoder.ffmpeg_supervisor.subprocess.Popen', return_value=mock_process):
            # Start supervisor (this will trigger state change to BOOTING, which triggers callback)
            supervisor.start()
        
        # Give threads time to start and callback to execute
        time.sleep(0.2)
        
        # Wait for threads to exit (prevents memory leaks)
        if supervisor._stderr_thread is not None:
            supervisor._stderr_thread.join(timeout=0.1)
        if supervisor._stdout_thread is not None:
            supervisor._stdout_thread.join(timeout=0.1)
        if supervisor._writer_thread is not None:
            supervisor._writer_thread.join(timeout=0.1)
        
        # Verify operation order per contract F7, F8, F9
        # Both drain threads MUST start before PCM write
        with operation_lock:
            operations = list(operation_order)
        
        # Find indices of key operations
        stdout_drain_idx = None
        stderr_drain_idx = None
        pcm_write_idx = None
        
        for i, (op_type, _) in enumerate(operations):
            if op_type == "stdout_drain_started":
                stdout_drain_idx = i
            elif op_type == "stderr_drain_started":
                stderr_drain_idx = i
            elif op_type == "pcm_write":
                pcm_write_idx = i
        
        # Per contract F7, F8, F9: Drain threads MUST start before PCM write
        assert stdout_drain_idx is not None, \
            ("Contract violation F7, F8, F9: Stdout drain thread must start. "
             f"Operation order: {operations}")
        
        assert stderr_drain_idx is not None, \
            ("Contract violation [S19.16]: Stderr drain thread must start. "
             f"Operation order: {operations}")
        
        assert pcm_write_idx is not None, \
            ("Contract violation [S19.16]: Initial PCM write must occur. "
             f"Operation order: {operations}")
        
        # Assert ordering: both drain threads must start BEFORE PCM write
        assert stdout_drain_idx < pcm_write_idx, \
            (f"Contract violation [S19.16]: Stdout drain thread MUST start before initial PCM write. "
             f"Stdout drain started at index {stdout_drain_idx}, PCM write at index {pcm_write_idx}. "
             f"Operation order: {operations}")
        
        assert stderr_drain_idx < pcm_write_idx, \
            (f"Contract violation [S19.16]: Stderr drain thread MUST start before initial PCM write. "
             f"Stderr drain started at index {stderr_drain_idx}, PCM write at index {pcm_write_idx}. "
             f"Operation order: {operations}")
        
        # Verify the written data is the expected silence frame
        pcm_write_data = None
        for op_type, data in operations:
            if op_type == "pcm_write":
                pcm_write_data = data
                break
        
        assert pcm_write_data == EXPECTED_SILENCE_FRAME, \
            (f"Contract violation [S19.16]: Initial PCM write must be silence frame. "
             f"Expected {len(EXPECTED_SILENCE_FRAME)} zero bytes, "
             f"got {len(pcm_write_data) if pcm_write_data else 0} bytes. "
             f"Operation order: {operations}")
        
        # Log the operation order for visibility
        print(f"\n[OPERATION_ORDER_VISIBILITY] Observed operation sequence:")
        for i, (op_type, data) in enumerate(operations):
            if op_type == "pcm_write":
                print(f"  {i}: {op_type} ({len(data) if data else 0} bytes)")
            else:
                print(f"  {i}: {op_type}")
        
        print(f"\n[OPERATION_ORDER_VISIBILITY] Ordering check:")
        print(f"  Stdout drain started: index {stdout_drain_idx}")
        print(f"  Stderr drain started: index {stderr_drain_idx}")
        print(f"  PCM write: index {pcm_write_idx}")
        print(f"  ✓ Both drain threads started before PCM write per F7, F8, F9")

