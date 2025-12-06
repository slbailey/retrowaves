# Contract: Encoder Operational Modes

This contract defines how Tower behaves under different runtime conditions, governing when encoding is required and when it is optional, defining behavior during transitions, and formally separating live, restart, fallback, and test harness modes.

## 1. Operational Modes

Tower operates in one of the following modes at any given time:

- [O1] **COLD_START**: Initial system startup before encoder process is spawned.
- [O2] **BOOTING**: Startup liveness proving - encoder process is running but first MP3 frame has not yet been received.
- [O3] **LIVE_INPUT**: Primary operation - encoder is producing MP3 frames from live PCM input.
- [O4] **FALLBACK**: Tone or silence injection - no live PCM input available, system outputs fallback content.
- [O5] **RESTART_RECOVERY**: Encoder restart in progress - previous encoder failed, new process is being spawned.
- [O6] **OFFLINE_TEST_MODE**: Testing mode - FFmpeg encoder is disabled, system uses synthetic MP3 frames.
- [O7] **DEGRADED**: Maximum restart attempts reached - encoder has failed permanently, system operates in degraded mode.

## 2. Mode Definitions and Behavior

### [O1] COLD_START Mode

**Definition**: Initial system startup before encoder process is spawned.

**Behavior**:
- System is initializing components.
- No encoder process exists.
- `EncoderManager.get_frame()` MUST return `None` or prebuilt silence MP3 frames.
- HTTP broadcast loop MUST continue operating (may send silence or wait for first frame per [T2]).
- Mode transitions to [O2] BOOTING when encoder process is spawned per [S19].

**State Mapping**:
- `SupervisorState.STOPPED` or `SupervisorState.STARTING` → COLD_START

### [O2] BOOTING Mode

**Definition**: Startup liveness proving - encoder process is running but first MP3 frame has not yet been received.

**Behavior**:
- Encoder process MUST be running (per [S5]).
- System MUST output fallback MP3 frames (silence or tone) until first valid MP3 frame is produced by encoder.
- `EncoderManager.get_frame()` MUST return prebuilt silence MP3 frames or fallback content.
- Frame interval MUST remain 24ms ± tolerance (per [S15], [S16]).
- Continuous PCM input MUST be fed to encoder (per [S7.1]) - silence frames if no live PCM available.
- Mode transitions to [O3] LIVE_INPUT when first MP3 frame is received per [S6A].
- Mode transitions to [O5] RESTART_RECOVERY if startup timeout exceeded per [S7A], [S13].

**State Mapping**:
- `SupervisorState.BOOTING` → BOOTING

**Output Requirements**:
- System MUST NOT stall or block during BOOTING.
- Clients MUST receive continuous MP3 stream (silence or tone).
- No gaps in output timeline.
- [O2.1] **Do NOT wait for FFmpeg before playback begins**: Broadcast MUST begin instantly on cold start. BOOTING mode means stream is live even if encoder isn't producing frames yet. System MUST output fallback MP3 frames immediately, never pause or wait for encoder to be ready.
- [O2.2] **Frame boundary alignment**: The first encoder frame MUST NOT replace fallback output mid-frame; switch only on frame boundary. This prevents audible clicks/pops common in naive implementations.

### [O3] LIVE_INPUT Mode

**Definition**: Primary operation - encoder is producing MP3 frames from live PCM input.

**Behavior**:
- Encoder process MUST be running and producing MP3 frames.
- `EncoderManager.get_frame()` returns real MP3 frames from encoder output.
- Frame interval MUST be 24ms ± tolerance (per [S15], [S16]).
- System processes live PCM input from AudioInputRouter.
- Mode transitions to [O4] FALLBACK if PCM input stops (grace period expires per [G6]).
- Mode transitions to [O5] RESTART_RECOVERY if encoder fails per [S9]–[S12], [S7A].

**State Mapping**:
- `SupervisorState.RUNNING` → LIVE_INPUT

**Output Requirements**:
- System MUST output real MP3 frames from encoder.
- Frame timing MUST be consistent (24ms intervals).
- No gaps or stalls in output.

### [O4] FALLBACK Mode

**Definition**: Tone or silence injection - no live PCM input available, system outputs fallback content.

**Behavior**:
- Triggered when:
  - No PCM input present (PCM buffer empty, grace period expired per [G6]).
  - Supervisor in BOOTING and no frames yet (per [O2]).
  - Restart in progress (per [O5]).
- System MUST output:
  - Prebuilt silence MP3 frames, OR
  - Tone-generated MP3 frames if configured.
- Frame interval MUST remain 24ms ± tolerance.
- `EncoderManager.get_frame()` returns fallback MP3 frames (silence or tone).
- Mode transitions to [O3] LIVE_INPUT when PCM input resumes (per [O21]).
- Mode transitions to [O5] RESTART_RECOVERY if encoder fails.

**State Mapping**:
- Can occur during `SupervisorState.BOOTING`, `SupervisorState.RUNNING`, or `SupervisorState.RESTARTING`.

**Output Requirements**:
- System MUST output continuous MP3 stream (no gaps).
- Frame timing MUST be consistent (24ms intervals).
- Clients MUST NOT experience disconnections or stalls.

