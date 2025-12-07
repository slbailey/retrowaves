# Contract: BROADCAST_GRADE_BEHAVIOR

This contract defines the broadcast-grade behavior requirements for the Tower encoding subsystem, ensuring it can operate indefinitely with zero PCM input, survive encoder failures gracefully, and provide continuous audio output under all conditions.

See `ARCHITECTURE_TOWER.md` Section 5.2.7 for complete architectural specification.

## 1. Core Broadcast Invariants

- [BG1] **No Dead Air (MP3 Layer)**: Once `TowerService.start()` returns "Encoder started", every call to `EncoderManager.get_frame()` MUST return a valid MP3 frame (silence/tone/program). None is not allowed in production.

- [BG2] **No Hard Dependence on PCM**: The system MUST NEVER require external PCM to be present to:
  - Keep FFmpeg alive
  - Avoid restarts
  - Satisfy timing/watchdog constraints
  The encoder MUST be able to run forever on fallback alone.
  **Architecture**: AudioPump ensures timing continuity (24ms ticks), while EncoderManager ensures audio continuity (fallback routing via `next_frame()`). Together they satisfy "no hard dependence on PCM" — AudioPump provides continuous timing ticks, and EncoderManager provides continuous PCM (program or fallback) via routing decisions.

- [BG3] **Predictable Audio State Machine**: At any instant, the encoder is in exactly one of:
  - SILENCE_GRACE – startup / recent loss of PCM: silence only
  - FALLBACK_TONE – stable absence of PCM: tone (or configured fallback)
  - PROGRAM – real PCM only
  - DEGRADED – failure mode (silence only but still valid MP3)
  All state transitions MUST be deterministic and logged.

## 2. Startup & Idle Behavior

### 2.1 Cold Start with No PCM

- [BG4] **Initial Conditions (AudioPump-driven timing, EncoderManager-driven routing)**: When `TowerService.start()` is called with no external PCM arriving (PCM buffer empty) and EncoderManager enabled:
  - FFmpegSupervisor starts FFmpeg, and during its BOOTING phase it may write initial PCM (silence) as per its own contract.
  - Within 1 frame interval (≈24ms) of AudioPump starting its loop, EncoderManager MUST:
    - Begin routing fallback-generated PCM on every 24ms tick via `next_frame()`.
    - AudioPump calls `EncoderManager.next_frame(pcm_buffer)` each tick (timing-driven).
    - EncoderManager internally routes via:
      - `write_pcm()` when valid PCM is available, OR
      - `write_fallback()` when no valid PCM is available (handled inside `next_frame()`).
  - Fallback injection MUST continue at real-time pace (≈24ms per frame), driven by **AudioPump's timing ticks** (24ms metronome), with **routing decisions made by EncoderManager** (inside `next_frame()`), until program PCM is detected and has passed the validity threshold per [BG8].
  - **Key architectural constraint**: The "within 1 frame interval" guarantee is explicitly tied to AudioPump's first tick (timing), while routing logic is entirely within EncoderManager. There is no requirement for `_fallback_thread`; in fact, any such thread would violate [M25] and the single-metronome design. "AudioPump-driven" refers to timing continuity, not routing decisions.

### 2.2 Grace Period → Tone Transition

- [BG5] **Silence Grace Period**: From the moment fallback starts, the encoder MUST inject silence PCM only for at least `GRACE_PERIOD_MS` (default 1500ms). During this period, FFmpeg produces valid MP3 frames (silence audio).

- [BG6] **Tone Lock-In**: After `GRACE_PERIOD_MS` has elapsed and there have still been no valid external PCM frames detected, system MUST transition to FALLBACK_TONE:
  - PCM injection switches from silence to tone frames (from FallbackGenerator) if tone is enabled
  - If tone is disabled by config, it remains in pure silence but is still considered FALLBACK_TONE state internally (different from SILENCE_GRACE)

- [BG7] **Long-Term Idle Stability**: The encoder MUST be able to remain in FALLBACK_TONE state for arbitrarily long durations (hours/days/years) with:
  - No FFmpeg restarts caused by input absence
  - No MP3 underflow
  - No watchdog "no first frame" or "stall" events as long as FFmpeg is producing output

## 3. PCM Detection & State Transitions

### 3.1 PCM Detection

