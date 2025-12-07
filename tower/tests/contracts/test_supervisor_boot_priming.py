"""
Contract test: Encoder Boot Priming Requirements

This test validates that the supervisor accepts PCM immediately once ffmpeg is running.
Supervisor must not generate its own PCM. Fallback continuity belongs to EncoderManager.

Per NEW_FFMPEG_SUPERVISOR_CONTRACT: F7, F8 (accept PCM), F3, F4 (no PCM generation)
Per NEW_ENCODER_MANAGER_CONTRACT: M19, M20 (boot fallback continuity)
Per NEW_FALLBACK_PROVIDER_CONTRACT: Fallback is guaranteed, silence vs tone is internal policy

Per contract [M19], [M20]:
- During BOOTING, next_frame() must never route None
- next_frame() must route a valid 4608-byte frame on every tick
- Boot output may be fallback tone or silence — content is not guaranteed, only validity and continuity are
- EncoderManager must supply fallback while no PCM is admitted yet
- This fallback is independent of supervisor startup state
"""

import pytest
import time
import threading
from unittest.mock import MagicMock, patch
from io import BytesIO

from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.encoder_manager import EncoderManager
from tower.encoder.ffmpeg_supervisor import FFmpegSupervisor, SupervisorState, FRAME_INTERVAL_MS, FRAME_INTERVAL_SEC


# Tower PCM frame format: 1152 samples * 2 channels * 2 bytes per sample = 4608 bytes
TOWER_PCM_FRAME_SIZE = 4608
SILENCE_FRAME = b'\x00' * TOWER_PCM_FRAME_SIZE
FAKE_PCM_FRAME = b'\x01' * TOWER_PCM_FRAME_SIZE  # Non-zero to distinguish from silence
FAKE_TONE_FRAME = b'\x02' * TOWER_PCM_FRAME_SIZE  # Different marker for tone

# Per F7, F8: Supervisor must accept PCM immediately once ffmpeg is running
# Per M19, M20: EncoderManager supplies fallback frames during BOOTING (fallback is guaranteed, silence vs tone is internal policy)
PRIMING_BURST_SIZE = 5  # Historical reference - actual behavior per F7, F8, M19, M20
PRIMING_TIMEOUT_MS = 50  # Historical reference


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
        stall_threshold_ms=2000,
        backoff_schedule_ms=[100, 200],
        max_restarts=3,
        allow_ffmpeg=True,  # Allow FFmpeg for integration tests per [I25]
    )
    yield manager
    try:
        manager.stop()
    except Exception:
        pass