### [O5] RESTART_RECOVERY Mode

**Definition**: Encoder restart in progress - previous encoder failed, new process is being spawned.

**Behavior**:
- Previous encoder process has failed or timed out.
- New encoder process is being spawned per [S13].
- System MUST output fallback MP3 frames (silence or tone) during restart.
- `EncoderManager.get_frame()` MUST return prebuilt silence MP3 frames or fallback content.
- Frame interval MUST remain 24ms ± tolerance.
- Mode transitions to [O2] BOOTING when new encoder process is spawned per [S13.8].
- Mode transitions to [O7] DEGRADED if max restart attempts exceeded per [S13.6].

**State Mapping**:
- `SupervisorState.RESTARTING` → RESTART_RECOVERY

**Output Requirements**:
- System MUST output continuous MP3 stream during restart (no gaps).
- Frame timing MUST be consistent (24ms intervals).
- Clients MUST NOT experience disconnections or stalls.
- Restart MUST complete within backoff schedule per [S13.4].

### [O6] OFFLINE_TEST_MODE

**Definition**: Testing mode - FFmpeg encoder is disabled, system uses synthetic MP3 frames.

**Behavior**:
- FFmpegSupervisor MUST NOT start.
- No encoder process is spawned.
- `EncoderManager.get_frame()` returns synthetic MP3 frames (prebuilt silence or mock frames).
- HTTP tests and broadcast fanout run without encoder present.
- System operates normally except encoder is disabled.

**Activation**:
- Environment variable: `TOWER_ENCODER_ENABLED=0` (default: enabled)
- OR TowerService constructor flag: `encoder_enabled=False`

**State Mapping**:
- `SupervisorState.STOPPED` (encoder never started) → OFFLINE_TEST_MODE

**Test Requirements**:
- Unit tests for HTTP broadcast MUST use this mode per [I16].
- RingBuffer, HTTP broadcast, routing, and semantics tests MUST NOT require FFmpeg per [I16].
- Integration tests that specifically test encoding MUST explicitly enable encoder.

**Output Requirements**:
- System MUST output synthetic MP3 frames.
- Frame timing MUST be consistent (24ms intervals).
- All broadcast and client handling logic MUST function correctly.

### [O7] DEGRADED Mode

**Definition**: Maximum restart attempts reached - encoder has failed permanently, system operates in degraded mode.

**Behavior**:
- Encoder has exceeded maximum restart attempts per [S13.6].
- No encoder process is running.
- System MUST output fallback MP3 frames (silence or tone).
- `EncoderManager.get_frame()` MUST return prebuilt silence MP3 frames or fallback content.
- Frame interval MUST remain 24ms ± tolerance.
- System continues operating but encoder is permanently disabled.
- Manual intervention required to recover.

**State Mapping**:
- `SupervisorState.FAILED` → DEGRADED

**Output Requirements**:
- System MUST output continuous MP3 stream (no gaps).
- Frame timing MUST be consistent (24ms intervals).
- Clients MUST NOT experience disconnections or stalls.
- System MUST log clear error indicating degraded mode.

## 3. Mode Transitions

### Transition Rules

- [O8] Mode transitions MUST be atomic and thread-safe.
- [O9] During any transition, system MUST continue outputting MP3 frames (no gaps).
- [O10] Frame timing MUST remain consistent (24ms ± tolerance) during transitions.
- [O11] Clients MUST NOT experience disconnections or stalls during mode transitions.

### Transition Sequence

**Startup Sequence**:
1. [O1] COLD_START → [O2] BOOTING (when encoder process spawned per [S19])
2. [O2] BOOTING → [O3] LIVE_INPUT (when first MP3 frame received per [S6A])

**Failure Recovery**:
1. [O3] LIVE_INPUT → [O5] RESTART_RECOVERY (on encoder failure per [S13])
2. [O5] RESTART_RECOVERY → [O2] BOOTING (when new process spawned per [S13.8])
3. [O2] BOOTING → [O3] LIVE_INPUT (when first MP3 frame received per [S6A])
4. [O5] RESTART_RECOVERY → [O7] DEGRADED (if max restarts exceeded per [S13.6])

**Input Loss**:
1. [O3] LIVE_INPUT → [O4] FALLBACK (when PCM input stops, grace period expires per [G6])
2. [O4] FALLBACK → [O3] LIVE_INPUT (when PCM input resumes)

## 4. Output Guarantees

### [O12] Continuous Output Requirement

Regardless of mode, system MUST output continuous MP3 stream:
- No gaps in frame timeline.
- Frame interval MUST be 24ms ± tolerance (per [S15], [S16]).
- Clients MUST receive frames at consistent intervals.

### [O13] Frame Source Priority

When multiple frame sources are available, priority order is:
1. Real MP3 frames from encoder (LIVE_INPUT mode)
2. Prebuilt silence MP3 frames (FALLBACK, BOOTING, RESTART_RECOVERY, DEGRADED)
3. Tone-generated MP3 frames (if configured, FALLBACK mode)
4. Synthetic MP3 frames (OFFLINE_TEST_MODE)

