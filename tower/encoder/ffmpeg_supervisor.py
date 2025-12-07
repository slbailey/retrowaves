"""
FFmpeg Supervisor for Tower encoding subsystem.

This module provides FFmpegSupervisor, which monitors encoder health and ensures
continuous MP3 output according to the FFMPEG_SUPERVISOR_CONTRACT.

See docs/contracts/FFMPEG_SUPERVISOR_CONTRACT.md for full specification.
"""

from __future__ import annotations

import enum
import logging
import os
import select
import subprocess
import sys
import threading
import time
from typing import BinaryIO, Callable, List, Optional

from tower.audio.ring_buffer import FrameRingBuffer

logger = logging.getLogger(__name__)


class SupervisorState(enum.Enum):
    """Supervisor state enumeration per contract [S19], [S6A]."""
    STARTING = 1
    BOOTING = 2  # Per contract [S6A]: BOOTING state until first MP3 frame received
    RUNNING = 3
    RESTARTING = 4
    FAILED = 5
    STOPPED = 6


# Frame timing constants per contract [S15]
FRAME_SIZE_SAMPLES = 1152
SAMPLE_RATE = 48000
FRAME_INTERVAL_SEC = FRAME_SIZE_SAMPLES / SAMPLE_RATE  # 0.024s
FRAME_INTERVAL_MS = FRAME_INTERVAL_SEC * 1000.0  # 24ms

# Frame size constant (4608 bytes: 1152 samples × 2 channels × 2 bytes)
FRAME_BYTES = 4608

# NOTE:
# FRAME_BYTES is the *only* valid Tower PCM frame size.
# Anything else is considered malformed and must be dropped at the edge.

# Removed boot priming constants per residue sweep.
# Per contract [S7.0B], [A7], [M12]: EncoderManager provides continuous PCM via AudioPump.
# Supervisor does not generate or inject PCM - it only writes what it receives.

# Per contract [S7.4]: PCM cadence is driven by AudioPump/EncoderManager, not Supervisor.
# Per contract [S22A]/[M25]: Supervisor is source-agnostic and never generates PCM frames
# (silence, tone, or live). All Tower-format 4608-byte PCM frames must be supplied upstream.

# Startup timeout per contract [S7], [S7A]
# Soft target: 500ms (WARN only, not restart condition) per [S7]
SOFT_STARTUP_TARGET_MS = 500
SOFT_STARTUP_TARGET_SEC = SOFT_STARTUP_TARGET_MS / 1000.0

# Hard timeout: configurable via TOWER_FFMPEG_STARTUP_TIMEOUT_MS, default 1500ms per [S7A]
def _get_startup_timeout_ms() -> int:
    """Get startup timeout from environment or use default per contract [S7A]."""
    return int(os.getenv("TOWER_FFMPEG_STARTUP_TIMEOUT_MS", "1500"))

STARTUP_TIMEOUT_MS = _get_startup_timeout_ms()
STARTUP_TIMEOUT_SEC = STARTUP_TIMEOUT_MS / 1000.0

# Default FFmpeg command for PCM to MP3 encoding (live-mode)
# Per contract [S19.11]: Must include -frame_size 1152 to force MP3 packetization
# at correct Tower frame boundaries and guarantee first-frame emission within startup timeout
DEFAULT_FFMPEG_CMD = [
    "ffmpeg",
    "-hide_banner",
    "-nostdin",
    "-loglevel", "warning",
    "-f", "s16le",
    "-ar", "48000",
    "-ac", "2",
    "-i", "pipe:0",
    "-c:a", "libmp3lame",
    "-b:a", "128k",
    "-frame_size", "1152",  # Per contract [S19.11]: Required for raw PCM encoding
    "-f", "mp3",
    "-fflags", "+nobuffer",
    "-flush_packets", "1",
    "-write_xing", "0",
    "pipe:1",
]


