"""
Encoder manager for Tower encoding subsystem.

This module provides EncoderManager, which manages the FFmpeg encoder
process lifecycle, handles restarts, and coordinates the drain thread
and buffers.
"""

from __future__ import annotations

import enum
import logging
import os
import select
import subprocess
import threading
import time
from typing import BinaryIO, Callable, List, Optional

from tower.audio.mp3_packetizer import MP3Packetizer
from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.ffmpeg_supervisor import FFmpegSupervisor, SupervisorState

logger = logging.getLogger(__name__)


class EncoderState(enum.Enum):
    """Encoder state enumeration."""
    RUNNING = 1
    RESTARTING = 2
    FAILED = 3
    STOPPED = 4
    
    @classmethod
    def from_supervisor_state(cls, state: SupervisorState) -> EncoderState:
        """Convert SupervisorState to EncoderState."""
        mapping = {
            SupervisorState.STARTING: cls.RUNNING,  # STARTING is treated as RUNNING for compatibility
            SupervisorState.BOOTING: cls.RUNNING,  # BOOTING is treated as RUNNING (encoder is active, waiting for first frame)
            SupervisorState.RUNNING: cls.RUNNING,
            SupervisorState.RESTARTING: cls.RESTARTING,
            SupervisorState.FAILED: cls.FAILED,
            SupervisorState.STOPPED: cls.STOPPED,
        }
        return mapping.get(state, cls.STOPPED)


# FFmpeg command construction is handled by FFmpegSupervisor
# See tower.encoder.ffmpeg_supervisor.DEFAULT_FFMPEG_CMD