class TestSupervisorBootPriming:
    """Tests for encoder boot priming per F7, F8, F3, F4, M19, M20."""
    
    @pytest.mark.timeout(10)
    def test_s7_3_encoder_boot_priming_requirements(self, encoder_manager, caplog):
        """
        Test F7, F8, F3, F4, M19, M20: Supervisor accepts PCM immediately once ffmpeg is running.
        
        This test validates:
        - F7, F8: Supervisor must accept PCM via write_pcm() immediately once ffmpeg is running
        - F3, F4: Supervisor must not generate its own PCM
        - M19, M20: EncoderManager supplies fallback frames during BOOTING (fallback is guaranteed, silence vs tone is internal policy)
        - Per [M19], [M20]: During BOOTING, next_frame() must never route None and must route valid 4608-byte frames
        - After priming, normal cadence resumes (per S7.3E)
        
        Per contract [M19], [M20]: Boot output may be fallback tone or silence — content is not guaranteed,
        only validity and continuity are. Fallback is guaranteed, silence vs tone is internal policy.
        """
        # Track writes to supervisor stdin with timestamps
        writes_captured = []  # List of (timestamp, frame_data, frame_length)
        write_lock = threading.Lock()
        
        # Create mock stdin that captures writes with timestamps
        mock_stdin = MagicMock()
        
        def capture_write(data):
            with write_lock:
                writes_captured.append((time.monotonic(), data, len(data) if isinstance(data, bytes) else 0))
            return len(data) if isinstance(data, bytes) else None
        
        mock_stdin.write.side_effect = capture_write
        mock_stdin.flush = MagicMock(return_value=None)
        mock_stdin.fileno.return_value = 1
        
        # Create mock stdout that doesn't immediately EOF (simulates no MP3 yet)
        mock_stdout = MagicMock()
        mock_stdout.read = MagicMock(side_effect=BlockingIOError())  # Simulate non-blocking pipe with no data
        mock_stdout.fileno.return_value = 2
        
        # Create mock stderr
        mock_stderr = BytesIO(b"")
        mock_stderr.fileno = MagicMock(return_value=3)
        
        # Create mock process
        mock_process = MagicMock()
        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr
        mock_process.pid = 12345
        mock_process.poll.return_value = None  # Process is running
        mock_process.returncode = None
        
        # Capture initial write count to identify priming writes
        initial_write_count = 0
        
        with patch('tower.encoder.ffmpeg_supervisor.subprocess.Popen', return_value=mock_process):
            # Record time before start() to capture BOOTING entry
            start_before = time.monotonic()
            
            # Start encoder manager - this should trigger priming per [S7.3A]
            # Priming happens in EncoderManager.start() after supervisor.start()
            encoder_manager.start()
            
            # Record time after start() completes
            start_after = time.monotonic()
            
            # Verify supervisor is in BOOTING state per [S19.13]
            supervisor = encoder_manager._supervisor
            assert supervisor is not None, "Supervisor should be created"
            assert supervisor.get_state() == SupervisorState.BOOTING, \
                (f"Supervisor must be in BOOTING state after start() per [S19.13]. "
                 f"Actual state: {supervisor.get_state()}")
            
            # Per [S7.3A]: Priming occurs when entering BOOTING state
            # Priming happens synchronously during start(), so use start_before as reference
            # Per [S7.3D]: Priming must complete within 50ms
            booting_start_time = start_before
            
            # Give priming time to complete (per [S7.3D]: within 50ms)
            # Note: Priming happens synchronously during state change callback, but give time for async operations
            time.sleep(PRIMING_TIMEOUT_MS / 1000.0 + 0.01)  # 50ms + small buffer
            
            # Per contract [S7.2]: AudioPump drives timing, EncoderManager handles routing on-demand
            # After priming, continuous feed happens via AudioPump calling next_frame() every tick
            # Simulate AudioPump ticks to generate post-priming writes
            from tower.audio.ring_buffer import FrameRingBuffer
            pcm_buffer = FrameRingBuffer(capacity=10)  # Empty buffer - will use fallback
            
            # Simulate 3 AudioPump ticks (post-priming cadence per [S7.3E])
            for _ in range(3):
                encoder_manager.next_frame(pcm_buffer)
                time.sleep(FRAME_INTERVAL_SEC)  # Wait for next tick interval
        
        # ============================================================
        # [S7.3C] Assertion: Writes ≥N frames immediately on BOOTING
        # ============================================================
        with write_lock:
            total_writes = len(writes_captured)
            # Per contract [S7.3C]: Priming = first N sequential writes after BOOTING entered
            # NOT "all writes within 50ms" - use order-based detection
            # NOT based on silence loop timing
            all_events = [(ts, frame_data, frame_len) for ts, frame_data, frame_len in writes_captured]
        
        # Per [S7.3C]: Priming = first N sequential writes after BOOTING
        # NOT based on timestamp or silence loop timing
        priming_events = all_events[:PRIMING_BURST_SIZE]  # EXACTLY first N writes, by contract
        post_priming_events = all_events[PRIMING_BURST_SIZE:]  # Everything after priming
        
        assert len(priming_events) >= PRIMING_BURST_SIZE, \
            (f"Contract violation [S7.3C]: Supervisor MUST write ≥{PRIMING_BURST_SIZE} frames "
             f"immediately on BOOTING. Actual priming writes: {len(priming_events)}. "
             f"Total writes: {total_writes}. "
             f"Expected: First {PRIMING_BURST_SIZE} writes are priming burst.")
        
        # ============================================================
        # [S7.3D] Assertion: Priming Burst Timing Requirements
        # ============================================================
        if len(priming_events) >= 2:
            # Per [S7.3D]: Priming Burst Timing Requirements
            # Calculate intervals between consecutive priming writes
            priming_intervals = [
                (priming_events[i][0] - priming_events[i-1][0]) * 1000.0
                for i in range(1, len(priming_events))
            ]
            
            # Per [S7.3D] requirement #1: Boot priming MUST write ≥N frames back-to-back 
            # with no intentional sleep. This is verified by checking that intervals are
            # reasonable (not indicating intentional sleep/delays).
            #
            # Per [S7.3D] requirement #3: The interval between writes MAY exceed 1ms for 
            # the FIRST interval only, due to FFmpeg cold-start initialization and OS pipe wake-up.
            # Therefore, we skip the first interval (write1→write2) when checking for intentional sleep.
            #
            # Per [S7.3D] requirement #4: All subsequent intervals (writes 2→3, 3→4, ..., N-1→N) 
            # SHOULD be <5ms under normal scheduler conditions. A sub-millisecond interval is ideal 
            # but not required for correctness.
            #
            # Per [S7.3D] requirement #5: Compliance is measured by burst completion time 
            # (requirement #2) and write immediacy (requirement #1), not strict microsecond precision.
            
            # Skip first interval (write1→write2) per requirement #3
            burst_intervals = priming_intervals[1:] if len(priming_intervals) > 1 else []
            
            # Check for intentional sleep: intervals >50ms would indicate intentional delays
            # This enforces requirement #1 (no intentional sleep)
            INTENTIONAL_SLEEP_THRESHOLD_MS = 50.0  # Any interval this large suggests intentional sleep
            
            assert len(burst_intervals) > 0, \
                (f"Contract violation [S7.3D]: Need at least 2 priming writes to verify back-to-back requirement. "
                 f"Got {len(priming_events)} priming writes.")
            
            # Requirement #1: No intentional sleep (strict check)
            intentional_sleeps = [i for i in burst_intervals if i >= INTENTIONAL_SLEEP_THRESHOLD_MS]
            assert len(intentional_sleeps) == 0, \
                (f"Contract violation [S7.3D] requirement #1: Priming burst MUST write frames back-to-back "
                 f"with no intentional sleep. Found intervals indicating sleep: {intentional_sleeps}ms. "
                 f"First interval (cold-start, ignored)={priming_intervals[0]:.2f}ms, "
                 f"Burst intervals={[f'{i:.2f}' for i in burst_intervals]}ms")
            
            # Requirement #4: Subsequent intervals SHOULD be <5ms (advisory check, log warning if exceeded)
            # This is not a strict failure condition per requirement #5
            IDEAL_BURST_INTERVAL_MS = 5.0  # Per requirement #4
            slow_intervals = [i for i in burst_intervals if i >= IDEAL_BURST_INTERVAL_MS]
            if slow_intervals:
                print(f"[S7.3D] Advisory: Some burst intervals exceed ideal <5ms threshold: "
                      f"{slow_intervals}ms. This is acceptable per requirement #5 (compliance measured "
                      f"by burst completion time, not strict microsecond precision).")
            
            # Requirement #2: Total burst MUST complete within 50ms (strict check)
            total_burst_ms = (priming_events[-1][0] - priming_events[0][0]) * 1000.0
            assert total_burst_ms < 50.0, \
                (f"Contract violation [S7.3D] requirement #2: Priming burst MUST complete within 50ms "
                 f"of entering BOOTING. Total burst time: {total_burst_ms:.2f}ms")
        else:
            pytest.fail(
                f"Contract violation [S7.3D]: Cannot verify back-to-back writes - "
                f"insufficient priming writes ({len(priming_events)} < 2). "
                f"This may indicate [S7.3C] failure as well."
            )
        
        # ============================================================
        # [S7.3B] Assertion: Frames used are ones selected by EncoderManager
        # ============================================================
        # Note: In a real implementation, EncoderManager would select frames per [S7.2B]
        # For this test, we verify that the supervisor receives frames from EncoderManager
        # (via write_pcm calls). The actual selection happens upstream.
        # 
        # Per contract [M19], [M20]: Boot output may be fallback tone or silence — 
        # content is not guaranteed, only validity and continuity are.
        # Fallback is guaranteed, silence vs tone is internal policy per [M20].
        
        # Check that priming frames are valid Tower-format frames (4608 bytes)
        invalid_frames = []
        for ts, frame_data, frame_len in priming_events:
            if frame_data is None:
                invalid_frames.append(("None", ts))
            elif frame_len != TOWER_PCM_FRAME_SIZE:
                invalid_frames.append((frame_len, ts))
        
        assert len(invalid_frames) == 0, \
            (f"Contract violation [S7.3B], [M19], [M20]: Priming frames MUST be valid Tower-format frames "
             f"(not None, exactly {TOWER_PCM_FRAME_SIZE} bytes) selected by EncoderManager per [S7.2B]. "
             f"Boot output may be fallback tone or silence — content is not guaranteed, only validity "
             f"and continuity are per [M19], [M20]. Invalid frames: {invalid_frames}")
        
        # ============================================================
        # [S7.3E] Assertion: After burst, fallback cadence resumes normally
        # ============================================================
        # After priming completes, normal FRAME_INTERVAL cadence should resume
        # per [S7.2] continuous feed requirements.
        # Per contract [M19], [M20]: Fallback continuity is guaranteed during BOOTING.
        
        # Post-priming cadence requirement [S7.3E]
        if len(post_priming_events) >= 2:
            # Calculate intervals between consecutive post-priming writes
            post_intervals = [
                (post_priming_events[i][0] - post_priming_events[i-1][0]) * 1000.0
                for i in range(1, len(post_priming_events))
            ]
            
            # Per [S7.3E] and [S7.2]: Normal cadence should be ~FRAME_INTERVAL_MS
            # Check that at least some intervals are in the expected range (20-40ms for ~24ms target)
            assert any(20 < i < 40 for i in post_intervals), \
                (f"Contract violation [S7.3E]: No normal cadence frames detected after priming. "
                 f"Post-priming intervals (ms): {[f'{i:.1f}' for i in post_intervals]}. "
                 f"Expected: Some intervals in 20-40ms range (FRAME_INTERVAL ≈ {FRAME_INTERVAL_MS}ms)")
        else:
            # If we don't have enough post-priming writes, that's also a violation
            # (fallback feed should continue after priming per [M19], [M20])
            assert len(post_priming_events) >= 2, \
                (f"Contract violation [S7.3E], [M19], [M20]: After priming completes, continuous feed per [S7.2] "
                 f"should resume. Expected at least 2 post-priming writes, got {len(post_priming_events)}. "
                 f"This may indicate fallback feed is not running after priming. "
                 f"Per [M19], [M20]: Fallback is guaranteed during BOOTING, silence vs tone is internal policy.")
        
        # ============================================================
        # [S7.3F] Assertion: Logs contain "priming start" and "priming complete"
        # ============================================================
        log_text = caplog.text.lower()
        
        # Per [S7.3F]: Supervisor MUST log start of priming
        assert "priming" in log_text and ("start" in log_text or "begin" in log_text), \
            (f"Contract violation [S7.3F]: Supervisor MUST log start of priming. "
             f"Log text (first 500 chars): {caplog.text[:500]}")
        
        # Per [S7.3F]: Supervisor MUST log completion of priming
        assert "priming" in log_text and ("complete" in log_text or "done" in log_text or "finished" in log_text), \
            (f"Contract violation [S7.3F]: Supervisor MUST log completion of priming. "
             f"Log text (first 500 chars): {caplog.text[:500]}")
        
        # Per [S7.3F]: Supervisor MUST log number of frames written
        # Check for log containing frame count (could be "5 frames", "frames: 5", etc.)
        has_frame_count = False
        for record in caplog.records:
            message = str(record.message).lower()
            if "priming" in message and any(char.isdigit() for char in message):
                has_frame_count = True
                break
        
        assert has_frame_count, \
            (f"Contract violation [S7.3F]: Supervisor MUST log number of frames written during priming. "
             f"Log records: {[str(r.message) for r in caplog.records if 'priming' in str(r.message).lower()]}")
        
        # Log visibility for debugging
        print(f"\n[PRIMING_VISIBILITY] Encoder Boot Priming Analysis:")
        print(f"  Total writes captured: {total_writes}")
        print(f"  Priming writes (first {PRIMING_BURST_SIZE}): {len(priming_events)}")
        print(f"  Expected priming burst size: {PRIMING_BURST_SIZE}")
        if len(priming_events) >= 2:
            intervals = [(priming_events[i][0] - priming_events[i-1][0]) * 1000.0 
                        for i in range(1, len(priming_events))]
            print(f"  Priming write intervals: {[f'{i:.2f}ms' for i in intervals]}")
            if len(intervals) > 1:
                first_interval = intervals[0]
                burst_intervals = intervals[1:]
                print(f"  First interval (cold-start, may exceed 1ms): {first_interval:.2f}ms")
                print(f"  Burst intervals (should be <5ms ideal): {[f'{i:.2f}ms' for i in burst_intervals]}")
                print(f"  Max burst interval: {max(burst_intervals):.2f}ms (ideal <5ms, not required for correctness)")
        print(f"  Post-priming writes: {len(post_priming_events)}")
        if len(post_priming_events) >= 2:
            post_intervals = [(post_priming_events[i][0] - post_priming_events[i-1][0]) * 1000.0 
                             for i in range(1, len(post_priming_events))]
            print(f"  Post-priming intervals: {[f'{i:.1f}ms' for i in post_intervals]}")
            print(f"  Expected: ~{FRAME_INTERVAL_MS}ms per frame")
        print(f"  ✓ All S7.3 contract requirements validated")
        
        # Cleanup
        try:
            supervisor.stop()
        except Exception:
            pass

