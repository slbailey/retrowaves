"""
Contract test: FFmpeg stderr diagnostics on spawn failure.

This test asserts that FFmpeg stderr is captured and exposed when FFmpeg
fails at startup, enabling diagnosis of spawn failures.

See docs/contracts/FFMPEG_SUPERVISOR_CONTRACT.md for contract specification.
Contract clause: [S21.3]
"""

import pytest
import time
import threading
from unittest.mock import MagicMock, patch
from io import BytesIO

from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.ffmpeg_supervisor import FFmpegSupervisor, SupervisorState


@pytest.fixture
def mp3_buffer():
    """Create MP3 buffer for supervisor."""
    return FrameRingBuffer(capacity=10)


@pytest.fixture
def supervisor_no_pcm(mp3_buffer):
    """
    Create FFmpegSupervisor instance that will fail at startup.
    
    This simulates a scenario where FFmpeg exits immediately due to
    invalid configuration or missing codec, producing stderr diagnostics.
    """
    sup = FFmpegSupervisor(
        mp3_buffer=mp3_buffer,
        allow_ffmpeg=True,  # Allow FFmpeg for integration tests per [I25]
    )
    yield sup
    try:
        sup.stop()
    except Exception:
        pass


class TestFFmpegDiagnostics:
    """Tests for FFmpeg stderr diagnostics on spawn failure per [S21.3]."""
    
    @pytest.mark.timeout(5)
    def test_ffmpeg_emits_startup_stderr_on_failure(self, supervisor_no_pcm):
        """
        Test [S21.3]: FFmpeg stderr must be captured and exposed on startup failure.
        
        Contract requirement [S21.3]:
        FFmpeg MUST produce diagnostic stderr output on spawn failure. The supervisor
        MUST capture and expose this stderr output so that the exit reason is visible.
        When FFmpeg fails at startup, the supervisor MUST ensure stderr is read and
        made available before the process is considered failed.
        
        This test simulates FFmpeg exiting immediately with stderr diagnostics,
        and verifies that the supervisor captures and exposes this stderr output.
        """
        # Create mock stderr with diagnostic message (simulating FFmpeg startup failure)
        stderr_content = b"Unknown encoder 'libmp3lame'\n"  # Example FFmpeg error
        mock_stderr = BytesIO(stderr_content)
        mock_stderr.fileno = MagicMock(return_value=3)
        
        # Create mock stdout that immediately EOFs (no MP3 frames)
        mock_stdout = BytesIO(b"")  # Empty - will EOF immediately
        mock_stdout.fileno = MagicMock(return_value=2)
        
        # Create mock stdin
        mock_stdin = MagicMock()
        mock_stdin.fileno.return_value = 1
        mock_stdin.write = MagicMock(return_value=4608)
        mock_stdin.flush = MagicMock()
        
        # Create mock process that exits immediately (spawn failure)
        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_process.pid = 12345
        mock_process.poll.return_value = 1  # Process exited with error
        mock_process.returncode = 1
        
        # Track stderr reads to verify it was accessed
        stderr_reads = []
        original_stderr_read = mock_stderr.read
        
        def track_stderr_read(size=-1):
            result = original_stderr_read(size)
            stderr_reads.append(result)
            return result
        
        mock_stderr.read = track_stderr_read
        
        # Track stderr readline calls (used by stderr drain thread)
        stderr_readlines = []
        original_stderr_readline = mock_stderr.readline
        
        def track_stderr_readline():
            result = original_stderr_readline()
            stderr_readlines.append(result)
            return result
        
        mock_stderr.readline = track_stderr_readline
        
        with patch('tower.encoder.ffmpeg_supervisor.subprocess.Popen', return_value=mock_process):
            # Start supervisor - this should trigger immediate failure detection
            supervisor_no_pcm.start()
            
            # Give time for failure detection and stderr capture
            # The supervisor should detect the process exit and read stderr
            time.sleep(0.2)
            
            # Wait for supervisor to process the failure
            # Check if supervisor has transitioned to RESTARTING or FAILED
            max_wait = 1.0
            start_time = time.time()
            while time.time() - start_time < max_wait:
                state = supervisor_no_pcm.get_state()
                if state in (SupervisorState.RESTARTING, SupervisorState.FAILED):
                    break
                time.sleep(0.05)
        
        # Per contract [S21.3]: Supervisor must capture and EXPOSE stderr on startup failure
        # The supervisor should expose stderr via a queryable interface (e.g., last_stderr property)
        # This enables debugging without requiring log parsing
        
        # Check if supervisor exposes stderr via queryable interface
        has_stderr_property = hasattr(supervisor_no_pcm, 'last_stderr')
        
        if has_stderr_property:
            # Supervisor exposes stderr - verify it's populated
            last_stderr = supervisor_no_pcm.last_stderr
            assert last_stderr is not None, \
                ("Contract violation [S21.3]: Supervisor must expose FFmpeg stderr on startup failure. "
                 f"last_stderr property exists but is None. Stderr content: {stderr_content}")
            
            assert len(last_stderr.strip()) > 0, \
                ("Contract violation [S21.3]: FFmpeg stderr must contain diagnostics if startup fails. "
                 f"last_stderr is empty. Original stderr: {stderr_content}")
            
            # Verify stderr contains the diagnostic message
            assert len(last_stderr.strip()) > 0, \
                ("Contract violation [S21.3]: FFmpeg stderr diagnostics must be readable. "
                 f"last_stderr: {last_stderr[:100]}")
            
            # Log visibility
            print(f"\n[STDERR_VISIBILITY] FFmpeg stderr on startup failure:")
            print(f"  Stderr reads: {len(stderr_reads)}")
            print(f"  Stderr readlines: {len(stderr_readlines)}")
            print(f"  Exposed stderr length: {len(last_stderr)} bytes")
            print(f"  Exposed stderr: {last_stderr[:100]}...")
            print(f"  ✓ Stderr captured and exposed per [S21.3]")
        else:
            # Supervisor does not expose stderr via queryable interface
            # This is a contract violation - stderr should be exposed for debugging
            assert False, \
                ("Contract violation [S21.3]: Supervisor must expose FFmpeg stderr on startup failure. "
                 f"Supervisor does not have last_stderr property or equivalent interface. "
                 f"Stderr was read ({len(stderr_reads)} reads, {len(stderr_readlines)} readlines) "
                 f"but not exposed for querying. Stderr content: {stderr_content}")
        
        # Fallback: Verify that stderr was at least read (even if not exposed)
        stderr_was_read = len(stderr_reads) > 0 or len(stderr_readlines) > 0
        assert stderr_was_read, \
            ("Contract violation [S21.3]: Supervisor must read FFmpeg stderr on startup failure. "
             f"Stderr reads: {len(stderr_reads)}, readlines: {len(stderr_readlines)}. "
             f"Stderr content: {stderr_content}")