class EncoderManager:
    """
    Manages FFmpeg encoder process lifecycle.
    
    Coordinates encoder process, drain thread, packetizer, and buffers.
    Handles encoder restarts with exponential backoff. Maintains state
    and ensures non-blocking operations throughout.
    
    Attributes:
        pcm_buffer: FrameRingBuffer for PCM input frames
        mp3_buffer: FrameRingBuffer for MP3 output frames (via property)
        state: Current encoder state
        
    Internal fields (for get_frame() fallback logic):
        _silence_frame: Prebuilt minimal valid MP3 frame that decodes as silence
        _last_frame: Last known good frame (for cheap "silence-ish" placeholder)
        _mp3_underflow_count: Counter for MP3-layer underflow events
    """
    
    class EncoderOutputDrainThread(threading.Thread):
        """
        Dedicated thread that continuously drains encoder stdout.
        
        Reads MP3 bytes from FFmpeg stdout using select() with 0.25s timeout,
        feeds them to MP3Packetizer, and pushes complete frames to the MP3 buffer.
        Detects stalls when no data is received for stall_threshold_ms.
        On encoder exit (EOF) or errors, triggers restart path.
        
        Never blocks the output side waiting for data. Only emits complete frames.
        
        Attributes:
            stdout: FFmpeg stdout pipe (BinaryIO)
            mp3_buffer: FrameRingBuffer to push complete frames to
            packetizer: MP3Packetizer instance
            stall_threshold_ms: Stall detection threshold in milliseconds
            on_stall_detected: Callback when stall is detected or encoder exits
            on_drain_error: Callback when drain thread encounters an error
            shutdown_event: Event to signal thread shutdown
        """
        
        # Select timeout: 0.25s (250ms) for efficient polling
        SELECT_TIMEOUT_SEC = 0.25
        
        # Read size: ~1KB per poll (small chunks for responsive processing)
        READ_SIZE = 1024
        
        def __init__(
            self,
            stdout: BinaryIO,
            mp3_buffer: FrameRingBuffer,
            packetizer: MP3Packetizer,
            stall_threshold_ms: int,
            on_stall_detected: Callable[[], None],
            on_drain_error: Callable[[Exception], None],
            shutdown_event: threading.Event,
        ) -> None:
            """
            Initialize drain thread.
            
            Args:
                stdout: FFmpeg stdout pipe (must be readable)
                mp3_buffer: FrameRingBuffer to push complete frames to (non-blocking drop-oldest)
                packetizer: MP3Packetizer instance (only emits complete frames)
                stall_threshold_ms: Stall detection threshold in milliseconds
                on_stall_detected: Callback when stall is detected or encoder exits
                on_drain_error: Callback when drain thread encounters an error
                shutdown_event: Event to signal thread shutdown
            """
            super().__init__(name="EncoderOutputDrain", daemon=True)
            self.stdout = stdout
            self.mp3_buffer = mp3_buffer
            self.packetizer = packetizer
            self.stall_threshold_ms = stall_threshold_ms
            self.on_stall_detected = on_stall_detected
            self.on_drain_error = on_drain_error
            self.shutdown_event = shutdown_event
            
            self._last_data_time: Optional[float] = None
        
        def run(self) -> None:
            """
            Main drain loop - continuously reads streaming bytes in tight loop.
            
            Reads small chunks (1024 bytes) continuously from stdout, feeds to
            packetizer, and pushes complete frames to buffer. Detects EOF and stalls.
            """
            logger.info("Encoder stdout drain thread running")
            
            # Track last log time for 1-second interval logging
            last_log_time = time.monotonic()
            
            try:
                while not self.shutdown_event.is_set():
                    # Read using read() in tight loop (stdout is set to non-blocking)
                    try:
                        data = self.stdout.read(4096)  # read() is non-blocking when fd is set to non-blocking
                    except BlockingIOError:
                        # No data available yet - small sleep to avoid tight CPU loop
                        time.sleep(0.001)  # 1ms sleep to prevent CPU spinning
                        continue
                    except (OSError, ValueError) as e:
                        logger.warning(f"Read error in drain thread: {e}")
                        self.on_drain_error(e)
                        break
                    
                    if not data:
                        # EOF - encoder process ended
                        logger.warning("Encoder stdout EOF - encoder process ended")
                        self.on_stall_detected()
                        break
                    
                    # Store actual MP3 data
                    logger.debug(f"[ENC-OUT] {len(data)} bytes from ffmpeg")
                    
                    # Feed bytes to packetizer and get complete frames only
                    # feed() returns an Iterator[bytes]
                    for frame in self.packetizer.feed(data):
                        logger.debug(f"mp3-frame: {len(frame)} bytes")
                        # Push complete frames to buffer (non-blocking, drop-oldest if full)
                        self.mp3_buffer.push_frame(frame)
                        # Log ring buffer state
                        stats = self.mp3_buffer.stats()
                        logger.debug(f"mp3->buffer count={stats.count}/{stats.capacity}")  # Per contract [B20]
                    
                    # Update last data timestamp
                    self._last_data_time = time.monotonic()
                    
                    # Log buffer size every 1 second
                    now = time.monotonic()
                    if now - last_log_time >= 1.0:
                        stats = self.mp3_buffer.stats()
                        logger.info(f"MP3 output buffer: {stats.count} frames")  # Per contract [B20]
                        last_log_time = now
                    
                    # Check for stall (only if we've received data before)
                    if self._last_data_time is not None:
                        elapsed_ms = (now - self._last_data_time) * 1000.0
                        
                        if elapsed_ms >= self.stall_threshold_ms:
                            logger.warning(
                                f"Encoder stall detected: {elapsed_ms:.0f}ms without data "
                                f"(threshold: {self.stall_threshold_ms}ms)"
                            )
                            self.on_stall_detected()
                            break
            except Exception as e:
                logger.error(f"Unexpected error in drain thread: {e}", exc_info=True)
                self.on_drain_error(e)
            finally:
                logger.debug("Encoder output drain thread stopped")
        
        def stop(self, timeout: float = 2.0) -> None:
            """
            Stop drain thread.
            
            Args:
                timeout: Maximum time to wait for thread to stop
            """
            self.shutdown_event.set()
            if self.is_alive():
                self.join(timeout=timeout)
                if self.is_alive():
                    logger.warning("Drain thread did not stop within timeout")
    
    def __init__(
        self,
        pcm_buffer: FrameRingBuffer,
        mp3_buffer: Optional[FrameRingBuffer] = None,
        stall_threshold_ms: Optional[int] = None,
        backoff_schedule_ms: Optional[List[int]] = None,
        max_restarts: Optional[int] = None,
        ffmpeg_cmd: List[str] = None,
        bitrate_kbps: int = 128,
        sample_rate: int = 48000,
        encoder_enabled: Optional[bool] = None,
        allow_ffmpeg: bool = False,
    ) -> None:
        """
        Initialize encoder manager.
        
        Args:
            pcm_buffer: FrameRingBuffer for PCM input frames
            mp3_buffer: Optional FrameRingBuffer for MP3 output frames
                       If None, creates one from TOWER_MP3_BUFFER_CAPACITY_FRAMES (default: 400)
            stall_threshold_ms: Optional stall detection threshold in milliseconds
                               If None, reads from TOWER_ENCODER_STALL_THRESHOLD_MS (default: 2000)
            backoff_schedule_ms: Optional restart backoff delays in milliseconds
                               If None, reads from TOWER_ENCODER_BACKOFF_MS (default: [1000,2000,4000,8000,10000])
            max_restarts: Optional maximum restart attempts before FAILED state
                        If None, reads from TOWER_ENCODER_MAX_RESTARTS (default: 5)
            ffmpeg_cmd: Optional FFmpeg command (default: None, uses FFmpegSupervisor default)
            bitrate_kbps: Expected MP3 bitrate in kbps (for silence frame generation)
            sample_rate: Expected MP3 sample rate in Hz (for silence frame generation)
            encoder_enabled: Optional flag to enable/disable encoder (default: None, reads from TOWER_ENCODER_ENABLED)
                            If False or TOWER_ENCODER_ENABLED=0, operates in OFFLINE_TEST_MODE [O6]
            allow_ffmpeg: Whether FFmpeg startup is allowed (default: False for test safety per [I25])
                         In production, set to True. In tests, set to False unless explicitly testing FFmpeg.
        """
        self._allow_ffmpeg = allow_ffmpeg
        self.pcm_buffer = pcm_buffer
        
        # Create or use provided MP3 buffer
        if mp3_buffer is None:
            # 200 frames ≈ ~8s buffer at 128kbps
            mp3_buffer_capacity = int(os.getenv("TOWER_MP3_BUFFER_CAPACITY_FRAMES", "200"))
            self._mp3_buffer = FrameRingBuffer(capacity=mp3_buffer_capacity)
        else:
            self._mp3_buffer = mp3_buffer
        
        # Read configuration from environment if not provided
        if stall_threshold_ms is None:
            stall_threshold_ms = int(os.getenv("TOWER_ENCODER_STALL_THRESHOLD_MS", "2000"))
        
        if backoff_schedule_ms is None:
            backoff_str = os.getenv("TOWER_ENCODER_BACKOFF_MS", "1000,2000,4000,8000,10000")
            try:
                backoff_schedule_ms = [int(x.strip()) for x in backoff_str.split(",")]
            except ValueError:
                backoff_schedule_ms = [1000, 2000, 4000, 8000, 10000]
        
        if max_restarts is None:
            max_restarts = int(os.getenv("TOWER_ENCODER_MAX_RESTARTS", "5"))
        
        self.stall_threshold_ms = stall_threshold_ms
        self.backoff_schedule_ms = backoff_schedule_ms
        self.max_restarts = max_restarts
        # FFmpeg command is constructed by FFmpegSupervisor (pass None to use default)
        self.ffmpeg_cmd = ffmpeg_cmd
        
        # Store bitrate/sample_rate for silence frame generation
        self._bitrate_kbps = bitrate_kbps
        self._sample_rate = sample_rate
        
        # Check if encoder is enabled (per contract [M17], [O6], [I19])
        # If encoder_enabled is explicitly False or TOWER_ENCODER_ENABLED=0, operate in OFFLINE_TEST_MODE
        if encoder_enabled is None:
            encoder_enabled_str = os.getenv("TOWER_ENCODER_ENABLED", "1")
            encoder_enabled = encoder_enabled_str not in ("0", "false", "False", "FALSE")
        self._encoder_enabled = encoder_enabled
        
        # MP3Packetizer will be created on encoder start (parses from headers)
        # Only created if encoder is enabled
        self.packetizer: Optional[MP3Packetizer] = None
        
        # Prebuilt silence MP3 frame for underflow fallback
        # This is a minimal valid MP3 frame that decodes as silence
        # Separate from PCM-level tone fallback (handled by AudioPump/FallbackGenerator)
        self._silence_frame: bytes = self._create_silence_frame()
        
        # Last known good frame (for cheap "silence-ish" placeholder during underflow)
        # Updated whenever we successfully pop a frame from buffer
        self._last_frame: Optional[bytes] = None
        
        # Track if we've received the first real MP3 frame (for startup behavior)
        self._has_received_first_frame = False
        
        # Underflow counter (tracks MP3-layer underflow events)
        self._mp3_underflow_count = 0
        
        # State management
        self._state = EncoderState.STOPPED
        self._state_lock = threading.Lock()
        self._restart_attempts = 0
        self._shutdown = False
        
        # PCM fallback injection per contract [M19]-[M24]
        # Grace period configuration (default 1500ms per [M21])
        self._grace_period_ms = int(os.getenv("TOWER_PCM_GRACE_PERIOD_MS", "1500"))
        self._fallback_use_tone = os.getenv("TOWER_PCM_FALLBACK_TONE", "0") not in ("0", "false", "False", "FALSE")
        self._fallback_thread: Optional[threading.Thread] = None
        self._fallback_running = False
        self._fallback_grace_timer_start: Optional[float] = None
        # Silence frame for PCM fallback (4608 bytes: 1152 samples × 2 channels × 2 bytes)
        self._pcm_silence_frame = b'\x00' * 4608
        # Fallback generator for tone (lazy import to avoid circular dependency)
        self._fallback_generator: Optional[object] = None
        
        # FFmpeg Supervisor (delegates all process lifecycle management)
        self._supervisor: Optional[FFmpegSupervisor] = None
        
        # Legacy process references (for backwards compatibility with tests)
        self._process: Optional[subprocess.Popen] = None
        self._stdin: Optional[BinaryIO] = None
        self._stdout: Optional[BinaryIO] = None
        self._stderr: Optional[BinaryIO] = None
        
        # Legacy thread references (for backwards compatibility)
        self._drain_thread: Optional[EncoderManager.EncoderOutputDrainThread] = None
        self._drain_shutdown = threading.Event()
        self._stderr_thread: Optional[threading.Thread] = None
        self._restart_thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        """
        Start encoder process via FFmpegSupervisor.
        
        Delegates all process lifecycle management to supervisor.
        Per contract [M17], if encoder is disabled (OFFLINE_TEST_MODE [O6]),
        supervisor is not created or started.
        """
        with self._state_lock:
            if self._state != EncoderState.STOPPED:
                raise RuntimeError(f"Cannot start encoder in state: {self._state}")
        
        # Per contract [M17], OFFLINE_TEST_MODE [O6] bypasses supervisor creation entirely
        if not self._encoder_enabled:
            logger.info("Encoder disabled (OFFLINE_TEST_MODE [O6]) - supervisor not created")
            # In OFFLINE_TEST_MODE, get_frame() returns synthetic frames
            # State remains STOPPED (maps to COLD_START [O1] or OFFLINE_TEST_MODE [O6])
            return
        
        # Create supervisor
        self._supervisor = FFmpegSupervisor(
            mp3_buffer=self._mp3_buffer,
            ffmpeg_cmd=self.ffmpeg_cmd,
            stall_threshold_ms=self.stall_threshold_ms,
            backoff_schedule_ms=self.backoff_schedule_ms,
            max_restarts=self.max_restarts,
            on_state_change=self._on_supervisor_state_change,
            allow_ffmpeg=self._allow_ffmpeg,
        )
        
        # Start supervisor (handles all startup sequence per contract)
        self._supervisor.start()
        
        # Update legacy references for backwards compatibility
        # (Some tests may access these directly)
        if self._supervisor._process:
            self._process = self._supervisor._process
            self._stdin = self._supervisor.get_stdin()
            self._stdout = self._supervisor._stdout
            self._stderr = self._supervisor._stderr
            self._stderr_thread = self._supervisor._stderr_thread
            self._drain_thread = self._supervisor._stdout_thread  # Map stdout thread to drain_thread
        
        # Update state from supervisor
        supervisor_state = self._supervisor.get_state()
        with self._state_lock:
            self._state = EncoderState.from_supervisor_state(supervisor_state)
        
        # Per contract [M19]-[M24]: Start fallback injection if in BOOTING, RESTART_RECOVERY, or DEGRADED
        if supervisor_state in (SupervisorState.BOOTING, SupervisorState.RESTARTING, SupervisorState.FAILED):
            self._start_fallback_injection()
        
        logger.info("EncoderManager started")
    
    def _on_supervisor_state_change(self, new_state: SupervisorState) -> None:
        """Callback when supervisor state changes."""
        with self._state_lock:
            old_state = self._state
            self._state = EncoderState.from_supervisor_state(new_state)
        
        # Per contract [M19]-[M24]: Manage fallback injection based on state
        # Start fallback injection during BOOTING, RESTART_RECOVERY, DEGRADED
        # Stop fallback injection when transitioning to RUNNING
        if new_state in (SupervisorState.BOOTING, SupervisorState.RESTARTING, SupervisorState.FAILED):
            self._start_fallback_injection()
        elif new_state == SupervisorState.RUNNING:
            self._stop_fallback_injection()
    
    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop encoder process via supervisor.
        
        Args:
            timeout: Maximum time to wait for cleanup
        """
        logger.info("Stopping EncoderManager...")
        
        self._shutdown = True
        
        # Stop supervisor (handles all cleanup)
        if self._supervisor is not None:
            self._supervisor.stop(timeout=timeout)
            self._supervisor = None
        
        with self._state_lock:
            self._state = EncoderState.STOPPED
        
        # Stop fallback injection thread per contract [M19]-[M24]
        self._stop_fallback_injection()
        
        # Clear legacy references
        self._process = None
        self._stdin = None
        self._stdout = None
        self._stderr = None
        self._drain_thread = None
        self._stderr_thread = None
        self._restart_thread = None
        
        logger.info("EncoderManager stopped")
    
    def write_pcm(self, frame: bytes) -> None:
        """
        Write PCM frame to encoder stdin (non-blocking).
        
        Forwards to supervisor's write_pcm() method per contract [M8].
        Per contract [M16], only delivers PCM during LIVE_INPUT [O3].
        During BOOTING, RESTART_RECOVERY, FALLBACK, and DEGRADED, silence/tone generation is used instead.
        Supervisor handles process liveness checks and error handling.
        Never blocks.
        
        Args:
            frame: PCM frame bytes to write
        """
        # Per contract [M16], write_pcm() only delivers PCM during LIVE_INPUT [O3]
        # Check supervisor state to determine if we're in LIVE_INPUT mode
        if self._supervisor is None:
            return
        
        supervisor_state = self._supervisor.get_state()
        
        # Per contract [M12], operational mode mapping:
        # - RUNNING → LIVE_INPUT [O3] (only mode where live PCM is forwarded)
        # - BOOTING → BOOTING [O2] (silence/tone generation used instead)
        # - RESTARTING → RESTART_RECOVERY [O5] (silence/tone generation used instead)
        # - FAILED → DEGRADED [O7] (silence/tone generation used instead)
        # - STOPPED/STARTING → COLD_START [O1] (no supervisor, returns early above)
        #
        # Per contract [M16], only deliver PCM during LIVE_INPUT [O3] (SupervisorState.RUNNING)
        # During BOOTING, RESTART_RECOVERY, FALLBACK, and DEGRADED, silence/tone generation is used
        # Per contract [S7.1], silence frames are fed during BOOTING, but that's handled by AudioPump/FallbackGenerator
        # This method only forwards live PCM during LIVE_INPUT
        if supervisor_state != SupervisorState.RUNNING:
            return
        
        # Forward to supervisor's write_pcm() method per contract [M8]
        # Supervisor.write_pcm() handles:
        # - Process liveness check (process.poll())
        # - Non-blocking write to stdin
        # - BrokenPipeError handling (triggers restart)
        self._supervisor.write_pcm(frame)
    
    def get_frame(self) -> Optional[bytes]:
        """
        Get MP3 frame for broadcast (non-blocking).
        
        Per contract [M15], applies source selection rules defined in [O13] and [O14].
        Priority order per [O13]:
        1. Real MP3 frames from encoder (LIVE_INPUT mode)
        2. Prebuilt silence MP3 frames (FALLBACK, BOOTING, RESTART_RECOVERY, DEGRADED)
        3. Tone-generated MP3 frames (if configured, FALLBACK mode)
        4. Synthetic MP3 frames (OFFLINE_TEST_MODE)
        
        Per contract [M10]: MUST NEVER BLOCK and SHOULD avoid returning None.
        For broadcast-grade systems: MUST NEVER return None. If no MP3 is available, MUST return silence.
        
        Called by the tick-driven broadcast loop every TOWER_OUTPUT_TICK_INTERVAL_MS.
        
        Returns:
            bytes: MP3 frame (always returns bytes, never None per [M10])
        """
        # Per contract [M17], OFFLINE_TEST_MODE [O6] returns synthetic frames
        if not self._encoder_enabled:
            # Return synthetic silence frame for OFFLINE_TEST_MODE
            return self._silence_frame
        
        # Determine current operational mode from supervisor state
        if self._supervisor is None:
            # COLD_START [O1] - no encoder process yet
            # Per [O1], get_frame() may return None or prebuilt silence frames
            return self._silence_frame  # Return silence to keep broadcast alive per [O2.1]
        
        supervisor_state = self._supervisor.get_state()
        
        # Per contract [M12], EncoderManager state tracks SupervisorState but resolves externally as Operational Modes:
        # - STOPPED/STARTING → COLD_START [O1]
        # - BOOTING → BOOTING [O2] until first MP3 frame received
        # - RUNNING → LIVE_INPUT [O3]
        # - RESTARTING → RESTART_RECOVERY [O5]
        # - FAILED → DEGRADED [O7]
        #
        # Per contract [O14], mode-aware frame selection:
        # - [O3] LIVE_INPUT: Return frames from MP3 buffer (encoder output)
        # - [O2] BOOTING: Return prebuilt silence frames
        # - [O4] FALLBACK: Return prebuilt silence or tone frames
        # - [O5] RESTART_RECOVERY: Return prebuilt silence frames
        # - [O7] DEGRADED: Return prebuilt silence or tone frames
        
        if supervisor_state == SupervisorState.RUNNING:
            # [O3] LIVE_INPUT mode - try to get real MP3 frames from encoder
            frame = self._mp3_buffer.pop_frame()
            
            if frame is not None:
                # Successfully got a frame - mark that we've received first frame
                self._has_received_first_frame = True
                self._last_frame = frame
                return frame
            
            # Buffer empty: MP3-layer underflow during LIVE_INPUT
            # Per [O13], fallback to last known good frame or silence
            self._mp3_underflow_count += 1
            
            if self._last_frame is not None:
                logger.debug(
                    f"MP3 buffer underflow (count: {self._mp3_underflow_count}), "
                    "returning last known good frame"
                )
                return self._last_frame
            
            # Last resort: Return static silence frame
            logger.debug(
                f"MP3 buffer underflow (count: {self._mp3_underflow_count}), "
                "no last frame available, returning silence frame"
            )
            return self._silence_frame
        
        elif supervisor_state == SupervisorState.BOOTING:
            # [O2] BOOTING mode - return prebuilt silence frames per [O14]
            # Per [O2.1], broadcast must begin instantly, never wait for encoder
            return self._silence_frame
        
        elif supervisor_state in (SupervisorState.RESTARTING, SupervisorState.FAILED):
            # [O5] RESTART_RECOVERY or [O7] DEGRADED - return prebuilt silence frames per [O14]
            return self._silence_frame
        
        elif supervisor_state in (SupervisorState.STOPPED, SupervisorState.STARTING):
            # [O1] COLD_START - return prebuilt silence frames per [O1], [O2.1]
            return self._silence_frame
        
        # Fallback: return silence frame
        return self._silence_frame
    
    def pop(self) -> Optional[bytes]:
        """
        Alias for get_frame() to support frame_source interface.
        
        This allows EncoderManager to be used as a frame_source for HTTPServer
        which expects a .pop() method.
        
        Returns:
            Optional[bytes]: MP3 frame if available, None otherwise
        """
        return self.get_frame()
    
    @property
    def mp3_buffer(self) -> FrameRingBuffer:
        """
        Get the MP3 output buffer (for backwards compatibility).
        
        Returns:
            FrameRingBuffer instance
        """
        return self._mp3_buffer
    
    def _create_silence_frame(self) -> bytes:
        """
        Create a minimal valid MP3 silence frame.
        
        This is a static prebuilt frame that decodes as silence. It's used as
        a last resort when the buffer is empty and no last frame is available.
        
        For now, this is a tiny static bytes literal. It can be improved later
        (e.g., generate via FFmpeg or use a more sophisticated approach).
        
        Returns:
            bytes: Minimal valid MP3 frame that decodes as silence
        """
        # Compute expected frame size for current encoder settings
        # Formula: frame_size = 144 * bitrate / sample_rate + padding
        # For 128kbps @ 48kHz: 144 * 128000 / 48000 = 384 bytes (no padding)
        bitrate_bps = self._bitrate_kbps * 1000
        frame_size = int((144 * bitrate_bps) / self._sample_rate)
        
        # Create minimal valid MP3 frame header for MPEG-1 Layer III
        # Byte 0: 0xFF (sync)
        # Byte 1: 0xFB (MPEG-1 Layer III, no CRC) - 0xFB & 0xE0 == 0xE0 ✓
        # Byte 2: Bitrate index 9 (128kbps) = 1001, Sample rate 1 (48kHz) = 01, Padding 0 = 0
        #         = 1001 0100 = 0x94
        # Byte 3: Channel mode, etc. = 0x00
        header = bytes([
            0xFF,  # Sync byte 1
            0xFB,  # Sync byte 2 (MPEG-1 Layer III, no CRC)
            0x94,  # Bitrate 128kbps, Sample rate 48kHz, No padding
            0x00   # Channel mode, etc.
        ])
        
        # Fill rest with zeros (silence payload)
        payload_size = max(0, frame_size - len(header))
        payload = b'\x00' * payload_size
        
        return header + payload
    
    def get_silence_mp3_frame(self) -> bytes:
        """
        Get a silence MP3 frame (backwards compatibility).
        
        Returns the prebuilt silence frame. This method is kept for backwards
        compatibility. Use get_frame() for new code.
        
        Returns:
            bytes: Silence MP3 frame
        """
        return self._silence_frame
    
    def _start_fallback_injection(self) -> None:
        """
        Start PCM fallback injection thread per contract [M19]-[M24].
        
        Injects PCM data during BOOTING, RESTART_RECOVERY, and DEGRADED states
        even when no live PCM input exists.
        
        Per contract [M24A]: Does not start in OFFLINE_TEST_MODE [O6].
        """
        # Per contract [M24A]: [M19]-[M24] do not apply in OFFLINE_TEST_MODE [O6]
        if not self._encoder_enabled:
            return
        
        if self._fallback_running:
            return
        
        self._fallback_running = True
        self._fallback_grace_timer_start = time.monotonic()  # Per [M20], [M21]: Start grace period
        
        # Lazy import to avoid circular dependency
        if self._fallback_generator is None:
            try:
                from tower.fallback.generator import FallbackGenerator
                self._fallback_generator = FallbackGenerator()
            except Exception as e:
                logger.warning(f"Failed to initialize FallbackGenerator: {e}, using silence only")
                self._fallback_generator = None
        
        self._fallback_thread = threading.Thread(
            target=self._fallback_injection_loop,
            daemon=True,
            name="EncoderManagerFallbackInjection"
        )
        self._fallback_thread.start()
        logger.debug("PCM fallback injection started per [M19]")
    
    def _stop_fallback_injection(self) -> None:
        """
        Stop PCM fallback injection thread per contract [M24].
        
        Called when state transitions to RUNNING or when stopping.
        """
        if not self._fallback_running:
            return
        
        self._fallback_running = False
        self._fallback_grace_timer_start = None
        
        if self._fallback_thread is not None and self._fallback_thread.is_alive():
            self._fallback_thread.join(timeout=1.0)
            if self._fallback_thread.is_alive():
                logger.warning("Fallback injection thread did not stop within timeout")
        
        self._fallback_thread = None
        logger.debug("PCM fallback injection stopped per [M24]")
    
    def _fallback_injection_loop(self) -> None:
        """
        Main loop for PCM fallback injection per contract [M19]-[M25].
        
        - [M20]: Begins with SILENCE, not tone
        - [M21]: Silence continues for GRACE_PERIOD_MS (default 1500ms)
        - [M22]: After grace period, tone or silence (configurable)
        - [M23]: Continuous and real-time paced (24ms intervals)
        - [M24]: Stops when state transitions to RUNNING (checked in loop)
        - [M25]: Timing-stable loop, independent of frame arrival or restart logic
        """
        # Frame duration: 1152 samples / 48000 Hz = 0.024 seconds
        # Per [M25]: Timing-stable loop with fixed frame duration
        FRAME_DURATION_SEC = 1152 / 48000
        next_tick = time.time()
        
        logger.debug("PCM fallback injection loop started per [M25]")
        
        while self._fallback_running:
            # Check if we should still be running (state may have changed)
            if self._supervisor is None:
                break
            
            supervisor_state = self._supervisor.get_state()
            # Per [M24]: Stop when state transitions to RUNNING
            if supervisor_state == SupervisorState.RUNNING:
                break
            
            # Only inject during BOOTING, RESTART_RECOVERY, DEGRADED per [M19]
            if supervisor_state not in (SupervisorState.BOOTING, SupervisorState.RESTARTING, SupervisorState.FAILED):
                # State changed, stop injection
                break
            
            # Per [M20], [M21], [M22]: Determine which frame to inject
            frame = self._get_fallback_frame()
            
            # Write directly to supervisor's stdin (bypassing write_pcm which only works in RUNNING)
            # This ensures fallback injection works during BOOTING/RESTART_RECOVERY/DEGRADED
            try:
                stdin = self._supervisor.get_stdin()
                if stdin is not None:
                    stdin.write(frame)
                    stdin.flush()
            except (BrokenPipeError, OSError) as e:
                # Pipe broken or process ended - supervisor will handle restart
                logger.debug(f"Fallback injection write error (expected during transitions): {e}")
                break
            except Exception as e:
                logger.warning(f"Unexpected error in fallback injection: {e}")
                break
            
            # Per [M23], [M25]: Real-time paced injection (24ms intervals)
            # Per [M25]: Timing-stable loop independent of frame arrival or restart logic
            # Uses fixed frame duration to maintain consistent pacing even during heavy churn
            next_tick += FRAME_DURATION_SEC
            sleep_time = next_tick - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # Behind schedule - resync to maintain timing stability per [M25]
                next_tick = time.time()
        
        logger.debug("PCM fallback injection loop stopped")
        self._fallback_running = False
    
    def _get_fallback_frame(self) -> bytes:
        """
        Get fallback PCM frame per contract [M20], [M21], [M22].
        
        Returns:
            bytes: PCM frame (4608 bytes) - silence or tone based on grace period
        """
        # Per [M20]: Fallback MUST begin with SILENCE, not tone
        # Per [M21]: Silence MUST continue for GRACE_PERIOD_MS (default 1500ms)
        if self._fallback_grace_timer_start is not None:
            elapsed_ms = (time.monotonic() - self._fallback_grace_timer_start) * 1000.0
            
            if elapsed_ms < self._grace_period_ms:
                # Per [M20], [M21]: Still in grace period - use silence
                return self._pcm_silence_frame
        
        # Per [M22]: After grace period expires, use tone or silence (configurable)
        if self._fallback_use_tone and self._fallback_generator is not None:
            try:
                return self._fallback_generator.get_frame()
            except Exception as e:
                logger.warning(f"Tone generation failed, using silence: {e}")
                return self._pcm_silence_frame
        
        # Continue with silence if tone is disabled or generator unavailable
        return self._pcm_silence_frame
    
    def get_state(self) -> EncoderState:
        """
        Get current encoder state.
        
        Returns:
            Current EncoderState
        """
        with self._state_lock:
            return self._state
    
    # Legacy methods removed - now handled by FFmpegSupervisor
    # _start_encoder_process, _stderr_drain, _handle_stall, _handle_drain_error, _restart_encoder_async
    # are all implemented in FFmpegSupervisor

