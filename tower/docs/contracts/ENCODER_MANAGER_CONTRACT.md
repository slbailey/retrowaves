# Contract: ENCODER_MANAGER

This contract defines the behavior of EncoderManager, which manages the encoding subsystem and owns FFmpegSupervisor.

## 1. Core Invariants

- [M1] EncoderManager is the **ONLY owner** of FFmpegSupervisor.
- [M2] EncoderManager **never exposes supervisor** to external components.
- [M3] Public interface is limited to:
  - `write_pcm(frame: bytes)` → forwards to supervisor
  - `get_frame() -> Optional[bytes]` → returns MP3 frame or silence
  - `start()`, `stop()`, `get_state()`
- [M4] Internally maintains:
  - MP3 ring buffer (output) - owned by EncoderManager
  - PCM buffer is **NOT owned** by EncoderManager (owned by TowerService, passed to AudioPump)

## 2. Supervisor Lifecycle

- [M5] FFmpegSupervisor is created **internally by EncoderManager (never externally)**, typically during `start()`.
- [M6] Supervisor lifecycle methods are called only by EncoderManager:
  - `supervisor.start()` → called by `encoder_manager.start()`
  - `supervisor.stop()` → called by `encoder_manager.stop()`
- [M7] Supervisor state changes are tracked via callback to EncoderManager.

## 3. PCM Input Interface

- [M8] `write_pcm(frame: bytes)`:
  - Forwards frame to supervisor's `write_pcm()` method
  - **Non-blocking**: Must return immediately, never stalls or deadlocks
  - **Error handling**: Handles BrokenPipeError and other I/O errors gracefully
  - **Async restart**: If pipe is broken, restart is triggered asynchronously; write_pcm() does not wait for restart
  - Only writes if encoder state is RUNNING
  - Multiple calls after broken pipe must all return immediately (non-blocking)
- [M9] PCM frames are written directly to supervisor (no intermediate buffering in EncoderManager).
  - PCM buffer is **outside** EncoderManager (owned by TowerService)
  - Flow: AudioInputRouter → PCM buffer → AudioPump → EncoderManager.write_pcm() → supervisor.write_pcm()
  - EncoderManager does NOT own or manage PCM buffer

## 4. MP3 Output Interface

- [M10] `get_frame() -> Optional[bytes]`:
  - **MUST NEVER BLOCK** and **SHOULD avoid returning None**.
  - Returns frame from MP3 buffer if available.
  - Returns silence frame if buffer empty (after first frame received).
  - May return None only during the earliest startup window before fallback activation, but SHOULD return silence from first call whenever feasible.
  - For broadcast-grade systems: **MUST NEVER return None**. If no MP3 is available, it MUST return silence.
- [M11] MP3 buffer is populated by supervisor's drain thread (not directly by EncoderManager).

## 5. State Management

- [M12] EncoderManager state tracks SupervisorState but resolves externally as Operational Modes [O1–O7]:
  - STOPPED/STARTING → COLD_START [O1]
  - BOOTING → BOOTING [O2] until first MP3 frame received
  - RUNNING → LIVE_INPUT [O3]
  - RESTARTING → RESTART_RECOVERY [O5]
  - FAILED → DEGRADED [O7]
- [M13] State transitions are synchronized via supervisor callback.

## 6. Operational Mode Integration

- [M14] EncoderManager is responsible for translating SupervisorState into Operational Modes [O1]–[O7] per ENCODER_OPERATION_MODES.md.
- [M15] `EncoderManager.get_frame()` MUST apply source selection rules defined in [O13] and [O14] (frame source priority and mode-aware frame selection).
- [M16] `write_pcm(frame)` MUST only deliver PCM during LIVE_INPUT [O3]; during BOOTING, RESTART_RECOVERY, FALLBACK, and DEGRADED, silence/tone generation is used instead.
- [M17] OFFLINE_TEST_MODE [O6] MUST bypass supervisor creation entirely: `get_frame()` returns synthetic frames, no FFmpegSupervisor is created or started.
- [M18] EncoderManager MUST NOT expose raw SupervisorState; external components interact in terms of Operational Modes only.

## 7. PCM Fallback Injection

- [M19] During BOOTING [O2], RESTART_RECOVERY [O5], and DEGRADED [O7], EncoderManager must inject PCM data into FFmpeg even when no live PCM input exists.
- [M20] On startup, fallback MUST begin with SILENCE, not tone.
- [M21] Silence MUST continue for GRACE_PERIOD_MS (default 1500).
- [M22] If no real PCM frames have arrived after grace period expires, system MUST inject tone PCM or continue silence (configurable fallback strategy).
- [M23] Fallback PCM injection MUST be continuous and real-time paced.
- [M24] After transition to RUNNING, fallback immediately stops when real PCM arrives.
- [M24A] When encoder is disabled via OFFLINE_TEST_MODE [O6], [M19]–[M24] do not apply, as no supervisor/PCM injection pipeline exists.
- [M25] PCM fallback generator MUST run in its own timing-stable loop, not tied to frame arrival or restart logic, ensuring continuous pacing even during heavy churn.

## Required Tests

- `tests/contracts/test_tower_encoder_manager.py` MUST cover:
  - [M1]–[M4]: Ownership and interface isolation
  - [M5]–[M7]: Supervisor lifecycle encapsulation
  - [M8]–[M9]: PCM input forwarding
  - [M10]–[M11]: MP3 output interface
  - [M12]–[M13]: State management
  - [M14]–[M18]: Operational mode integration
  - [M19]–[M25]: PCM fallback injection