### [O14] Mode-Aware Frame Selection

`EncoderManager.get_frame()` MUST select frame source based on current mode:
- [O3] LIVE_INPUT: Return frames from MP3 buffer (encoder output).
- [O2] BOOTING: Return prebuilt silence frames.
- [O4] FALLBACK: Return prebuilt silence or tone frames.
- [O5] RESTART_RECOVERY: Return prebuilt silence frames.
- [O6] OFFLINE_TEST_MODE: Return synthetic MP3 frames.
- [O7] DEGRADED: Return prebuilt silence or tone frames.

## 5. Testing Mode Requirements

### [O15] Test Mode Isolation

- [O15.1] Unit tests MUST use [O6] OFFLINE_TEST_MODE (no FFmpeg).
- [O15.2] HTTP broadcast tests MUST use [O6] OFFLINE_TEST_MODE per [I16].
- [O15.3] RingBuffer, routing, and semantics tests MUST use [O6] OFFLINE_TEST_MODE.
- [O15.4] Integration tests that test encoding MUST explicitly enable encoder.
- [O15.5] Tests MUST enforce mode boundaries per [I16], [I17].
- [O15.6] **MUST-HAVE**: If a unit test launches FFmpegSupervisor without explicitly requesting encoding, the test is invalid and MUST fail loudly. This prevents future regressions permanently and ensures test isolation.

### [O16] Test Mode Activation

- [O16.1] `TOWER_ENCODER_ENABLED=0` environment variable activates [O6] OFFLINE_TEST_MODE.
- [O16.2] TowerService constructor flag `encoder_enabled=False` activates [O6] OFFLINE_TEST_MODE.
- [O16.3] When [O6] OFFLINE_TEST_MODE is active, FFmpegSupervisor MUST NOT be created or started.

## 6. Broadcast-Grade Requirements

### [O17] Never Stall Transmission

System MUST never stall the transmission loop:
- Frame output MUST continue regardless of encoder state.
- Mode transitions MUST not cause output gaps.
- Restart operations MUST not block broadcast loop.

### [O18] Graceful Degradation

When encoder fails:
- System MUST transition to [O4] FALLBACK or [O7] DEGRADED mode.
- Output MUST continue (silence or tone).
- Clients MUST NOT experience disconnections.
- System MUST log clear error messages.

### [O19] Predictable Behavior

Mode transitions MUST be predictable and testable:
- Each mode has well-defined entry and exit conditions.
- Mode behavior is deterministic.
- Restart storms and silent failures are detectable and testable.

### [O20] Output Cadence Guarantee

Frame timing MUST be paced by a wall-clock/time clock, not frame availability.

**Requirements**:
- Output MUST occur on a clock — not "as fast as we have frames".
- If encoder lags, duplicate last frame instead of stalling.
- If CPU spikes, skip late frames but keep time true (no drift).
- If no fresh frame exists by deadline → emit previous frame, silence, or fallback.
- Transmission remains real-time aligned, never buffered-delayed.

**Key Principle**: This is the difference between a file transcoder and a broadcast encoder. Broadcast encoders maintain real-time cadence regardless of encoder performance.

### [O21] Seamless Recovery

When PCM input resumes while in [O4] FALLBACK mode, system MUST switch back to [O3] LIVE_INPUT with no audible pop, drop, or buffer gap.

**Requirements**:
- No restart required — system MUST smooth transition.
- Mode transition MUST be seamless (no audio artifacts).
- Frame timing MUST remain consistent (24ms ± tolerance).
- Clients MUST NOT experience disconnections or stalls.
- **Frame boundary alignment required**: Never cut mid-frame during source switch. Switch MUST occur only on frame boundary to prevent faint clicks/pops common in naive implementations.

**Optional Advanced Future Rule** (not required now):
- Crossfade or click-masked transition may be implemented for enhanced audio quality.

### [O22] Mode Telemetry

The current mode MUST be externally observable via API/metrics for dashboarding, alerting, and operators.

**Requirements**:
- System MUST expose current operational mode via API (e.g., `GET /tower/state`).
- Response MUST include:
  - Current mode (COLD_START, BOOTING, LIVE_INPUT, FALLBACK, RESTART_RECOVERY, OFFLINE_TEST_MODE, DEGRADED)
  - Frame rate (fps, e.g., 41.6 for 24ms intervals)
  - Fallback status (boolean)
  - Additional metrics as needed for observability
- This telemetry becomes critical for production broadcast systems and future features (e.g., Prevue channel).

## Required Tests

- `tests/contracts/test_tower_encoder_operation_modes.py` MUST cover:
  - [O1]–[O7]: Mode definitions and behavior
  - [O2.1]: BOOTING mode instant playback requirement
  - [O8]–[O11]: Mode transitions
  - [O12]–[O14]: Output guarantees
  - [O15]–[O16]: Testing mode requirements (including [O15.6] test isolation enforcement)
  - [O17]–[O19]: Broadcast-grade requirements
  - [O20]: Output cadence guarantee (clock-based pacing)
  - [O21]: Seamless recovery (FALLBACK → LIVE_INPUT transition)
  - [O22]: Mode telemetry (API observability)