- [BG8] **PCM Validity Threshold**: A "real PCM stream present" condition is met when:
  - A continuous run of N frames (e.g. 10–20) have been read from the PCM buffer by EncoderManager (via AudioPump calling `next_frame()` → EncoderManager routing to `write_pcm()`)
  - AND these frames are not all zeros (if zero-only can't be distinguished, treat "frames present" as the condition)
  This prevents toggling due to single stray frames.
  **Architecture**: EncoderManager applies this threshold internally within `next_frame()` before transitioning to PROGRAM state. AudioPump provides timing ticks only.

### 3.2 Tone → Program Transition

- [BG9] **Transition Trigger**: When PCM_PRESENT becomes true while encoder is in FALLBACK_TONE state:
  - EncoderManager MUST stop fallback injection immediately or within 1 frame
  - Thereafter, only real PCM is fed to FFmpeg via write_pcm (LIVE_INPUT mode)

- [BG10] **Click/Pop Minimization**: EncoderManager/AudioPump MUST ensure there is no large discontinuity at the moment of switch:
  - If you have a compressor/limiter: rely on it but avoid sudden zero → full-scale jumps
  - At minimum, do NOT change sample rate/format/bit depth
  - Optional enhancement (recommended): Crossfade 1–2 frames between tone and PCM in PCM domain before handing to FFmpeg, or start PCM at a low gain and ramp to full over a small number of frames
  - But even without crossfade, maintain same RMS ballpark to avoid obvious blast

### 3.3 Program → Tone (Loss of PCM)

- [BG11] **Loss Detection**: Once in PROGRAM state, if no valid PCM frames are available for `LOSS_WINDOW_MS` (e.g. 250–500ms), system MUST treat this as "loss of program audio".

- [BG12] **Program Loss Transition**: On program loss:
  - Enter SILENCE_GRACE again (silence injection, reset grace timer)
  - After another `GRACE_PERIOD_MS` without PCM, move back to FALLBACK_TONE
  - Hysteresis prevents rapid flipping if PCM flickers

## 4. Encoder Liveness & Watchdogs

### 4.1 First Frame Watchdog

- [BG13] **First Frame Source-Agnostic**: The "first MP3 frame received" condition MUST be satisfied by any valid MP3 output (from silence, tone, or real program), not just real inputs. As soon as stdout yields one valid frame, "BOOTING" timeout is satisfied. No additional requirement that PCM be present.

### 4.2 Stall Detection While Idle

- [BG14] **Stall Semantics**: A "stall" is defined as no MP3 bytes from FFmpeg for `STALL_THRESHOLD_MS`. This MUST fire whether we're on program or fallback.

- [BG15] **Stall Recovery**: On stall:
  - Supervisor transitions to RESTARTING and executes restart backoff
  - EncoderManager MUST continue fallback injection once FFmpeg is up again, returning to SILENCE_GRACE → FALLBACK_TONE sequence as needed
  - Crucially: stall due to input absence should never happen if fallback injection is working; a stall indicates real FFmpeg failure, which justifies restart

## 5. Restart Behavior & State Preservation

### 5.1 MP3 Buffer Continuity

- [BG16] **Buffer Preservation Across Restart**: When FFmpeg restarts:
  - The MP3 ring buffer MUST NOT be forcibly cleared by EncoderManager or Supervisor
  - Any frames already queued MUST be allowed to drain (they'll disappear naturally as consumed)
  - This avoids abrupt artifacts on the listener side at the moment of restart if the player is slightly ahead

### 5.2 Fallback Re-Entry After Restart

- [BG17] **Automatic Fallback Resumption**: After a restart completes:
  - EncoderManager MUST automatically detect supervisor restart completion and resume fallback routing
  - EncoderManager enables fallback routing via `next_frame()` automatically until conditions for PROGRAM are again satisfied (per [M16A], [BG8])
  - AudioPump continues providing 24ms timing ticks, ensuring timing continuity
  - EncoderManager ensures audio continuity via automatic fallback routing
  - There MUST be no window after restart where FFmpeg is running but receiving no PCM from either program or fallback
  - **Architecture**: EncoderManager owns fallback state management and automatically resumes fallback routing. AudioPump provides continuous timing ticks but does not control fallback resumption.

## 6. Production vs Test Behavior

### 6.1 OFFLINE_TEST_MODE

- [BG18] **OFFLINE_TEST_MODE as Local Simulation Only**: When `TOWER_ENCODER_ENABLED=0` or `encoder_enabled=False`, EncoderManager MUST NOT start FFmpeg at all. `get_frame()` MUST return synthetic MP3 silence frames (created locally), following the same timing expectations. Fallback injection and watchdog logic can be bypassed. This ensures you can unit-test the upper stack without invoking FFmpeg.

### 6.2 Test-Safe Defaults

- [BG19] **No Tone in Tests by Default**: For unit/contract tests:
  - Default `TOWER_PCM_FALLBACK_TONE=0` to avoid requiring audio inspections
  - Ensure fallback silence is enough to satisfy watchdogs
  - Production configs re-enable tone as needed

## 7. Logging & Monitoring

- [BG20] **Mode Logging**: Whenever encoder state changes: SILENCE_GRACE ↔ FALLBACK_TONE ↔ PROGRAM ↔ DEGRADED, Tower MUST log:
  - Old state → new state
  - Reason (startup, PCM detected, PCM lost, encoder restart, fatal error)
  - Relevant counters (grace ms elapsed, restarts count, etc.)

- [BG21] **Alarms**: At minimum, the following events should generate operational alarms (or at least WARN/ERROR):
  - Repeated FFmpeg restarts exceeding max_restarts
  - Persistent operation in FALLBACK_TONE for longer than some configurable threshold (e.g. 10 minutes) – this can be a "no program audio" alarm
  - Switches to DEGRADED (FFmpeg completely dead or disabled)

## 8. Automatic Self-Healing & Recovery

- [BG22] **Self-Healing After Max Restarts**: If FFmpeg reaches `max_restarts`, state becomes DEGRADED but streaming continues. System shall retry full encoder recovery every `RECOVERY_RETRY_MINUTES` (default 10 minutes). Must run FOREVER without operator intervention. This prevents a 3AM outage from requiring manual intervention.

**Implementation Requirements:**
- After max restarts, enter DEGRADED state but continue streaming fallback audio
- Start background recovery timer that attempts full encoder restart every `RECOVERY_RETRY_MINUTES`
- Each recovery attempt follows normal startup sequence (BOOTING → RUNNING)
- If recovery succeeds, transition back to PROGRAM or FALLBACK_TONE as appropriate
- If recovery fails, continue streaming fallback and schedule next retry
- System must never give up permanently; retries continue indefinitely

## 9. Audio Transition Smoothing

- [BG23] **Optional Crossfade for Fallback → Program Transitions**: Fallback → Program transitions must support optional crossfade (default off but architecture prepared to support it). Real broadcast stations use crossfading to eliminate clicks, pops, and level jumps during source transitions.

**Implementation Requirements:**
- Crossfade is optional and disabled by default (`TOWER_CROSSFADE_ENABLED=0`)
- When enabled, perform 1-2 frame crossfade in PCM domain before handing to FFmpeg
- Architecture must support crossfade without blocking or timing disruption
- Crossfade parameters: duration (frames), curve (linear/logarithmic), and gain normalization
- Even without crossfade, maintain same RMS ballpark to avoid obvious level jumps

## 10. File Fallback Looping

- [BG24] **Sample-Accurate Gapless File Fallback**: When fallback MP3/WAV is used, decoding MUST occur into PCM at startup. Loop must be sample-accurate, gapless, and stable indefinitely. This ensures professional "Please Stand By" or emergency audio loops seamlessly without audible gaps or clicks.

**Implementation Requirements:**
- Pre-decode fallback file to PCM at Tower startup (not on-demand)
- Cache decoded PCM frames in memory for low-latency access
- Loop detection: identify loop points (start/end samples) for seamless wrapping
- Sample-accurate looping: no frame boundary misalignment, no partial samples
- Gapless playback: zero samples of silence between loop iterations
- Stable indefinitely: loop must run for hours/days without drift or accumulation errors
- Fallback: If file decoding fails, fall through to tone generator

## 11. Silence Detection on Program PCM

- [BG25] **Amplitude-Aware Silence Detection**: Real PCM may contain silence (songs with silence, mixers idle). Silence ≠ no-input. Silence detection must be amplitude-aware not just "frame present". This stops tone falsely firing during quiet songs or natural program silence.

**Implementation Requirements:**
- PCM presence detection must distinguish between:
  - **No input**: No frames arriving from source (triggers fallback)
  - **Silent input**: Frames arriving but containing silence/very low amplitude (remains in PROGRAM)
- Amplitude threshold: Configure RMS or peak threshold below which PCM is considered "silent" but still "present"
- Default threshold: -60dB or configurable via `TOWER_PCM_SILENCE_THRESHOLD_DB`
- Hysteresis: Require sustained silence for `SILENCE_DURATION_MS` before treating as "no input"
- This prevents false fallback triggers during:
  - Quiet passages in music
  - Mixer fader-down moments
  - Natural program silence between tracks

## 12. Observability & Monitoring API

- [BG26] **HTTP Status Endpoint for DevOps**: HTTP `/status` endpoint must expose:
  - Current source (program/tone/silence)
  - PCM buffer fullness (frames available / capacity)
  - MP3 buffer fullness (frames available / capacity)
  - Restarts count (total encoder restarts since startup)
  - Uptime (seconds since TowerService.start())
  - Optional: JSON stats for dashboards

**Implementation Requirements:**
- Endpoint: `GET /status` returns JSON with current system state
- Response format:
  ```json
  {
    "source": "program|tone|silence",
    "encoder_state": "RUNNING|RESTARTING|DEGRADED|STOPPED",
    "pcm_buffer": {
      "available": 45,
      "capacity": 100,
      "percent_full": 45
    },
    "mp3_buffer": {
      "available": 320,
      "capacity": 400,
      "percent_full": 80
    },
    "restarts": 2,
    "uptime_seconds": 86400,
    "recovery_retries": 0
  }
  ```
- Non-blocking: Status endpoint must never block or affect audio streaming
- Thread-safe: All status queries must be safe to call from any thread
- Optional dashboard integration: Consider Prometheus metrics or similar for long-term monitoring

**Note:** This endpoint doesn't need to be implemented immediately, but once Tower runs months continuously, operational visibility becomes critical for diagnosing issues and monitoring health.

## 13. Configuration

The following environment variables control broadcast-grade behavior:

```bash
# Grace period before switching from silence to tone
TOWER_PCM_GRACE_PERIOD_MS=1500

# Enable tone fallback after grace period
TOWER_PCM_FALLBACK_TONE=1  # 0=silence only, 1=tone enabled

# Window for detecting PCM loss when in PROGRAM state
TOWER_PCM_LOSS_WINDOW_MS=500

# Retry encoder recovery after max restarts (minutes)
TOWER_RECOVERY_RETRY_MINUTES=10

# Enable crossfade for fallback→program transitions
TOWER_CROSSFADE_ENABLED=0  # 0=disabled, 1=enabled

# RMS threshold for detecting silent but present PCM (dB)
TOWER_PCM_SILENCE_THRESHOLD_DB=-60
```

## 14. Required Tests

- `tests/contracts/test_tower_broadcast_grade.py` MUST cover:
  - [BG1]–[BG3]: Core broadcast invariants
  - [BG4]–[BG7]: Startup & idle behavior
  - [BG8]–[BG12]: PCM detection & state transitions
  - [BG13]–[BG15]: Encoder liveness & watchdogs
  - [BG16]–[BG17]: Restart behavior & state preservation
  - [BG18]–[BG19]: Production vs test behavior
  - [BG20]–[BG21]: Logging & monitoring
  - [BG22]: Automatic self-healing & recovery
  - [BG23]: Audio transition smoothing (optional)
  - [BG24]: File fallback looping (optional)
  - [BG25]: Silence detection on program PCM (optional)
  - [BG26]: Observability & monitoring API (optional)

## 15. Summary

This contract ensures Tower can:
- Start cold with zero PCM and remain stable indefinitely
- Run forever on fallback alone without requiring external PCM
- Survive encoder failures and restarts without audible glitches
- Switch cleanly between fallback tone and real PCM (both directions)
- Self-heal after max restarts without operator intervention
- Provide operational visibility for long-running deployments

That's the broadcast-grade behavior: no dead air, no requirement that the studio "talks" immediately, deterministic logged transitions between known audio states, automatic self-healing, and operational observability.