class FFmpegSupervisor:
    """
    FFmpeg encoder supervisor implementing FFMPEG_SUPERVISOR_CONTRACT.
    
    Monitors encoder health, detects failures, and manages restarts with
    exponential backoff. Ensures continuous MP3 output regardless of encoder
    health issues.
    
    Per contract [S22A]: Supervisor MUST NOT know about noise/silence generation.
    It is source-agnostic and treats all valid Tower-format PCM frames identically.
    PCM source selection (silence, tone, or live) is handled by AudioPump/EncoderManager.
    
    Contract compliance:
    - [S1] Encoder is "live" only when all liveness criteria are met
    - [S2] Restarts encoder on any liveness failure with error logging
    - [S3] Never blocks output path (MP3 frame delivery)
    - [S4] Preserves MP3 buffer contents during restarts
    - [S7.1] Receives PCM frames via write_pcm(), does not generate or inject PCM
    - [S22A] Source-agnostic: does not distinguish between silence, tone, or live PCM
    """
    
    def __init__(
        self,
        mp3_buffer: FrameRingBuffer,
        ffmpeg_cmd: Optional[List[str]] = None,
        stall_threshold_ms: int = 2000,
        backoff_schedule_ms: Optional[List[int]] = None,
        max_restarts: int = 5,
        on_state_change: Optional[Callable[[SupervisorState], None]] = None,
        allow_ffmpeg: bool = False,
        encoder_manager: Optional[object] = None,
    ) -> None:
        """
        Initialize FFmpeg supervisor.
        
        Args:
            mp3_buffer: FrameRingBuffer for MP3 output frames (preserved during restarts)
            ffmpeg_cmd: Optional FFmpeg command to execute (default: DEFAULT_FFMPEG_CMD)
            stall_threshold_ms: Stall detection threshold (default: 2000ms per [S11])
            backoff_schedule_ms: Exponential backoff delays (default: [1000,2000,4000,8000,10000])
            max_restarts: Maximum restart attempts before FAILED state (default: 5 per [S13.5])
            on_state_change: Optional callback when state changes
            allow_ffmpeg: Whether FFmpeg startup is allowed (default: False for test safety per [I25])
            encoder_manager: Optional EncoderManager instance for boot priming (default: None)
        """
        self._allow_ffmpeg = allow_ffmpeg
        self._mp3_buffer = mp3_buffer
        self._encoder_manager = encoder_manager
        # Use default command if not provided, ensuring -frame_size 1152 is present per [S19.11]
        self._ffmpeg_cmd = ffmpeg_cmd if ffmpeg_cmd is not None else DEFAULT_FFMPEG_CMD.copy()
        self._stall_threshold_ms = stall_threshold_ms
        self._backoff_schedule_ms = backoff_schedule_ms or [1000, 2000, 4000, 8000, 10000]
        self._max_restarts = max_restarts
        self._on_state_change = on_state_change
        
        # State management per contract [S13.2]
        self._state = SupervisorState.STOPPED
        self._state_lock = threading.Lock()
        self._restart_attempts = 0
        
        # Process management
        self._process: Optional[subprocess.Popen] = None
        self._stdin: Optional[BinaryIO] = None
        self._stdout: Optional[BinaryIO] = None
        self._stderr: Optional[BinaryIO] = None
        
        # Threads per contract [S14]
        self._stderr_thread: Optional[threading.Thread] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._restart_thread: Optional[threading.Thread] = None
        # Removed _writer_thread - per contract [A7], timing is driven by AudioPump, not Supervisor
        
        # Per contract [S7.4]: PCM cadence is driven by AudioPump, not Supervisor
        # Supervisor only writes what it receives via write_pcm()
        self._last_write_ts: Optional[float] = None
        self._write_lock = threading.Lock()  # Protects _last_write_ts (used for telemetry)
        
        # Shutdown event
        self._shutdown_event = threading.Event()
        
        # Removed _stop_event - no longer needed without writer thread per residue sweep
        
        # Per contract [S31] #3: Restart logic disable flag
        self._restart_disabled = False
        
        # Liveness tracking per contract [S7], [S8], [S17]
        # Per contract [S7.1E]: RUNNING requires first MP3 bytes observed from stdout
        # Per contract F9.1: FFmpeg handles MP3 packetization, no packetizer needed
        self._first_frame_received = False  # Also serves as _mp3_seen_yet flag
        self._first_frame_seen = False  # Flag to mark first frame seen per Fix #1
        self._first_frame_time: Optional[float] = None
        self._last_frame_time: Optional[float] = None
        self._startup_time: Optional[float] = None
        
        # Startup timeout monitoring per contract [S7], [S7A]
        self._startup_timeout_thread: Optional[threading.Thread] = None
        self._startup_timeout_cancelled = threading.Event()  # Event to cancel startup timeout
        self._slow_startup_warn_logged = False  # Track if 500ms WARN has been logged per [S7]
        
        # Debug mode per contract [S25]
        self._debug_mode = os.getenv("TOWER_ENCODER_DEBUG", "0") == "1"
        
        # NOTE: We only use _startup_complete to protect the *initial* start()
        # semantics per [S19.13]/[S19.14]. Restarts do not reuse this flag.
        self._startup_complete = False
        
        # Per contract [S19.14]: Pending failures counter for deferring failures during STARTING
        self._pending_failures = 0
        self._pending_failure_details: Optional[tuple] = None  # (failure_type, kwargs)
        self._pending_failure_lock = threading.Lock()
        
        # Telemetry flags for first byte tracking
        self._debug_first_stdin_logged = False
        self._debug_first_stdout_logged = False
        
        # Per contract [S21.3]: Stderr capture for diagnostics
        # Limit size to prevent memory leaks (keep last 10KB)
        self._last_stderr = ""
        self._last_stderr_max_size = 10 * 1024  # 10KB limit
        
        # Per contract F9: MP3 frame boundary detection and accumulation
        # MP3 frame size for 128kbps @ 48kHz: (144 * bitrate_bps) / sample_rate = (144 * 128000) / 48000 = 384 bytes
        # Note: Actual MP3 frames can vary by 1 byte due to padding bit, so we use dynamic detection
        self._stdout_accumulator = bytearray()
        # Limit size to prevent memory leaks (max 1MB - should be enough for several frames)
        self._stdout_accumulator_max_size = 1024 * 1024  # 1MB limit
        # Compute frame size from bitrate and sample rate
        # Extract from ffmpeg command or use default Tower values
        self._mp3_bitrate_kbps = 128  # Default Tower bitrate
        self._mp3_sample_rate = 48000  # Default Tower sample rate
        # Compute base frame size: (144 * bitrate_bps) / sample_rate
        self._mp3_base_frame_size = int((144 * self._mp3_bitrate_kbps * 1000) / self._mp3_sample_rate)
        
        # Per contract [A7], [C7.1]: AudioPump is the single timing authority.
        # Per contract [M12]: EncoderManager handles all routing decisions.
        # Supervisor does NOT buffer or pace PCM - it writes immediately when received.
        # Removed PCM buffers and timing loop per residue sweep.
    
    def start(self) -> None:
        """
        Start supervisor and encoder process per contract [S19].
        
        Follows exact startup sequence:
        1. Create FFmpeg subprocess
        2. Log process PID
        3. Transition to BOOTING state per [S6A]
        4. Start stderr drain thread immediately
        5. Start stdout drain thread
        7. Start timer for first-frame detection (timeout: TOWER_FFMPEG_STARTUP_TIMEOUT_MS, default 1500ms per [S7A])
        8. Monitor for first MP3 frame arrival
        9. If no frame arrives by 500ms → log LEVEL=WARN "slow startup" per [S7] (not a restart condition)
        10. If first frame arrives within hard timeout → transition to RUNNING state per [S6A]
        11. If timeout exceeds hard timeout per [S7A] → log error, restart encoder per [S13]
        
        Note: Per contract [M25], all PCM generation MUST go through AudioPump.
        Supervisor does NOT write initial silence frames. The first PCM frame is provided
        by AudioPump via EncoderManager.next_frame() -> write_pcm() -> supervisor.write_pcm().
        
        Per contract [S19.13]: start() MUST always return with state == BOOTING,
        even if the process exits immediately. Failure handling happens after start() returns.
        """
        with self._state_lock:
            if self._state != SupervisorState.STOPPED:
                raise RuntimeError(f"Cannot start supervisor in state: {self._state}")
            self._state = SupervisorState.STARTING
        
        # Notify state change outside lock
        if self._on_state_change:
            self._on_state_change(SupervisorState.STARTING)
        
        # Step 1-3: Start encoder process FIRST (before setting BOOTING state)
        self._start_encoder_process()
        
        if self._process is None:
            logger.error("Failed to start encoder process")
            self._set_state(SupervisorState.FAILED)
            return
        
        # Per contract [S19.16]: Drain threads MUST start BEFORE first PCM write (boot priming)
        # Step 5: Start stdout drain thread
        # Per contract [S14.7]: stdout drain thread MUST start before or concurrently with stderr drain.
        # Stopping either thread MUST NOT block process termination.
        # Per contract F9.1: FFmpeg handles MP3 packetization, no packetizer needed
        if self._stdout is not None:
            self._stdout_thread = threading.Thread(
                target=self._stdout_drain,
                daemon=True,  # Per contract [S14.7]: Non-blocking termination
                name="FFmpegStdoutDrain"
            )
            self._stdout_thread.start()
            logger.info("Encoder stdout drain thread started")
        
        # Step 4: Start stderr drain thread IMMEDIATELY per contract [S14.1]
        # Per contract [S14.7]: stdout starts before stderr (or concurrently)
        if self._stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._stderr_drain,
                daemon=True,  # Per contract [S14.4], [S14.7]: Non-blocking termination
                name="FFmpegStderrDrain"
            )
            self._stderr_thread.start()
            logger.info("Encoder stderr drain thread started")
        
        # Per contract [S19.13]: Set state to BOOTING AFTER process is started and drain threads are started
        # This ensures start() always returns with state == BOOTING, even if process exits immediately
        # CRITICAL: State must be set AFTER _start_encoder_process() so that stdin is ready
        # CRITICAL: State must be set AFTER drain threads start so that first PCM write happens after drain threads per [S19.16]
        with self._state_lock:
            self._state = SupervisorState.BOOTING
        if self._on_state_change:
            self._on_state_change(SupervisorState.BOOTING)
        
        # Per contract [S7.4], [A7], [C7.1]: PCM cadence is driven by AudioPump, not Supervisor.
        # Supervisor does NOT operate a timing loop or buffer PCM frames.
        # AudioPump drives timing at 24ms intervals and calls EncoderManager.next_frame() each tick.
        # EncoderManager handles all routing decisions (M11, M12) and calls supervisor.write_pcm().
        # Supervisor writes frames immediately when received - no buffering or pacing.
        self._last_write_ts = None  # Reset write tracking (used for telemetry)
        
        # Step 8-9: Start timer for first-frame detection per contract [S7], [S7A]
        # Per contract [S7B]: First-frame timer MUST use wall-clock time, not frame timestamps
        # or asyncio loop time. Because async clocks can pause under scheduler pressure,
        # wall clock cannot.
        self._startup_time = time.time()  # Use wall-clock time per [S7B]
        self._slow_startup_warn_logged = False
        # Clear startup timeout cancellation event for new timeout monitoring
        self._startup_timeout_cancelled.clear()
        self._startup_timeout_thread = threading.Thread(
            target=self._monitor_startup_timeout,
            daemon=True,
            name="StartupTimeoutMonitor"
        )
        self._startup_timeout_thread.start()
        
        # Per contract [S19.13]: Complete startup and force state → BOOTING before returning
        # Even if FFmpeg died milliseconds ago, start() must return with state == BOOTING
        self._complete_startup()
    
    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop supervisor and encoder process.
        
        Per contract [S31]: Supervisor Shutdown Guarantees
        1. stdin/stdout/stderr drain threads MUST terminate
        2. FFmpeg process MUST be killed if alive
        3. Restart logic MUST be disabled
        4. No background threads may remain running
        5. Shutdown MUST complete within 200ms in test mode
        
        Args:
            timeout: Maximum time to wait for cleanup
        """
        import os as os_module
        start_time = time.time()
        is_test_mode = os_module.getenv("TOWER_TEST_MODE", "0") == "1" or os_module.getenv("PYTEST_CURRENT_TEST") is not None
        
        logger.info("Stopping FFmpegSupervisor...")
        
        # Per contract [S31] #3: Disable restart logic immediately
        self._shutdown_event.set()
        
        # Removed _stop_event.set() - no writer thread per residue sweep
        
        # Cancel startup timeout thread to prevent it from blocking during join
        self._startup_timeout_cancelled.set()
        
        # Set state without calling _set_state to avoid deadlock
        with self._state_lock:
            old_state = self._state
            self._state = SupervisorState.STOPPED
            # Per contract [S31] #3: Disable restart logic by setting flag
            # This prevents _schedule_restart() from starting new restart threads
            self._restart_disabled = True
        
        # Notify outside lock
        if old_state != SupervisorState.STOPPED and self._on_state_change:
            self._on_state_change(SupervisorState.STOPPED)
        
        # CRITICAL: Close file descriptors BEFORE joining threads to unblock blocking I/O operations
        # Threads blocked in readline()/read() will not exit until the file descriptors are closed
        # Close stdout and stderr first to unblock drain threads
        if self._stdout is not None:
            try:
                self._stdout.close()
            except Exception:
                pass
            self._stdout = None
        
        if self._stderr is not None:
            try:
                self._stderr.close()
            except Exception:
                pass
            self._stderr = None
        
        # Close stdin to stop writer thread
        if self._stdin is not None:
            try:
                self._stdin.close()
            except Exception:
                pass
            self._stdin = None
        
        # Per contract [S31] #2: Terminate process - FFmpeg process MUST be killed if alive
        # Do this after closing file descriptors to ensure threads can exit
        if self._process is not None:
            try:
                self._process.terminate()
                process_timeout = 0.1 if is_test_mode else timeout
                self._process.wait(timeout=process_timeout)
            except subprocess.TimeoutExpired:
                logger.warning("Encoder process did not terminate, killing")
                self._process.kill()
                self._process.wait()
            except Exception as e:
                logger.warning(f"Error stopping encoder process: {e}")
            finally:
                self._process = None
        
        # Per contract [S31] #1: Stop threads - ensure all drain threads terminate
        # File descriptors are now closed, so threads should exit quickly
        thread_timeout = 0.1 if is_test_mode else 1.0  # Tighter timeout in test mode per [S31] #5
        
        # Removed writer thread join - no writer thread per residue sweep
        
        if self._stdout_thread is not None and self._stdout_thread.is_alive():
            self._stdout_thread.join(timeout=thread_timeout)
            if self._stdout_thread.is_alive():
                logger.warning("Stdout drain thread did not terminate within timeout")
        
        if self._stderr_thread is not None and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=thread_timeout)
            if self._stderr_thread.is_alive():
                logger.warning("Stderr drain thread did not terminate within timeout")
        
        if self._startup_timeout_thread is not None and self._startup_timeout_thread.is_alive():
            self._startup_timeout_thread.join(timeout=0.05 if is_test_mode else 0.5)
        
        if self._restart_thread is not None and self._restart_thread.is_alive():
            self._restart_thread.join(timeout=0.1 if is_test_mode else 2.0)
            if self._restart_thread.is_alive():
                logger.warning("Restart thread did not terminate within timeout")
        
        # Per contract [S31] #4: Verify no background threads remain running
        # All threads should be daemon threads or already joined above
        remaining_threads = []
        # Removed writer thread check - no writer thread per residue sweep
        if self._stdout_thread is not None and self._stdout_thread.is_alive():
            remaining_threads.append("stdout_drain")
        if self._stderr_thread is not None and self._stderr_thread.is_alive():
            remaining_threads.append("stderr_drain")
        if self._startup_timeout_thread is not None and self._startup_timeout_thread.is_alive():
            remaining_threads.append("startup_timeout")
        if self._restart_thread is not None and self._restart_thread.is_alive():
            remaining_threads.append("restart")
        
        if remaining_threads:
            logger.warning(f"Background threads still running after shutdown: {remaining_threads}")
        
        # Clear stdout accumulator to prevent memory leaks
        self._stdout_accumulator = bytearray()
        
        # Clear stderr buffer to prevent memory leaks
        self._last_stderr = ""
        
        # Clear all thread references to help garbage collection
        # Removed _writer_thread - no writer thread per residue sweep
        self._stdout_thread = None
        self._stderr_thread = None
        self._startup_timeout_thread = None
        self._restart_thread = None
        
        # Reset startup flag
        self._startup_complete = False
        
        # Per contract [S31] #5: Shutdown MUST complete within 200ms in test mode
        elapsed_ms = (time.time() - start_time) * 1000.0
        if is_test_mode and elapsed_ms > 200:
            logger.warning(f"Shutdown took {elapsed_ms:.1f}ms in test mode (target: 200ms)")
        
        logger.info("FFmpegSupervisor stopped")
    
    def get_state(self) -> SupervisorState:
        with self._state_lock:
            state = self._state
            first_frame = self._first_frame_received
            restart_attempts = self._restart_attempts

        # 🎯 Broadcast-grade semantic rule:
        # If we have restarted (restart_attempts > 0)
        # and the new encoder has NOT yet produced first MP3 frame,
        # we are operationally still in RESTARTING.
        if (
            restart_attempts > 0
            and not first_frame
            and state in (SupervisorState.BOOTING, SupervisorState.RESTARTING)
        ):
            return SupervisorState.RESTARTING

        return state
    
    def _on_first_mp3_frame(self) -> None:
        """
        Handle first MP3 frame arrival and transition to RUNNING state.
        
        Per Fix #1: When first MP3 frame arrives, this method:
        - Sets self.state = SupervisorState.RUNNING
        - Emits log: "FFMPEG_SUPERVISOR: first MP3 frame received — entering RUNNING [S7.3]"
        - Cancels startup timeout timer
        - Marks _first_frame_seen = True
        """
        with self._state_lock:
            if self._state == SupervisorState.BOOTING:
                logger.info("FFMPEG_SUPERVISOR: first MP3 frame received — entering RUNNING [S7.3]")
                self._state = SupervisorState.RUNNING
                self._first_frame_seen = True
                # Cancel startup timeout by setting the event
                self._startup_timeout_cancelled.set()
                callback = self._on_state_change
            else:
                callback = None
        
        # Per contract [S13.7]: State change callbacks MUST run strictly outside the lock
        if callback:
            callback(SupervisorState.RUNNING)
        
        # Removed boot buffer flush - no buffers per residue sweep
        # Per contract [A7], [S7.4]: Supervisor writes immediately, no buffering
    
    def _transition_to_running(self) -> None:
        """
        Transition from BOOTING to RUNNING state per contract [S6A], [S19], [S20.1], [S20.1A].
        
        Per contract [S20.1]: On every successful RUNNING transition from BOOTING,
        MUST log INFO "Encoder LIVE (first frame received)".
        
        Per contract [S20.1A]: Log emission MUST be atomic with state change.
        Per contract [S13.7]: State change callbacks MUST run outside the lock.
        
        This method handles the state transition and log emission atomically within the lock,
        then invokes the callback outside the lock.
        """
        callback = None
        with self._state_lock:
            if self._state == SupervisorState.BOOTING:
                self._state = SupervisorState.RUNNING
                # Per contract [S20.1A]: Log emission MUST be atomic with state change
                # Both state change and log occur inside the lock to ensure atomicity
                logger.debug("Supervisor state: BOOTING -> RUNNING (first frame received)")
                # Per contract [S20.1]: On every successful RUNNING transition,
                # log INFO "Encoder LIVE (first frame received)"
                logger.info("Encoder LIVE (first frame received)")
                # Store callback to invoke outside lock per [S13.7]
                callback = self._on_state_change
        
        # Per contract [S13.7]: State change callbacks MUST run strictly outside the lock
        if callback:
            callback(SupervisorState.RUNNING)
        
        # Removed boot buffer flush - no buffers per residue sweep
        # Per contract [A7], [S7.4]: Supervisor writes immediately, no buffering
    
    def get_stdin(self) -> Optional[BinaryIO]:
        """Get encoder stdin for writing PCM frames."""
        return self._stdin
    
    def mark_boot_priming_complete(self) -> None:
        """
        Mark boot priming as complete per contract [S7.3A].
        
        Per contract [S7.4]: PCM cadence is driven by AudioPump, not Supervisor.
        This method is kept for API compatibility but has no effect since Supervisor
        no longer operates a silence feed loop.
        """
        # No-op: Per [S7.4], Supervisor does not generate timing-based writes
        logger.debug("FFMPEG_SUPERVISOR: Boot priming complete [S7.3A] (no-op per [S7.4])")
    
    # Removed _perform_boot_priming_burst() per residue sweep.
    # Per contract [S7.0B]: EncoderManager MUST be capable of supplying PCM before Supervisor starts.
    # Per contract [A7], [C7.1]: AudioPump drives timing and calls EncoderManager.next_frame() each tick.
    # Per contract [M12]: EncoderManager handles all routing - Supervisor does not generate/inject PCM.
    # Per contract [S22A]: Supervisor is source-agnostic and does not generate silence frames.
    # Continuous PCM delivery is handled by AudioPump + EncoderManager from startup.
    
    @property
    def last_stderr(self) -> str:
        """
        Return most recent stderr buffer per contract [S21.3].
        
        Returns the captured stderr output from the most recent FFmpeg process,
        enabling debugging of startup failures and other errors.
        """
        return self._last_stderr
    
    def write_pcm(self, frame: bytes) -> None:
        """
        Write PCM frame immediately to ffmpeg stdin.
        
        Per contract [S7.1], [S7.4], [A7], [C7.1]: Supervisor receives PCM frames via write_pcm()
        and writes them immediately. PCM cadence is driven by AudioPump, not Supervisor.
        Supervisor does NOT buffer or pace PCM frames.
        
        Per contract [S22A]: Supervisor MUST NOT know about noise/silence generation.
        It treats all valid Tower-format PCM frames identically.
        
        Per contract [M12]: All routing decisions (program, silence, fallback) are made by
        EncoderManager. Supervisor is source-agnostic and simply writes whatever frame it receives.
        
        Args:
            frame: PCM frame bytes to write (Tower format, 4608 bytes)
        """
        # First: validate the frame *shape*.
        # This is the edge of the Supervisor API; enforcing the 4608-byte contract
        # here keeps the write operation simple and predictable (F7/F8).

        if not isinstance(frame, (bytes, bytearray)):
            raise TypeError(f"PCM frame must be bytes-like, got {type(frame)!r}")

        frame_len = len(frame)
        if frame_len != FRAME_BYTES:
            # Per core timing + TR-AIR2/S7.0: wrong-sized frames are discarded.
            # We log at DEBUG so tests can inspect this if needed without
            # spamming production logs.
            logger.debug(
                "FFMPEG_SUPERVISOR: rejecting PCM frame with wrong size",
                extra={"len": frame_len, "expected": FRAME_BYTES},
            )
            return
        
        # Per contract [S7.1], [S22A]: Supervisor is source-agnostic and receives
        # PCM frames from EncoderManager. The PCM source (silence, tone, or live)
        # is determined upstream. We only accept frames while actively booting or
        # running; everything else is ignored to keep the API safe if callers are
        # slightly ahead/behind the lifecycle.
        current_state = self.get_state()
        if current_state not in (SupervisorState.BOOTING, SupervisorState.RUNNING):
            return

        # Normalize to immutable bytes to avoid surprises if a bytearray is mutated
        # after enqueuing.
        frame_bytes = bytes(frame)

        # Per contract [A7], [C7.1], [S7.4]: Write immediately - no buffering or pacing.
        # AudioPump drives timing at 24ms intervals via EncoderManager.next_frame().
        # Supervisor is a simple pass-through: receives frame, writes immediately.
        if self._stdin is not None:
            try:
                self._stdin.write(frame_bytes)
                self._stdin.flush()
                
                # Telemetry: Log first byte written to stdin
                if not self._debug_first_stdin_logged:
                    self._debug_first_stdin_logged = True
                    logger.debug("FFMPEG_SUPERVISOR: first PCM bytes written to stdin", extra={"len": len(frame_bytes)})
                
                # Visibility: Track PCM write timestamp
                with self._write_lock:
                    self._last_write_ts = time.monotonic()
            except BrokenPipeError:
                # ffmpeg died, Supervisor failure handler will restart it asynchronously
                # This is non-blocking - per contract [M8], write_pcm() does not wait for restart
                logger.debug("FFMPEG_SUPERVISOR: BrokenPipeError during write_pcm() - restart will be handled asynchronously")
                # Don't raise - per contract [M8], errors are handled by supervisor's restart logic
            except Exception as e:
                # Other errors (e.g., pipe closed) - log and let restart logic handle it
                logger.debug(f"FFMPEG_SUPERVISOR: Error during write_pcm(): {e}")
    
    # Removed _pcm_writer_loop() per residue sweep.
    # Per contract [A7], [C7.1]: AudioPump is the single timing authority.
    # Per contract [M12]: EncoderManager handles all routing decisions.
    # Per contract [S7.4]: PCM cadence is driven by AudioPump, not Supervisor.
    # Supervisor now writes PCM immediately when received via write_pcm().
    
    def _set_state(self, new_state: SupervisorState) -> None:
        """Set state and notify callback."""
        old_state = None
        with self._state_lock:
            old_state = self._state
            self._state = new_state
        
        # Notify outside lock to avoid deadlock
        if old_state != new_state:
            logger.debug(f"Supervisor state: {old_state} -> {new_state}")
            if self._on_state_change:
                self._on_state_change(new_state)
    
    def _force_booting(self, tag: str = "[S13.8][S29] restart/boot normalization") -> None:
        """
        Force state to BOOTING per contract requirements.
        
        Used to enforce [S13.8], [S29], [S19.13] guarantees that BOOTING must be
        observable after process spawn, even if async failures have already
        transitioned to RESTARTING/FAILED.
        
        Args:
            tag: Descriptive tag for logging/debugging context
        """
        callback = None
        with self._state_lock:
            # Set BOOTING regardless of current state (unless STOPPED) per contract
            if self._state != SupervisorState.STOPPED:
                old_state = self._state
                self._state = SupervisorState.BOOTING
                callback = self._on_state_change
        
        # Per contract [S13.7]: State change callbacks MUST run outside the lock
        if callback:
            callback(SupervisorState.BOOTING)
    
    def _check_test_isolation(self) -> None:
        """
        Contract [I25] enforcement — FFmpeg start is opt-in only.
        
        Per contract [I25]: The system MUST prevent FFmpeg from starting during tests
        unless the test is explicitly marked as an integration test. If FFmpeg would
        otherwise start implicitly, the system MUST fail loudly.
        
        Enforcement is via explicit configuration (allow_ffmpeg parameter) and
        environment variable override. Production code does NOT detect test context.
        """
        if self._allow_ffmpeg:
            return
        
        if os.getenv("TOWER_ALLOW_FFMPEG_IN_TESTS") == "1":
            return
        
        raise RuntimeError(
            "FFmpegSupervisor attempted to start without encoder permission. "
            "Tests must disable encoder or enable explicitly using "
            "TOWER_ALLOW_FFMPEG_IN_TESTS=1 or allow_ffmpeg=True in DI. "
            "See contract [I25]."
        )
    
    def _start_encoder_process(self) -> None:
        """
        Start FFmpeg encoder process per contract [S19].
        
        Steps per [S19]:
        1. Test isolation check per [I25], [S19.12]
        2. Create FFmpeg subprocess with subprocess.Popen()
        3. Log process PID: logger.info(f"Started ffmpeg PID={process.pid}")
        4. Start stderr drain thread immediately
        5. Start stdout drain thread
        7. Enter BOOTING state per [S6A] and start the 500ms first-frame timer [S7]
        8. Monitor for first MP3 frame arrival
        9. If no frame arrives by 500ms → log LEVEL=WARN "slow startup" per [S7]
        10. If first frame arrives within hard timeout → transition to RUNNING state per [S6A]
        11. If timeout exceeds hard timeout per [S7A] → treat as failure per [S10]/[S9]/[S13]
        
        Note: Per contract [M25], all PCM generation MUST go through AudioPump.
        Supervisor does NOT write initial silence frames directly to stdin.
        The first PCM frame is provided by AudioPump via EncoderManager.next_frame().
        """
        try:
            # Per contract [I25]: Check test isolation before starting FFmpeg
            # This must raise RuntimeError if FFmpeg is started without permission
            self._check_test_isolation()
            
            # Per contract [S25]: Modify FFmpeg command for debug mode
            ffmpeg_cmd = self._build_ffmpeg_cmd()
            
            # Telemetry: Log command and environment before starting
            safe_env_subset = {
                "PATH": os.environ.get("PATH"),
                "FFMPEG_BIN": os.environ.get("FFMPEG_BIN"),
                "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH"),
                "LANG": os.environ.get("LANG"),
            }
            logger.debug("FFMPEG_SUPERVISOR: starting ffmpeg", extra={"cmd": ffmpeg_cmd, "env_subset": safe_env_subset})
            
            # Telemetry: Sanity checks for ffmpeg command and environment
            ffmpeg_bin = ffmpeg_cmd[0] if ffmpeg_cmd else None
            if ffmpeg_bin:
                # Check if ffmpeg is in PATH
                import shutil
                ffmpeg_in_path = shutil.which(ffmpeg_bin)
                logger.debug(
                    "FFMPEG_SUPERVISOR: ffmpeg binary check",
                    extra={"bin": ffmpeg_bin, "in_path": ffmpeg_in_path is not None, "resolved_path": ffmpeg_in_path}
                )
                
                # Check if FFMPEG_BIN env var is set and points to executable
                ffmpeg_bin_env = os.environ.get("FFMPEG_BIN")
                if ffmpeg_bin_env:
                    ffmpeg_bin_exists = os.path.exists(ffmpeg_bin_env)
                    ffmpeg_bin_executable = os.access(ffmpeg_bin_env, os.X_OK) if ffmpeg_bin_exists else False
                    logger.debug(
                        "FFMPEG_SUPERVISOR: FFMPEG_BIN env check",
                        extra={"FFMPEG_BIN": ffmpeg_bin_env, "exists": ffmpeg_bin_exists, "executable": ffmpeg_bin_executable}
                    )
            
            # Verify PCM format matches command (sanity check)
            # Command should have -f s16le -ar 48000 -ac 2
            if "-f" in ffmpeg_cmd:
                fmt_idx = ffmpeg_cmd.index("-f")
                if fmt_idx + 1 < len(ffmpeg_cmd):
                    pcm_format = ffmpeg_cmd[fmt_idx + 1]
                    logger.debug("FFMPEG_SUPERVISOR: PCM format check", extra={"format": pcm_format, "expected": "s16le"})
            
            if "-ar" in ffmpeg_cmd:
                ar_idx = ffmpeg_cmd.index("-ar")
                if ar_idx + 1 < len(ffmpeg_cmd):
                    sample_rate = ffmpeg_cmd[ar_idx + 1]
                    logger.debug("FFMPEG_SUPERVISOR: sample rate check", extra={"sample_rate": sample_rate, "expected": "48000"})
            
            if "-ac" in ffmpeg_cmd:
                ac_idx = ffmpeg_cmd.index("-ac")
                if ac_idx + 1 < len(ffmpeg_cmd):
                    channels = ffmpeg_cmd[ac_idx + 1]
                    logger.debug("FFMPEG_SUPERVISOR: channels check", extra={"channels": channels, "expected": "2"})
            
            # Per contract [S25.1]: Log full FFmpeg command at startup in debug mode
            if self._debug_mode:
                logger.info(f"[DEBUG] Executing FFmpeg command: {' '.join(ffmpeg_cmd)}")
            
            # Step 1: Create subprocess
            # All file descriptors (stdin, stdout, stderr) remain in blocking mode
            # Python pipes are designed to work in blocking mode, not non-blocking mode
            self._process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            
            # Telemetry: Log after Popen succeeds
            logger.info("FFMPEG_SUPERVISOR: ffmpeg started", extra={"pid": self._process.pid})
            
            # All file descriptors remain in blocking mode (default for subprocess.PIPE)
            self._stdin = self._process.stdin
            self._stdout = self._process.stdout
            self._stderr = self._process.stderr
            
            # Step 2: Log process PID per contract [S19]
            logger.info(f"Started ffmpeg PID={self._process.pid}")
            
            # Check if process exited immediately per contract [S9], [S21]
            time.sleep(0.2)  # Give FFmpeg a moment to start
            
            # Per contract [S21.2]: Defensively handle cases where poll() returns non-int/None (e.g., MagicMock)
            poll_result = self._process.poll()
            if poll_result is not None and isinstance(poll_result, int):
                # Process exited with valid exit code
                exit_code = self._process.returncode
                # Defensively handle MagicMock objects in tests
                if exit_code is not None and isinstance(exit_code, int):
                    exit_code_str = str(exit_code)
                else:
                    exit_code_str = "unknown"
                logger.error(f"🔥 FFmpeg exited immediately at startup (exit code: {exit_code_str})")
                
                # Telemetry: Log unexpected process exit during startup
                logger.error(
                    "FFMPEG_SUPERVISOR: ffmpeg exited during startup",
                    extra={"pid": self._process.pid, "returncode": exit_code_str, "phase": "BOOTING"}
                )
                
                # Read and log stderr per contract [S21]
                self._read_and_log_stderr()
                
                # Per [S19.13]/[S19.14]: do *not* transition state or schedule
                # restarts here while start() is still in progress. Failure has
                # been detected and logged; handling is deferred simply by
                # virtue of *not* calling _handle_failure() until after
                # startup is complete.
                return
            
            
        except RuntimeError as e:
            # Per contract [I25]: RuntimeError from test isolation check must propagate
            # This ensures tests fail loudly when FFmpeg is started inappropriately
            if "FFmpegSupervisor attempted to start without encoder permission" in str(e):
                # Re-raise test isolation errors per [I25]
                raise
            # Other RuntimeErrors are treated as general failures
            logger.error(f"Failed to start encoder process: {e}", exc_info=True)
            self._process = None
            self._stdin = None
            self._stdout = None
            self._stderr = None
        except Exception as e:
            logger.error(f"Failed to start encoder process: {e}", exc_info=True)
            self._process = None
            self._stdin = None
            self._stdout = None
            self._stderr = None
    
    def _build_ffmpeg_cmd(self) -> List[str]:
        """
        Build FFmpeg command with debug mode support per contract [S25].
        Ensures -frame_size 1152 is present per contract [S19.11].
        
        Returns:
            FFmpeg command list with appropriate loglevel based on TOWER_ENCODER_DEBUG
            and guaranteed to include -frame_size 1152.
        """
        # Make a copy to avoid modifying the original
        cmd = list(self._ffmpeg_cmd)
        
        # Per contract [S19.11]: Ensure -frame_size 1152 is present
        # This forces MP3 packetization at correct Tower frame boundaries
        if "-frame_size" not in cmd:
            # Insert -frame_size 1152 after -b:a (bitrate) or before -f mp3
            try:
                # Try to find -b:a and insert after it
                bitrate_idx = cmd.index("-b:a")
                if bitrate_idx + 2 < len(cmd):
                    cmd.insert(bitrate_idx + 2, "-frame_size")
                    cmd.insert(bitrate_idx + 3, "1152")
                else:
                    # Fallback: insert before -f mp3
                    mp3_idx = cmd.index("-f")
                    if cmd[mp3_idx + 1] == "mp3":
                        cmd.insert(mp3_idx, "1152")
                        cmd.insert(mp3_idx, "-frame_size")
            except ValueError:
                # Neither -b:a nor -f mp3 found, insert before last argument (pipe:1)
                cmd.insert(-1, "-frame_size")
                cmd.insert(-1, "1152")
        
        # Per contract [S25.1]: Use -loglevel debug when TOWER_ENCODER_DEBUG=1
        # Per contract [S25.2]: Use normal runtime loglevel (e.g. warning) when unset or 0
        if self._debug_mode:
            # Replace existing -loglevel argument with debug
            # Find -loglevel in command and replace its value
            try:
                loglevel_idx = cmd.index("-loglevel")
                if loglevel_idx + 1 < len(cmd):
                    cmd[loglevel_idx + 1] = "debug"
                else:
                    # If -loglevel exists but no value, add debug
                    cmd.insert(loglevel_idx + 1, "debug")
            except ValueError:
                # -loglevel not found, insert it after -nostdin or at appropriate position
                # Try to insert after common flags
                insert_pos = 1
                if "-nostdin" in cmd:
                    insert_pos = cmd.index("-nostdin") + 1
                elif "-hide_banner" in cmd:
                    insert_pos = cmd.index("-hide_banner") + 1
                cmd.insert(insert_pos, "-loglevel")
                cmd.insert(insert_pos + 1, "debug")
        # If not debug mode, command is unchanged (preserves existing -loglevel warning)
        
        return cmd
    
    def _stderr_drain(self) -> None:
        """
        Drain FFmpeg stderr per contract [S14].
        
        Requirements:
        - [S14.1] Start immediately after process creation (already done in start())
        - [S14.2] Stderr drain thread started (done in _start_encoder_process())
        - [S14.3] Use readline() in continuous loop with blocking I/O
        - [S14.4] Log each line with [FFMPEG] prefix
        - [S14.5] Never block main thread (runs as daemon thread)
        - [S14.6] Continue reading until stderr closes
        """
        if self._process is None:
            return
        proc = self._process  # Keep reference
        if proc.stderr is None:
            return
        
        try:
            # Per contract [S14.3]: Use readline() in continuous loop
            # Stderr is in blocking mode, so readline() will block until data is available or EOF
            while not self._shutdown_event.is_set():
                try:
                    line = proc.stderr.readline()
                    # Per contract [S21.2]: Defensively handle non-string stderr data (e.g., unittest mocks)
                    # Handle None explicitly - readline() can return None on closed/invalid file descriptors
                    if line is None:
                        # File descriptor is closed or in invalid state
                        logger.debug("Stderr readline() returned None - file descriptor closed or invalid")
                        break
                    
                    # Check if line is actually bytes before processing
                    if not isinstance(line, bytes):
                        # In tests, readline() might return a MagicMock - skip this line
                        # This prevents test noise from MagicMock string representations
                        if not line:  # EOF or empty
                            break
                        continue  # Skip MagicMock or other non-bytes objects
                    
                    if not line:
                        # EOF - stderr closed (process ended)
                        # Fix #3: Suppress EOF during BOOTING until MP3 frames begin
                        current_state = self.get_state()
                        if current_state == SupervisorState.BOOTING:
                            # Ignore EOF during BOOTING - continue monitoring
                            logger.debug("Ignoring stderr EOF during BOOTING - waiting for first MP3 frame")
                            continue
                        break
                    
                    try:
                        decoded_line = line.decode(errors='ignore').rstrip()
                    except (AttributeError, TypeError):
                        # In tests, decode() might return a mock object - skip this line
                        # This prevents test noise from MagicMock string representations
                        continue
                    
                    # Only log if decoded_line is actually a string (not a mock object in tests)
                    if isinstance(decoded_line, str) and decoded_line:
                        # Per contract [S14.4]: Log with [FFMPEG] prefix
                        # "Guessed Channel Layout" is an FFmpeg stdout message, not an actual error
                        # Demote to DEBUG for informational FFmpeg messages
                        if "Guessed channel layout" in decoded_line or "guessed channel layout" in decoded_line.lower():
                            logger.debug(f"[FFMPEG] {decoded_line}")
                        else:
                            # Real errors still logged at ERROR level
                            logger.error(f"[FFMPEG] {decoded_line}")
                        # Per contract [S25.1]: Also log at DEBUG level when debug mode enabled
                        if self._debug_mode:
                            logger.debug(f"[FFMPEG] {decoded_line}")
                        # Per contract [S21.3]: Capture stderr for exposure
                        # Limit size to prevent memory leaks
                        new_line = decoded_line + "\n"
                        if len(self._last_stderr) + len(new_line) > self._last_stderr_max_size:
                            # Keep only the most recent data (truncate from beginning)
                            excess = len(self._last_stderr) + len(new_line) - self._last_stderr_max_size
                            self._last_stderr = self._last_stderr[excess:]
                        self._last_stderr += new_line
                except (OSError, ValueError, TypeError) as e:
                    # Stderr closed or error reading
                    # TypeError can occur when readline() returns None on invalid file descriptor
                    error_msg = str(e)
                    if "NoneType" in error_msg or "read() should have returned" in error_msg:
                        # File descriptor is in invalid state (likely closed)
                        logger.debug("Stderr file descriptor invalid (likely closed) - readline() returned None")
                    else:
                        logger.debug(f"Stderr read error (likely closed): {e}")
                    break
            
            # Per contract [S14.6]: Loop exits when stderr closes or shutdown
            logger.debug("FFmpeg stderr drain thread exiting")
        except Exception as e:
            logger.warning(f"Stderr drain thread error: {e}")
    
    def _stdout_drain(self) -> None:
        """
        Drain FFmpeg stdout, packetize MP3 frames, and push to buffer.
        
        Tracks frame timing per contract [S17], [S18] and detects stalls per [S11].
        """
        logger.info("Encoder stdout drain thread running")
        
        last_log_time = time.monotonic()
        
        try:
            while not self._shutdown_event.is_set():
                # Check for process exit per contract [S9]
                if self._process is not None:
                    poll_result = self._process.poll()
                    if poll_result is not None and isinstance(poll_result, int):
                        exit_code = self._process.returncode
                        current_state = self.get_state()
                        
                        # Fix #3: Suppress process exit detection during BOOTING until MP3 frames begin
                        # Only suppress if we haven't received first MP3 frame yet
                        if current_state == SupervisorState.BOOTING and not self._first_frame_received:
                            # Ignore process exit during BOOTING before first MP3 frame - continue monitoring
                            # This allows FFmpeg startup sequence to complete
                            logger.debug(f"Ignoring process exit during BOOTING before first MP3 frame (exit_code: {exit_code})")
                            continue
                        
                        # Per contract [S19.14]: Queue if STARTING, process if BOOTING+
                        if current_state == SupervisorState.BOOTING:
                            exit_code_str = str(exit_code) if exit_code is not None and isinstance(exit_code, int) else "unknown"
                            logger.error(
                                "FFMPEG_SUPERVISOR: ffmpeg exited during startup",
                                extra={"pid": self._process.pid, "returncode": exit_code_str, "phase": "BOOTING"}
                            )
                        self._on_process_failure("process_exit", exit_code=exit_code)
                        if self.get_state() != SupervisorState.STARTING:
                            # Was processed (not STARTING), break monitoring
                            logger.warning("Encoder process exited - triggering restart")
                            break
                        # Was deferred (STARTING), continue monitoring
                
                # Read from stdout (blocking mode - will block until data is available or EOF)
                data = None
                current_state = self.get_state()
                
                try:
                    data = self._stdout.read(4096) if self._stdout else None
                except (OSError, ValueError) as e:
                    # Fix #3: Suppress read errors during BOOTING until MP3 frames begin
                    # Only suppress if we haven't received first MP3 frame yet
                    if current_state == SupervisorState.BOOTING and not self._first_frame_received:
                        # Ignore read errors during BOOTING before first MP3 frame - continue monitoring
                        logger.debug(f"Ignoring read error during BOOTING (before first MP3 frame): {e}")
                        continue
                    
                    logger.warning(f"Read error in drain thread: {e}")
                    # Per contract [S19.14]: Queue if STARTING, process if BOOTING+
                    self._on_process_failure("read_error", error=str(e))
                    if self.get_state() != SupervisorState.STARTING:
                        # Was processed (not STARTING), break
                        break
                    # Was deferred (STARTING), continue monitoring
                    data = None  # Ensure data is set even in exception path
                
                if not data:
                    # Fix #3: Suppress EOF during BOOTING until MP3 frames begin
                    # Only suppress if we haven't received first MP3 frame yet
                    if current_state == SupervisorState.BOOTING and not self._first_frame_received:
                        # Ignore EOF during BOOTING before first MP3 frame - continue monitoring
                        # This allows FFmpeg to start up without triggering false failures
                        # Once we've received first MP3 frame, EOF should trigger normal failure handling
                        logger.debug("Ignoring EOF during BOOTING (before first MP3 frame) - waiting for first MP3 frame")
                        continue
                    
                    # If we're in BOOTING but have received first frame, we should have transitioned to RUNNING
                    # If we're still in BOOTING and get EOF after first frame, something is wrong
                    # This should not happen in normal operation, but handle it gracefully
                    if current_state == SupervisorState.BOOTING and self._first_frame_received:
                        logger.warning("EOF detected during BOOTING after first MP3 frame - should have transitioned to RUNNING")
                    
                    # EOF - encoder died per contract [S9], [S21.1]
                    # Get process return code before handling failure
                    exit_code = None
                    if self._process is not None:
                        # Per contract [S21.1]: Get return code when process exits
                        # Per contract [S21.2]: Defensively handle cases where poll() returns non-int/None
                        # poll() returns None if process is still running, or exit code if exited
                        poll_result = self._process.poll()
                        if poll_result is not None and isinstance(poll_result, int):
                            # Process has exited with valid exit code - returncode should be available
                            exit_code = self._process.returncode
                        elif poll_result is None:
                            # Process might still be running but stdout closed (unusual)
                            # Or process just exited and returncode not set yet
                            # Try getting returncode directly (may be None if process was killed)
                            exit_code = getattr(self._process, 'returncode', None)
                            # If still None, process might have been killed or terminated abnormally
                            if exit_code is None:
                                # Give it a tiny moment for returncode to be set (non-blocking check)
                                # This handles race condition where process just exited
                                time.sleep(0.001)  # 1ms - minimal delay
                                poll_result = self._process.poll()
                                if poll_result is not None and isinstance(poll_result, int):
                                    exit_code = self._process.returncode
                        # If poll_result is not None but not an int (e.g., MagicMock), skip exit_code
                        # This handles test scenarios where poll() returns MagicMock per [S21.2]
                    
                    # Defensively handle MagicMock objects in tests per [S21.2]
                    # Only log exit_code if it's a valid integer or None
                    # MagicMock objects will fail this check and be logged as "unknown"
                    if exit_code is None:
                        exit_code_str = "None"
                    elif isinstance(exit_code, int):
                        exit_code_str = str(exit_code)
                    else:
                        # exit_code is not None and not an int - likely a MagicMock in tests
                        # Per contract [S21.2]: Logs MUST degrade gracefully without MagicMock representations
                        exit_code_str = "unknown"
                    logger.warning(
                        f"Encoder stdout EOF - encoder process ended "
                        f"(exit code: {exit_code_str})"
                    )
                    # Per contract [S19.14]: Defer if STARTING, process if BOOTING+
                    self._on_process_failure("eof", exit_code=exit_code)
                    if self.get_state() != SupervisorState.STARTING:
                        # Was processed (not STARTING), break
                        break
                    # Was deferred (STARTING), continue monitoring
                
                # NOTE: This is the ONLY place MP3 exists in Tower architecture.
                # The internal pipeline (AudioInputRouter → AudioPump → EncoderManager → FFmpegSupervisor)
                # is 100% PCM-only. MP3 only exists at FFmpeg's stdout (output boundary).
                # This buffer is for HTTP output only, not part of the internal PCM pipeline.
                
                # Per contract F9.1: FFmpeg handles MP3 packetization entirely
                # FFmpeg outputs MP3 bytes to stdout, which we buffer for HTTP clients
                # Telemetry: Log first byte read from stdout
                if not self._debug_first_stdout_logged:
                    self._debug_first_stdout_logged = True
                    logger.info("FFMPEG_SUPERVISOR: first MP3 bytes read from stdout (output boundary)")
                
                # Per contract F9: Accumulate bytes and detect frame boundaries
                # Append new bytes to accumulator (with size limit to prevent memory leaks)
                self._stdout_accumulator.extend(data)
                
                # Prevent unbounded growth - if accumulator gets too large, truncate from beginning
                # This should be rare, but protects against malformed MP3 data or sync word detection failures
                if len(self._stdout_accumulator) > self._stdout_accumulator_max_size:
                    logger.warning(f"Stdout accumulator exceeded max size ({self._stdout_accumulator_max_size} bytes), truncating")
                    # Keep only the most recent data (last 512KB)
                    keep_size = 512 * 1024
                    self._stdout_accumulator = self._stdout_accumulator[-keep_size:]
                
                # Process complete frames from accumulator
                frames_pushed = 0
                while True:
                    # Find next MP3 frame by looking for sync word
                    sync_pos = self._find_mp3_sync(self._stdout_accumulator)
                    if sync_pos is None:
                        # No sync word found - need more data
                        break
                    
                    # Remove any data before sync word (garbage/incomplete data)
                    if sync_pos > 0:
                        self._stdout_accumulator = self._stdout_accumulator[sync_pos:]
                    
                    # Try to detect frame size starting at sync word
                    frame_size = self._detect_mp3_frame_size(self._stdout_accumulator)
                    if frame_size is None:
                        # Can't determine frame size yet - need more data
                        break
                    
                    if len(self._stdout_accumulator) < frame_size:
                        # Not enough data for this frame yet
                        break
                    
                    # Extract complete frame
                    frame = bytes(self._stdout_accumulator[:frame_size])
                    self._stdout_accumulator = self._stdout_accumulator[frame_size:]
                    
                    # Push complete frame to output buffer (per contract F9)
                    self._mp3_buffer.push_frame(frame)
                    frames_pushed += 1
                    
                    # Update last frame time for timing/stall detection
                    now_monotonic = time.monotonic()
                    if self._last_frame_time is None:
                        self._last_frame_time = now_monotonic
                    
                    # Track first frame for RUNNING transition (only on first frame pushed)
                    if not self._first_frame_received:
                        self._first_frame_received = True
                        now = time.time()  # Use wall-clock time per [S7B]
                        self._first_frame_time = now
                        elapsed_ms = (now - self._startup_time) * 1000.0 if self._startup_time else 0
                        logger.info(f"First MP3 output received after {elapsed_ms:.1f}ms (from PCM input)")
                        # Per Fix #1: Call _on_first_mp3_frame() to handle RUNNING transition
                        self._on_first_mp3_frame()
                
                # If we pushed frames, update timing tracking
                if frames_pushed > 0:
                    now_monotonic = time.monotonic()
                    # Per contract [S18]: Non-strict output cadence - encoder batching is normal
                    # Frame interval tracking is used solely for stall detection, not for enforcing strict timing
                    if self._last_frame_time is not None:
                        # Track last frame time for stall detection only
                        pass
                    self._last_frame_time = now_monotonic
                
                # Buffer stats tracking (demoted to DEBUG - not contract-required)
                if frames_pushed > 0:
                    # Log buffer size every 10 seconds at DEBUG level
                    now = time.monotonic()
                    if now - last_log_time >= 10.0:
                        stats = self._mp3_buffer.stats()
                        logger.debug(f"MP3 output buffer: {stats.count} frames")
                        last_log_time = now
                    
                    # Check for stall per contract [S11]
                    # Fix #4: Only check for stall after first MP3 frame (RUNNING state)
                    # Stall detection is disabled during BOOTING per Fix #1
                    if self._first_frame_received:
                        self._check_stall()
                
        except Exception as e:
            logger.error(f"Unexpected error in drain thread: {e}", exc_info=True)
            # Per contract [S19.14]: Defer if STARTING, process if BOOTING+
            self._on_process_failure("drain_error", error=str(e))
        finally:
            logger.debug("Encoder output drain thread stopped")
    
    def _find_mp3_sync(self, data: bytearray) -> Optional[int]:
        """
        Find MP3 sync word position in accumulator.
        
        MP3 sync word: 0xFF followed by byte with top 3 bits = 0xE0 (0xFB-0xFF).
        
        Args:
            data: Bytearray to search for sync word
            
        Returns:
            Index of sync word if found, None otherwise
        """
        if len(data) < 2:
            return None
        
        # Search for sync word pattern: 0xFF followed by valid header byte
        for i in range(len(data) - 1):
            if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
                return i
        
        return None
    
    def _detect_mp3_frame_size(self, data: bytearray) -> Optional[int]:
        """
        Detect MP3 frame size by parsing frame header.
        
        Per contract F9: Must detect frame boundaries correctly.
        MP3 frame starts with sync word 0xFF followed by valid header byte (0xFB-0xFF).
        Frame size = (144 * bitrate_bps) / sample_rate + padding
        
        Args:
            data: Bytearray with potential MP3 frame starting at index 0
            
        Returns:
            Frame size in bytes if valid frame detected, None otherwise
        """
        if len(data) < 4:
            return None  # Need at least 4 bytes for header
        
        # Check for MP3 sync word: 0xFF followed by 0xFB-0xFF (top 3 bits must be 0xE0)
        if data[0] != 0xFF:
            return None
        
        second_byte = data[1]
        if (second_byte & 0xE0) != 0xE0:
            return None  # Invalid sync word
        
        # Parse header to get bitrate and sample rate
        # Byte 2: bitrate index (bits 4-7), sample rate index (bits 2-3), padding (bit 1)
        header_byte2 = data[2]
        
        # Extract bitrate index (bits 4-7)
        bitrate_index = (header_byte2 >> 4) & 0x0F
        # Extract sample rate index (bits 2-3)
        sample_rate_index = (header_byte2 >> 2) & 0x03
        # Extract padding bit (bit 1)
        padding = (header_byte2 >> 1) & 0x01
        
        # Bitrate lookup table (kbps)
        BITRATE_TABLE = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
        # Sample rate lookup table (Hz)
        SAMPLE_RATE_TABLE = [44100, 48000, 32000, 0]
        
        if bitrate_index >= len(BITRATE_TABLE) or sample_rate_index >= len(SAMPLE_RATE_TABLE):
            return None
        
        bitrate_kbps = BITRATE_TABLE[bitrate_index]
        sample_rate = SAMPLE_RATE_TABLE[sample_rate_index]
        
        if bitrate_kbps == 0 or sample_rate == 0:
            return None  # Invalid bitrate or sample rate
        
        # Calculate frame size: (144 * bitrate_bps) / sample_rate + padding
        bitrate_bps = bitrate_kbps * 1000
        frame_size = int((144 * bitrate_bps) / sample_rate) + padding
        
        if frame_size < 4:
            return None  # Invalid frame size
        
        return frame_size
    
    def _check_stall(self) -> None:
        """
        Check for encoder stall per contract [S11].
        
        Stall is detected when no MP3 frames are received for STALL_THRESHOLD_MS
        after the first frame.
        
        Per Fix #1: DO NOT detect stalls during BOOTING. Stall detection only
        activates after first MP3 frame (when state == RUNNING).
        """
        # Fix #1: Disable stall detection while state == BOOTING
        current_state = self.get_state()
        if current_state == SupervisorState.BOOTING:
            # DO NOT detect stalls during boot
            return
        
        if not self._first_frame_received:
            return  # Can't detect stall until first frame received
        
        if self._last_frame_time is None:
            return
        
        now = time.monotonic()
        elapsed_ms = (now - self._last_frame_time) * 1000.0
        
        if elapsed_ms >= self._stall_threshold_ms:
            logger.warning(f"🔥 FFmpeg stall detected: {elapsed_ms:.0f}ms without frames")
            # Per contract [S19.14]: Defer if STARTING, process if BOOTING+
            self._on_process_failure("stall", elapsed_ms=elapsed_ms)
    
    def _monitor_startup_timeout(self) -> None:
        """
        Monitor startup timeout per contract [S7], [S7A], [S10].
        
        Per contract [S7]: If no frame arrives by 500ms → log LEVEL=WARN "slow startup".
        This is not a restart condition.
        
        Per contract [S7A]: Hard timeout (default 1500ms) triggers restart per [S13].
        Per contract [S7.1E]: Startup timeout should only fire if MP3 not yet seen.
        
        Thread safety: This method runs in a daemon thread and does not hold locks
        for extended periods. Failure handling is delegated via _queue_failure_if_starting()
        which safely handles state transitions without deadlock risk.
        """
        # If ffmpeg is disabled (test mode), don't enforce startup timeout
        if not getattr(self, "_allow_ffmpeg", True):
            return
        
        if self._startup_time is None:
            return
        
        # Step 10 per contract [S19]: Monitor for 500ms soft target per [S7]
        # Check for cancellation during sleep
        if self._startup_timeout_cancelled.wait(timeout=SOFT_STARTUP_TARGET_SEC):
            # Timeout was cancelled (first frame arrived)
            return
        
        # Check if first frame arrived within soft target (500ms)
        # Per contract [S7.1E]: Only check if MP3 not yet seen
        # Also check cancellation event
        if self._startup_timeout_cancelled.is_set():
            return
        
        if not self._first_frame_received and not self._slow_startup_warn_logged:
            # Per contract [S7]: Startup delay is normal; contracts do not specify thresholds
            # Demoted to DEBUG - startup timing varies and is not an error condition
            logger.debug("FFmpeg startup: first frame not yet received (startup delay is normal)")
            self._slow_startup_warn_logged = True
        
        # Step 12 per contract [S19]: Wait for hard timeout per [S7A]
        remaining_time = STARTUP_TIMEOUT_SEC - SOFT_STARTUP_TARGET_SEC
        if remaining_time > 0:
            # Check for cancellation during remaining sleep
            if self._startup_timeout_cancelled.wait(timeout=remaining_time):
                # Timeout was cancelled (first frame arrived)
                return
        
        # Check cancellation event one more time before firing timeout
        if self._startup_timeout_cancelled.is_set():
            return
        
        # Per contract [S7.1E]: Startup timeout should only fire if MP3 not yet seen
        # Check if first frame arrived within hard timeout
        if not self._first_frame_received:
            # Telemetry: Log startup timeout firing
            logger.error(
                "FFMPEG_SUPERVISOR: startup timeout fired, no MP3 produced",
                extra={"timeout_sec": STARTUP_TIMEOUT_SEC}
            )
            # Per contract [S7A], [S20]: Log error and restart per [S13]
            logger.error(f"🔥 FFmpeg did not produce first MP3 frame within {STARTUP_TIMEOUT_MS}ms")
            # Observability: Log captured stderr to diagnose startup failures
            logger.error("FFMPEG_SUPERVISOR: last_stderr at startup timeout: %s", self.last_stderr or "<empty>")
            # Per contract [S19.14]: Defer if STARTING, process if BOOTING+
            # This delegates failure handling safely without deadlock risk
            self._on_process_failure("startup_timeout")
    
    def _on_process_failure(
        self,
        failure_type: str,
        exit_code: Optional[int] = None,
        elapsed_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Handle process failure, deferring if in STARTING state.
        
        Per contract [S19.14]: If ffmpeg exits during STARTING or before first-frame detection,
        failure handling MUST be deferred until after BOOTING state is set.
        
        Args:
            failure_type: Type of failure (process_exit, startup_timeout, stall, etc.)
            exit_code: Process exit code (for process_exit)
            elapsed_ms: Elapsed time in ms (for stall/timeout)
            error: Error message (for read_error, etc.)
        """
        should_log_exit = False
        should_read_stderr = False
        exit_code_str = None
        is_deferred = False
        
        with self._state_lock:
            # Per contract [S19.14]: Defer failures during STARTING state OR if startup
            # is not yet complete (even if state is BOOTING, _complete_startup() may have
            # just been called but start() hasn't returned yet). This ensures start() returns
            # with state == BOOTING per [S19.13].
            if self._state == SupervisorState.STARTING or not self._startup_complete:
                is_deferred = True
                # Queue this event to run after BOOTING promotion and startup completion
                with self._pending_failure_lock:
                    self._pending_failures += 1
                    # Store failure details (keep last failure if multiple occur)
                    self._pending_failure_details = (failure_type, {
                        'exit_code': exit_code,
                        'elapsed_ms': elapsed_ms,
                        'error': error,
                    })
                logger.debug(f"Deferred failure during startup: {failure_type} (state={self._state.name}, startup_complete={self._startup_complete}, will process after BOOTING)")
                
                # Per contract [S20], [S21]: Log exit code and stderr immediately when process exits
                # during STARTING/BOOTING, even though state transition is deferred
                if failure_type in ("process_exit", "eof", "stdin_broken"):
                    should_log_exit = True
                    if exit_code is not None and isinstance(exit_code, int):
                        exit_code_str = str(exit_code)
        
        # Check if stderr thread is alive (outside lock to avoid deadlock)
        if should_log_exit:
            stderr_thread_alive = False
            if self._stderr_thread is not None:
                try:
                    stderr_thread_alive = self._stderr_thread.is_alive()
                except Exception:
                    pass
            should_read_stderr = not stderr_thread_alive
        
        # Log exit code and read stderr outside the lock per contract [S20], [S21]
        if should_log_exit:
            if failure_type == "process_exit":
                if exit_code_str is not None:
                    logger.error(
                        f"🔥 FFmpeg exited immediately at startup (exit code: {exit_code_str})"
                    )
                else:
                    logger.error(
                        "🔥 FFmpeg exited immediately at startup "
                        "(exit code: unknown - process may have been killed)"
                    )
            elif failure_type == "eof":
                if exit_code_str is not None:
                    logger.error(f"🔥 FFmpeg stdout EOF (exit code: {exit_code_str})")
                else:
                    logger.error(
                        "🔥 FFmpeg stdout EOF (exit code: unknown - process may have been "
                        "killed or terminated abnormally)"
                    )
            elif failure_type == "stdin_broken":
                if exit_code_str is not None:
                    logger.error(f"🔥 FFmpeg stdin broken (exit code: {exit_code_str})")
                else:
                    logger.error(
                        "🔥 FFmpeg stdin broken (exit code: unknown - process may have been killed)"
                    )
            
            # Per contract [S21]: Read and log stderr immediately when process exits
            # during STARTING, even though failure handling is deferred
            if should_read_stderr:
                self._read_and_log_stderr()
        
        if is_deferred:
            return
        
        # Not in STARTING, process asynchronously (not inline) to avoid deadlock
        kwargs = {
            'exit_code': exit_code,
            'elapsed_ms': elapsed_ms,
            'error': error,
        }
        threading.Thread(
            target=self._handle_failure,
            args=(failure_type,),
            kwargs=kwargs,
            daemon=True
        ).start()
    
    def _complete_startup(self) -> None:
        """
        Complete startup sequence and transition to BOOTING.
        
        Per contract [S19.13]: start() MUST force state → BOOTING before returning,
        even if FFmpeg died milliseconds ago.
        
        Per contract [S19.14]: After BOOTING is set, any deferred failures are processed.
        However, they must be processed AFTER start() returns (via async callback) to ensure
        start() always returns with BOOTING state per [S19.13].
        """
        # Force state → BOOTING per [S19.13]
        with self._state_lock:
            self._state = SupervisorState.BOOTING
            self._startup_complete = True
        
        if self._on_state_change:
            self._on_state_change(SupervisorState.BOOTING)
        
        # Process deferred failures asynchronously AFTER start() returns
        # This ensures start() returns with BOOTING state per [S19.13]
        pending_count = 0
        failure_details = None
        with self._pending_failure_lock:
            if self._pending_failures > 0:
                pending_count = self._pending_failures
                failure_details = self._pending_failure_details
                # Clear immediately to prevent reprocessing
                self._pending_failures = 0
                self._pending_failure_details = None
        
        if pending_count > 0 and failure_details is not None:
            failure_type, kwargs = failure_details
            logger.debug(f"Scheduling {pending_count} deferred failure(s) for processing after startup: {failure_type}")
            # Process in a timer with small delay to ensure start() returns with BOOTING state first
            # per contract [S19.13], then process deferred failures asynchronously per [S19.14]
            def process_deferred_failure():
                # Only process if we're still in BOOTING state (not already handled by another path)
                with self._state_lock:
                    current_state = self._state
                if current_state == SupervisorState.BOOTING:
                    self._handle_failure(failure_type, **kwargs)
            # Use a small delay (50ms) to ensure start() returns before processing deferred failures
            # This gives callers time to check the state immediately after start() returns per [S19.13]
            timer = threading.Timer(0.05, process_deferred_failure)
            timer.daemon = True
            timer.start()
    
    def _enter_restarting_or_failed(
        self,
        failure_type: str,
        exit_code: Optional[int] = None,
        elapsed_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Enter RESTARTING or FAILED state based on failure.
        
        This method handles the actual failure processing: logging, state transitions,
        and restart scheduling. It's called from _handle_failure() after validation.
        
        Args:
            failure_type: Type of failure (process_exit, startup_timeout, stall, etc.)
            exit_code: Process exit code (for process_exit)
            elapsed_ms: Elapsed time in ms (for stall/timeout)
            error: Error message (for read_error, etc.)
        """
        # DEBUG observability – you already added this and it's super helpful
        logger.info(
            "FFMPEG_SUPERVISOR: entering _enter_restarting_or_failed "
            f"(failure_type={failure_type}, state={self.get_state().name}, "
            f"first_frame_received={self._first_frame_received}, "
            f"startup_complete={self._startup_complete})"
        )
        
        # Only suppress soft liveness failures during BOOTING
        state = self.get_state()
        if (
            state == SupervisorState.BOOTING
            and not self._first_frame_received
            and failure_type == "stall"
        ):
            logger.info(f"Ignoring {failure_type} during BOOTING before first MP3 frame")
            return
        
        # Per contract [S13.1], [S21.1]: Log specific failure reason with exit code when available
        # Defensively handle MagicMock objects in tests - only log exit_code if it's a valid integer
        exit_code_str = None
        if exit_code is not None and isinstance(exit_code, int):
            exit_code_str = str(exit_code)
        
        if failure_type == "process_exit":
            if exit_code_str is not None:
                logger.error(f"🔥 FFmpeg exited immediately at startup (exit code: {exit_code_str})")
            else:
                logger.error(f"🔥 FFmpeg exited immediately at startup (exit code: unknown - process may have been killed)")
        elif failure_type == "eof":
            # Per contract [S21.1]: Explicitly log exit code for EOF failures
            if exit_code_str is not None:
                logger.error(f"🔥 FFmpeg stdout EOF (exit code: {exit_code_str})")
            else:
                logger.error(f"🔥 FFmpeg stdout EOF (exit code: unknown - process may have been killed or terminated abnormally)")
        elif failure_type == "stdin_broken":
            # Per contract [S21.1]: Explicitly log exit code for stdin broken failures
            if exit_code_str is not None:
                logger.error(f"🔥 FFmpeg stdin broken (exit code: {exit_code_str})")
            else:
                logger.error(f"🔥 FFmpeg stdin broken (exit code: unknown - process may have been killed)")
        elif failure_type == "startup_timeout":
            # Per contract [S7A], [S20]: Log hard timeout exceeded
            logger.error(f"🔥 FFmpeg did not produce first MP3 frame within {STARTUP_TIMEOUT_MS}ms")
            # Observability: Log captured stderr when transitioning from BOOTING to RESTARTING due to timeout
            with self._state_lock:
                if self._state == SupervisorState.BOOTING:
                    logger.error("FFMPEG_SUPERVISOR: last_stderr at BOOTING→RESTARTING (startup_timeout): %s", self.last_stderr or "<empty>")
        elif failure_type == "stall":
            logger.error(f"🔥 FFmpeg stall detected: {elapsed_ms:.0f}ms without frames")
        else:
            # Include exit code in generic failure log if available
            # Defensively handle MagicMock objects - only include exit_code if it's a valid integer
            exit_info = f" (exit code: {exit_code_str})" if exit_code_str is not None else ""
            logger.error(f"🔥 FFmpeg failure: {failure_type}{exit_info}" + (f" ({error})" if error else ""))
        
        # Per contract [S21.1]: Ensure stderr is captured for process exit/EOF failures
        # If stderr thread never started or has already exited, do a one-shot read
        if failure_type in ("eof", "process_exit", "stdin_broken"):
            if self._stderr_thread is None or not self._stderr_thread.is_alive():
                self._read_and_log_stderr()
        
        # Per contract [S13.2]: Transition to RESTARTING
        # Per contract [S13.7]: Set state directly since we already hold the lock.
        # MUST NOT call _set_state() which would also acquire _state_lock (deadlock).
        with self._state_lock:
            old_state = self._state
            # Observability: Log captured stderr when transitioning from BOOTING to RESTARTING
            if old_state == SupervisorState.BOOTING:
                logger.error("FFMPEG_SUPERVISOR: last_stderr at BOOTING→RESTARTING: %s", self.last_stderr or "<empty>")
            self._state = SupervisorState.RESTARTING
            
            # Per contract [S13.5]: Check max restarts
            self._restart_attempts += 1
            entered_failed = False
            if self._restart_attempts > self._max_restarts:
                # Per contract [S13.6]: Enter FAILED state
                logger.error(
                    f"Encoder failed after {self._max_restarts} restart attempts. "
                    "Entering FAILED state."
                )
                old_state = self._state  # RESTARTING -> FAILED
                self._state = SupervisorState.FAILED
                entered_failed = True
        
        # Per contract [S13.7]: State change callbacks SHALL be executed strictly outside the lock
        # to prevent nested deadlocks. Lock is released above, callbacks invoked here.
        if entered_failed:
            logger.debug(f"Supervisor state: {old_state} -> {SupervisorState.FAILED}")
            if self._on_state_change:
                self._on_state_change(SupervisorState.FAILED)
            return
        
        # Per [S13.2] & [S13.9]: ensure RESTARTING event is emitted whenever we newly enter RESTARTING
        if old_state != SupervisorState.RESTARTING:
            logger.debug(f"Supervisor state: {old_state} -> {SupervisorState.RESTARTING}")
            # Notify EncoderManager immediately when entering RESTARTING state
            if self._encoder_manager is not None:
                self._encoder_manager._on_supervisor_restarting()
            if self._on_state_change:
                self._on_state_change(SupervisorState.RESTARTING)
        
        # Per contract [S13.3]: Preserve MP3 buffer contents (do not clear)
        # Buffer is already preserved - we don't clear it here
        # Per contract [S13.3B]: During restart, MP3 output MUST remain continuous —
        # Supervisor restarts MUST NOT stall or block the broadcast loop.
        # Per contract [S13.3C]: Frame delivery MUST continue from existing buffer during restart
        # until new frames arrive. Fallback/silence may be injected upstream if buffer depletes,
        # but output MUST NOT stop.
        # The buffer remains accessible and non-blocking during restart, allowing the broadcast
        # loop to continue consuming frames from the buffer.
        
        # Per contract [S13.4]: Follow exponential backoff schedule
        self._schedule_restart()
    
    def _handle_failure(
        self,
        failure_type: str,
        exit_code: Optional[int] = None,
        elapsed_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Handle encoder failure per contract [S13].
        
        Per contract [S13.7]: This function holds _state_lock and sets state directly
        (does not call _set_state() which would also acquire the lock, causing deadlock).
        State change callbacks are invoked outside the lock.
        
        Args:
            failure_type: Type of failure (process_exit, startup_timeout, stall, frame_interval_violation, etc.)
            exit_code: Process exit code (for process_exit)
            elapsed_ms: Elapsed time in ms (for stall/timeout)
            error: Error message (for read_error, etc.)
        """
        with self._state_lock:
            # Contract [S19.14]: If we're in STARTING state, failure handling MUST be deferred.
            # This ensures start() always returns with state == BOOTING per [S19.13].
            # Note: This check should not be needed if all callers use _on_process_failure(),
            # but we keep it as a safety check.
            if self._state == SupervisorState.STARTING:
                # This should not happen if callers use _on_process_failure() correctly
                # But as a safety measure, defer it here
                with self._pending_failure_lock:
                    self._pending_failures += 1
                    self._pending_failure_details = (failure_type, {
                        'exit_code': exit_code,
                        'elapsed_ms': elapsed_ms,
                        'error': error,
                    })
                logger.debug(f"Safety defer: failure {failure_type} detected during STARTING (should have been deferred earlier)")
                return
            
            # Legacy check: If startup not complete, defer (for backwards compatibility)
            # This is redundant with STARTING check above, but kept for safety
            if not self._startup_complete:
                exit_code_str = None
                if exit_code is not None and isinstance(exit_code, int):
                    exit_code_str = str(exit_code)
                
                if failure_type == "eof":
                    if exit_code_str is not None:
                        logger.error(f"🔥 FFmpeg stdout EOF (exit code: {exit_code_str})")
                    else:
                        logger.error(
                            "🔥 FFmpeg stdout EOF (exit code: unknown - process may have been "
                            "killed or terminated abnormally)"
                        )
                elif failure_type == "process_exit":
                    if exit_code_str is not None:
                        logger.error(
                            f"🔥 FFmpeg exited immediately at startup (exit code: {exit_code_str})"
                        )
                    else:
                        logger.error(
                            "🔥 FFmpeg exited immediately at startup "
                            "(exit code: unknown - process may have been killed)"
                        )
                elif failure_type == "stdin_broken":
                    if exit_code_str is not None:
                        logger.error(f"🔥 FFmpeg stdin broken (exit code: {exit_code_str})")
                    else:
                        logger.error(
                            "🔥 FFmpeg stdin broken (exit code: unknown - process may have been killed)"
                        )
                elif failure_type == "startup_timeout":
                    logger.error(
                        f"🔥 FFmpeg did not produce first MP3 frame within {STARTUP_TIMEOUT_MS}ms"
                    )
                
                # No state transition, no restart scheduling during startup.
                return
            
            if self._state in (SupervisorState.STOPPED, SupervisorState.FAILED):
                return
            
            # PATCH 3: Allow REAL FAILURES to exit BOOTING, but suppress only stall detection
            # Real failures (exit, eof, error, forced_failure) MUST exit BOOTING immediately
            # Stall detection is suppressed during BOOTING to avoid false positives
            state = self._state
            reason = failure_type
            
            # Map failure_type to reason for consistency
            if failure_type == "process_exit":
                reason = "exit"
            elif failure_type in ("read_error", "error"):
                reason = "error"
            
            # Check if we should suppress this failure (only stall during BOOTING)
            if reason == "stall" and state == SupervisorState.BOOTING:
                # Suppress only stall detection during BOOTING
                return  # Suppress only stall detection
            
            # All other failures (including real failures) proceed to failure handling
            # Store state for use after lock is released
            should_handle_failure = True
        
        # Release lock before calling _enter_restarting_or_failed() to avoid deadlock
        # _enter_restarting_or_failed() will acquire its own lock
        if should_handle_failure:
            self._enter_restarting_or_failed(failure_type, exit_code, elapsed_ms, error)
    
    def _schedule_restart(self) -> None:
        """Schedule asynchronous restart with backoff per contract [S13.4]."""
        # Per contract [S31] #3: Restart logic MUST be disabled after shutdown
        if self._restart_disabled:
            logger.debug("Restart disabled (shutdown in progress)")
            return
        
        if self._restart_thread is not None and self._restart_thread.is_alive():
            logger.debug("Restart already in progress")
            return
        
        self._restart_thread = threading.Thread(
            target=self._restart_worker,
            daemon=False,
            name="EncoderRestart"
        )
        self._restart_thread.start()
    
    def _restart_worker(self) -> None:
        """
        Worker function for asynchronous restart per contract [S13.4].
        
        Handles exponential backoff and restart logic.
        """
        # Per contract requirements: Reset state IMMEDIATELY when restart begins,
        # before backoff delay, before stopping old process, before launching new process.
        # This ensures proper state tracking for the new encoder process.
        with self._state_lock:
            # If restart invoked while not RESTARTING (possible in tests),
            # promote state to RESTARTING without callback inside lock.
            if self._state != SupervisorState.RESTARTING:
                self._state = SupervisorState.RESTARTING
                promote = True
            else:
                promote = False
            attempt_num = self._restart_attempts
        
        # Fire RESTARTING callback only if we had to promote (outside lock per S13.7)
        if promote:
            # Notify EncoderManager immediately when entering RESTARTING state
            if self._encoder_manager is not None:
                self._encoder_manager._on_supervisor_restarting()
            if self._on_state_change:
                self._on_state_change(SupervisorState.RESTARTING)
        
        # Reset state to BOOTING and initialize startup tracking IMMEDIATELY
        # This must happen unconditionally for EVERY restart, before any other operations.
        with self._state_lock:
            self._state = SupervisorState.BOOTING
        
        # Set startup deadline: now() + STARTUP_TIMEOUT
        self._startup_time = time.time()  # Use wall-clock time per [S7B]
        
        # Reset liveness tracking to force first-frame logic to restart
        self._first_frame_received = False
        self._first_frame_seen = False  # Reset first frame seen flag per Fix #1
        self._first_frame_time = None
        self._last_frame_time = None
        
        # Reset slow startup warning flag
        self._slow_startup_warn_logged = False
        
        # Reset startup timeout cancellation event
        self._startup_timeout_cancelled.clear()
        
        # Fire BOOTING callback (outside lock per S13.7)
        if self._on_state_change:
            self._on_state_change(SupervisorState.BOOTING)
        
        # Get backoff delay per contract [S13.4]
        backoff_idx = min(attempt_num - 1, len(self._backoff_schedule_ms) - 1)
        delay_ms = self._backoff_schedule_ms[backoff_idx]
        delay_sec = delay_ms / 1000.0
        
        logger.info(
            f"Restarting encoder (attempt {attempt_num}/{self._max_restarts}) "
            f"after {delay_sec:.1f}s delay"
        )
        
        # Wait for backoff delay
        time.sleep(delay_sec)
        
        # Stop old process
        self._stop_encoder_process()
        
        # Reset telemetry flags for restart
        self._debug_first_stdin_logged = False
        self._debug_first_stdout_logged = False
        
        # Per contract [S21.3]: Reset stderr capture for new process
        self._last_stderr = ""
        
        # Per contract F9: Reset stdout accumulator for new process
        self._stdout_accumulator = bytearray()
        
        # Start new encoder process
        self._start_encoder_process()
        
        # Check if process started successfully
        if self._process is None or self._stdout is None:
            # Restart failed - set state to BOOTING and defer failure handling
            # Per contract [S13.8], [S29]: State MUST be BOOTING immediately after spawn attempt
            with self._state_lock:
                self._state = SupervisorState.BOOTING
            callback = self._on_state_change
            if callback:
                callback(SupervisorState.BOOTING)
            
            # Defer the failure handling to ensure state is BOOTING when _restart_worker() returns
            # The failure will be handled asynchronously by monitoring threads
            logger.debug("Restart process spawn failed - deferring failure handling to preserve BOOTING state per [S13.8], [S29]")
            # Schedule failure handling asynchronously to preserve BOOTING state per contract
            def deferred_failure():
                time.sleep(0.01)  # Tiny delay to ensure _restart_worker() returns first
                self._handle_failure("restart_failed")
            threading.Thread(target=deferred_failure, daemon=True, name="DeferredRestartFailure").start()
            return
        
        # Per contract [S19.16]: Drain threads MUST start BEFORE first PCM write (boot priming)
        # Per contract F9.1: FFmpeg handles MP3 packetization, no packetizer needed
        # Per contract [S13.3]: Do NOT clear _mp3_buffer - preserve buffer contents
        
        # Start new threads BEFORE setting state to BOOTING (which triggers boot priming via callback)
        # Per contract [S14.7]: stdout drain thread MUST start before or concurrently with stderr drain.
        # Stopping either thread MUST NOT block process termination.
        if self._stdout is not None:
            self._stdout_thread = threading.Thread(
                target=self._stdout_drain,
                daemon=True,  # Per contract [S14.7]: Non-blocking termination
                name="FFmpegStdoutDrain"
            )
            self._stdout_thread.start()
            logger.info("Encoder stdout drain thread started")
        
        if self._stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._stderr_drain,
                daemon=True,  # Per contract [S14.7]: Non-blocking termination
                name="FFmpegStderrDrain"
            )
            self._stderr_thread.start()
            logger.info("Encoder stderr drain thread started")
        
        # Ensure PCM writer thread is running (restart if needed)
        # The writer thread should continue running through restarts, but restart it if it died
        if self._writer_thread is None or not self._writer_thread.is_alive():
            self._stop_event.clear()  # Clear stop event for new writer thread
            self._writer_thread = threading.Thread(
                target=self._pcm_writer_loop,
                name="FFMPEG_PCM_WRITER",
                daemon=True
            )
            self._writer_thread.start()
            logger.info("Encoder PCM writer thread started (restart)")
        
        # Per contract [S13.8], [S29]: IMMEDIATELY set state to BOOTING after process spawn and drain threads start
        # This must happen synchronously so that tests checking state immediately after _restart_worker() returns will see BOOTING (not RESTARTING).
        # Even if the process fails immediately, state MUST be BOOTING first per [S13.8], [S29]
        # Use explicit state transition to ensure RESTARTING → BOOTING is visible to observers
        # Per contract [S13R]: On restart, FFmpegSupervisor MUST transition states in order:
        # RUNNING → RESTARTING → BOOTING → RUNNING
        # This sequence is encapsulated and observable to EncoderManager via callback
        # CRITICAL: State must be set AFTER drain threads start so that first PCM write happens after drain threads per [S19.16]
        with self._state_lock:
            old = self._state
            self._state = SupervisorState.BOOTING
        callback = self._on_state_change
        
        # fire callback outside lock
        # Per contract [S13.8A]: BOOTING must be observable even if we're already in BOOTING
        # Always fire the callback to ensure the state transition is observable to tests
        if callback:
            callback(SupervisorState.BOOTING)
        
        # Per contract [S7.4]: PCM cadence is driven by AudioPump, not Supervisor
        # No silence feed loop - Supervisor only writes what it receives via write_pcm()
        self._last_write_ts = None  # Reset write tracking for new process (used for telemetry)
        
        # Removed boot priming burst per residue sweep.
        # Per contract [S7.0B], [A7], [M12]: EncoderManager provides continuous PCM via AudioPump.
        # Supervisor does not generate or inject PCM - it only writes what it receives.
        
        # Restart startup timeout monitor per contract [S19] step 7
        # Note: _startup_time and _slow_startup_warn_logged are already set at the start of _restart_worker()
        # per contract requirements to ensure proper state tracking from the beginning of restart
        # Clear startup timeout cancellation event for new timeout monitoring
        self._startup_timeout_cancelled.clear()
        self._startup_timeout_thread = threading.Thread(
            target=self._monitor_startup_timeout,
            daemon=True,
            name="StartupTimeoutMonitor"
        )
        self._startup_timeout_thread.start()
        
        # Reset restart attempts on successful restart
        with self._state_lock:
            self._restart_attempts = 0
        
        # Ensure BOOTING is observable at the end of restart per [S13.8]:
        # RESTARTING → BOOTING must appear in the state sequence for each
        # new encoder process.
        self._force_booting(tag="restart post-threads [S13.8]")
        
        logger.info(
            "Encoder restarted successfully (in BOOTING state, waiting for first frame per [S13.8])"
        )
    
    def _stop_encoder_process(self) -> None:
        """Stop encoder process and threads."""
        # Signal shutdown
        self._shutdown_event.set()
        
        # Cancel startup timeout thread to prevent it from blocking during join
        self._startup_timeout_cancelled.set()
        
        # CRITICAL: Close file descriptors BEFORE joining threads to unblock blocking I/O operations
        # Threads blocked in readline()/read() will not exit until the file descriptors are closed
        
        # Close stdout and stderr first to unblock drain threads
        if self._stdout is not None:
            try:
                self._stdout.close()
            except Exception:
                pass
            self._stdout = None
        
        if self._stderr is not None:
            try:
                self._stderr.close()
            except Exception:
                pass
            self._stderr = None
        
        # Close stdin to stop writer thread
        if self._stdin is not None:
            try:
                self._stdin.close()
            except Exception:
                pass
            self._stdin = None
        
        # Now join threads (they should exit quickly after FDs are closed)
        if self._stdout_thread is not None and self._stdout_thread.is_alive():
            self._stdout_thread.join(timeout=1.0)
        
        if self._stderr_thread is not None and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1.0)
        
        if self._startup_timeout_thread is not None and self._startup_timeout_thread.is_alive():
            self._startup_timeout_thread.join(timeout=0.5)
        
        if self._writer_thread is not None and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=1.0)
        
        # Terminate process
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except Exception:
                try:
                    self._process.kill()
                    self._process.wait()
                except Exception:
                    pass
            self._process = None
        
        # Clear buffers and thread references to prevent memory leaks
        self._stdout_accumulator = bytearray()
        self._last_stderr = ""
        self._writer_thread = None
        self._stdout_thread = None
        self._stderr_thread = None
        self._startup_timeout_thread = None
        
        # Clear shutdown event for next start
        self._shutdown_event.clear()
    
    def _read_and_log_stderr(self) -> None:
        """
        Read and log all available stderr output per contract [S21].
        
        Called when process exits to capture error messages that may not have been
        captured by the stderr drain thread (e.g., if process exits very quickly).
        Read all available stderr data.
        
        Per contract [S21.2]: Defensively handle cases where stderr data is not
        a plain string (e.g., unittest mocks). Logs MUST degrade gracefully without
        logging MagicMock representations.
        """
        if self._stderr is None:
            return
        
        # Production-safe, contract-legal, test-neutral: Use duck-typing + capability checks
        # If stderr doesn't have a read method, it's not a real file descriptor - skip
        if not hasattr(self._stderr, "read"):
            logger.debug("Stderr does not have read() method - skipping read")
            return
        
        try:
            # Read all available stderr data
            err_chunks = []
            while True:
                chunk = None
                try:
                    chunk = self._stderr.read(4096)
                except (AttributeError, TypeError, OSError, ValueError):
                    # If stderr behaves non-pipe-like (e.g., mock objects, closed pipes, etc.),
                    # bail safely. Other exceptions indicate the object isn't a real pipe.
                    return
                except Exception:
                    # Catch any other unexpected exceptions and bail safely
                    # This prevents deadlocks from mock objects or other non-pipe-like behavior
                    return
                
                # Per contract [S21.2]: Only process bytes/bytearray data
                # If chunk is not bytes/bytearray (e.g., MagicMock, None, etc.), skip it
                if not isinstance(chunk, (bytes, bytearray)):
                    # Not bytes - treat as invalid/closed and exit
                    return
                
                if not chunk:
                    # EOF - no more data available
                    break
                
                err_chunks.append(chunk)
            
            if err_chunks:
                try:
                    err = b''.join(err_chunks).decode(errors='ignore')
                    # Per contract [S21.2]: Only log if decoded result is actually a string
                    # (not a mock object in tests)
                    if isinstance(err, str) and err.strip():  # Only log if there's actual content
                        logger.error("FFmpeg stderr at exit:\n" + err)
                        # Per contract [S21.3]: Capture stderr for exposure
                        # Limit size to prevent memory leaks
                        if len(self._last_stderr) + len(err) > self._last_stderr_max_size:
                            # Keep only the most recent data (truncate from beginning)
                            excess = len(self._last_stderr) + len(err) - self._last_stderr_max_size
                            self._last_stderr = self._last_stderr[excess:]
                        self._last_stderr += err
                except (AttributeError, TypeError):
                    # In tests, decode() or join() might return a mock object - skip logging
                    # This prevents test noise from MagicMock string representations per [S21.2]
                    logger.debug("Stderr data is not a plain string (likely test mock) - skipping log per [S21.2]")
            else:
                logger.debug("No stderr output available at process exit")
        except Exception as e:
            # Per contract [S21.2]: Defensively handle exceptions from mock objects
            # Only log if error message is actually a string (not a MagicMock representation)
            try:
                error_str = str(e)
                # Check if error_str is actually a string and doesn't contain MagicMock representations
                if isinstance(error_str, str) and "MagicMock" not in error_str and "<MagicMock" not in error_str:
                    logger.error(f"Failed to read FFmpeg stderr: {error_str}", exc_info=True)
                else:
                    # Don't log MagicMock representations per [S21.2]
                    logger.debug("Failed to read FFmpeg stderr (likely test mock) - skipping log per [S21.2]")
            except Exception:
                # If str(e) itself fails (e.g., e is a MagicMock), skip logging per [S21.2]
                logger.debug("Failed to read FFmpeg stderr (likely test mock) - skipping log per [S21.2]")


                # If str(e) itself fails (e.g., e is a MagicMock), skip logging per [S21.2]
                logger.debug("Failed to read FFmpeg stderr (likely test mock) - skipping log per [S21.2]")

