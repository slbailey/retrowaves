"""
Contract test: Full system boot sustains FFmpeg until RUNNING.

This test verifies that the full Tower system (AudioPump + EncoderManager + Supervisor)
feeds PCM continuously from startup, even before live PCM begins.

Per NEW contracts:
- AudioPump ticks at 24ms intervals (A4)
- EncoderManager.next_frame() returns a valid PCM frame each tick including silence during startup (M-GRACE1-M-GRACE4)
- FFmpegSupervisor receives frames through write_pcm() (F7)
- Supervisor start/stop behavior follows F5-F6 and F-HEAL

See docs/contracts/NEW_FFMPEG_SUPERVISOR_CONTRACT.md, NEW_ENCODER_MANAGER_CONTRACT.md, NEW_AUDIOPUMP_CONTRACT.md
Contract clauses: F5, F6, F7, F-HEAL, M1-M3, M-GRACE, A4, A5
"""

import pytest
import time
import threading
from unittest.mock import MagicMock, patch
from io import BytesIO

from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.encoder_manager import EncoderManager, EncoderState
from tower.encoder.ffmpeg_supervisor import FFmpegSupervisor, SupervisorState
from tower.encoder.audio_pump import AudioPump, FRAME_DURATION_SEC


# Tower PCM frame format: 1152 samples * 2 channels * 2 bytes per sample = 4608 bytes
TOWER_PCM_FRAME_SIZE = 4608
SILENCE_FRAME = b'\x00' * TOWER_PCM_FRAME_SIZE
FRAME_INTERVAL_MS = 24  # Per A4, C1.1


@pytest.fixture
def buffers():
    """Create PCM and MP3 buffers for testing."""
    pcm_buffer = FrameRingBuffer(capacity=10)
    mp3_buffer = FrameRingBuffer(capacity=10)
    return pcm_buffer, mp3_buffer


@pytest.fixture
def fallback_provider():
    """Create a mock fallback provider that returns silence per NEW_FALLBACK_PROVIDER_CONTRACT."""
    mock_fallback = MagicMock()
    mock_fallback.next_frame = MagicMock(return_value=SILENCE_FRAME)
    return mock_fallback


@pytest.fixture
def encoder_manager(buffers, fallback_provider):
    """Create EncoderManager instance for testing per NEW_ENCODER_MANAGER_CONTRACT."""
    pcm_buffer, mp3_buffer = buffers
    manager = EncoderManager(
        pcm_buffer=pcm_buffer,
        mp3_buffer=mp3_buffer,
        stall_threshold_ms=2000,
        backoff_schedule_ms=[100, 200],
        max_restarts=3,
        allow_ffmpeg=True,  # Allow FFmpeg for integration tests
    )
    # Set fallback provider per M16
    manager._fallback_generator = fallback_provider
    yield manager
    try:
        manager.stop()
    except Exception:
        pass


@pytest.fixture
def audio_pump(buffers, fallback_provider, encoder_manager):
    """Create AudioPump instance for testing per NEW_AUDIOPUMP_CONTRACT."""
    pcm_buffer, _ = buffers
    pump = AudioPump(
        pcm_buffer=pcm_buffer,
        fallback_generator=fallback_provider,
        encoder_manager=encoder_manager,
    )
    yield pump
    try:
        pump.stop()
    except Exception:
        pass


class TestFullSystemBootSustainsFFmpeg:
    """Tests for full system boot sustaining FFmpeg per F5, F6, F7, F-HEAL, M-GRACE, A4, A5."""
    
    @pytest.mark.timeout(10)
    def test_full_system_boot_sustains_ffmpeg_until_running(
        self, buffers, encoder_manager, audio_pump
    ):
        """
        Test full system boot: AudioPump + EncoderManager + Supervisor feed PCM continuously.
        
        Per NEW contracts:
        - AudioPump ticks at 24ms intervals (A4)
        - EncoderManager.next_frame() returns valid PCM frame each tick (M1-M3)
        - During startup, EncoderManager outputs silence frames (M-GRACE1-M-GRACE4, M9)
        - FFmpegSupervisor receives frames through write_pcm() (F7)
        - Supervisor starts ffmpeg process (F5) and restarts if needed (F6, F-HEAL)
        
        Expected behavior:
        1. AudioPump starts and calls encoder_manager.next_frame() every 24ms (A4, A5)
        2. EncoderManager.next_frame() returns silence frames during startup grace period (M-GRACE, M9)
        3. EncoderManager routes frames to supervisor.write_pcm() (F7)
        4. Supervisor receives continuous PCM frames at 24ms cadence
        5. If FFmpeg produces first MP3 frame → Supervisor transitions to RUNNING
        6. If MP3 not observed before timeout → Supervisor may restart (F6, F-HEAL)
        7. Process remains alive with continuous PCM feed (F5)
        """
        pcm_buffer, mp3_buffer = buffers
        
        # Track writes to supervisor stdin (via supervisor.write_pcm() per F7)
        frames_written = []
        write_lock = threading.Lock()
        
        # Create mock stdin that captures writes
        mock_stdin = MagicMock()
        
        def capture_write(data):
            with write_lock:
                frames_written.append((time.time(), len(data) if isinstance(data, bytes) else 0))
            return len(data) if isinstance(data, bytes) else None
        
        mock_stdin.write.side_effect = capture_write
        mock_stdin.flush = MagicMock(return_value=None)
        mock_stdin.fileno.return_value = 1
        
        # Create mock stdout that simulates MP3 output after a delay
        # (FFmpeg needs time to encode the first frame)
        # Create a minimal valid MP3 frame: MPEG-1 Layer III, 128kbps, 48kHz, no padding
        # Header: 0xFF 0xFB 0x90 0x00 (sync + MPEG-1 L3 + 128kbps@48kHz)
        # Frame size for 128kbps@48kHz: 144 * 128000 / 48000 = 384 bytes
        mp3_frame_size = 384
        mp3_frame_header = bytes([0xFF, 0xFB, 0x90, 0x00])  # Valid MP3 header
        mp3_frame_data = mp3_frame_header + b'\x00' * (mp3_frame_size - 4)  # Complete frame
        mp3_bytes_sent = 0
        
        def mock_stdout_read(size):
            nonlocal mp3_bytes_sent
            # After ~100ms, start returning MP3 data (simulating first frame)
            if time.time() > (start_time + 0.1):
                if mp3_bytes_sent < len(mp3_frame_data):
                    chunk = mp3_frame_data[mp3_bytes_sent:mp3_bytes_sent + size]
                    mp3_bytes_sent += len(chunk)
                    return chunk
                # After first frame, return empty (simulating no more data yet)
                raise BlockingIOError()
            raise BlockingIOError()  # No data available yet
        
        mock_stdout = MagicMock()
        mock_stdout.read.side_effect = mock_stdout_read
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
        
        start_time = time.time()
        
        with patch('tower.encoder.ffmpeg_supervisor.subprocess.Popen', return_value=mock_process):
            # Start the full system
            encoder_manager.start()
            audio_pump.start()
            
        pcm_buffer, mp3_buffer = buffers
        
        # Wait for system to stabilize
        max_wait = 2.0
        start_wait = time.time()
        while time.time() - start_wait < max_wait:
            supervisor_state = encoder_manager._supervisor.get_state() if encoder_manager._supervisor else None
            if supervisor_state in (SupervisorState.RUNNING, SupervisorState.RESTARTING, SupervisorState.FAILED):
                break
            time.sleep(0.05)
        
        # Give system time to stabilize
        time.sleep(0.2)
        
        # Wait for threads to exit (prevents memory leaks)
        if encoder_manager._supervisor:
            if encoder_manager._supervisor._stderr_thread is not None:
                encoder_manager._supervisor._stderr_thread.join(timeout=0.1)
            if encoder_manager._supervisor._stdout_thread is not None:
                encoder_manager._supervisor._stdout_thread.join(timeout=0.1)
            if encoder_manager._supervisor._writer_thread is not None:
                encoder_manager._supervisor._writer_thread.join(timeout=0.1)
        
        # Per contract A4, A5: Verify AudioPump calls encoder_manager.next_frame() at 24ms intervals
        # Per contract M1-M3: EncoderManager returns valid PCM frame each tick
        # Per contract F7: Supervisor receives frames through write_pcm()
        with write_lock:
            total_writes = len(frames_written)
            
            # Log visibility first
            print(f"\n[FULL_SYSTEM_BOOT_VISIBILITY] System boot analysis:")
            print(f"  Total PCM writes: {total_writes}")
            print(f"  Supervisor state: {supervisor_state}")
            
            assert total_writes > 1, \
                (f"Contract violation [A4, A5, M1-M3, F7]: System must feed PCM continuously from startup. "
                 f"AudioPump should call encoder_manager.next_frame() every 24ms, which routes frames to "
                 f"supervisor.write_pcm(). Only {total_writes} write(s) detected. "
                 f"Expected multiple writes at 24ms cadence.")
            
            # Verify writes occurred at approximately 24ms cadence (per A4, C1.1)
            if len(frames_written) > 1:
                intervals = []
                for i in range(1, len(frames_written)):
                    interval_ms = (frames_written[i][0] - frames_written[i-1][0]) * 1000.0
                    intervals.append(interval_ms)
                
                # Check that intervals are close to 24ms (within tolerance)
                # Per contract A4: AudioPump ticks at 24ms intervals
                avg_interval = sum(intervals) / len(intervals) if intervals else 0
                assert avg_interval <= FRAME_INTERVAL_MS * 2, \
                    (f"Contract violation [A4]: AudioPump must tick at 24ms intervals. "
                     f"Average interval: {avg_interval:.1f}ms (target: {FRAME_INTERVAL_MS}ms). "
                     f"Intervals: {intervals}")
        
        # Per contract F5: Supervisor starts ffmpeg process
        # Per contract F6, F-HEAL: Supervisor may restart if needed
        supervisor_state = encoder_manager._supervisor.get_state() if encoder_manager._supervisor else None
        
        # With continuous PCM feed, supervisor should reach one of:
        # - RUNNING (if MP3 observed)
        # - RESTARTING (if startup timeout exceeded)
        # - FAILED (if max restarts exceeded)
        assert supervisor_state in (SupervisorState.RUNNING, SupervisorState.RESTARTING, SupervisorState.FAILED), \
            (f"Contract violation [F5, F6]: With continuous PCM feed, supervisor should reach RUNNING, "
             f"RESTARTING, or FAILED state. Actual state: {supervisor_state}")
        
        # Verify process is still running (not exited) per F5
        if encoder_manager._supervisor and encoder_manager._supervisor._process:
            poll_result = encoder_manager._supervisor._process.poll()
            assert poll_result is None, \
                (f"Contract violation [F5]: FFmpeg process should remain alive with continuous PCM feed. "
                 f"Process exited with code: {poll_result}")
        
        # Log visibility
        with write_lock:
            print(f"\n[FULL_SYSTEM_BOOT_VISIBILITY] System boot analysis:")
            print(f"  Total PCM writes: {total_writes}")
            print(f"  Supervisor state: {supervisor_state}")
            if len(frames_written) > 1:
                intervals = [(frames_written[i][0] - frames_written[i-1][0]) * 1000.0 
                            for i in range(1, len(frames_written))]
                print(f"  Average interval: {sum(intervals)/len(intervals):.1f}ms (target: {FRAME_INTERVAL_MS}ms)")
                print(f"  Interval range: {min(intervals):.1f}ms - {max(intervals):.1f}ms")
            print(f"  Process running: {poll_result is None if encoder_manager._supervisor and encoder_manager._supervisor._process else 'N/A'}")
            print(f"  ✓ Full system boot sustains FFmpeg per [F5, F6, F7, A4, A5, M-GRACE]")

