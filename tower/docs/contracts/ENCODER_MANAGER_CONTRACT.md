# Contract: ENCODER_MANAGER (Revised for Broadcast Grade)

This contract defines the behavior of EncoderManager, which manages the encoding subsystem and owns FFmpegSupervisor.

## 1. Core Invariants

- [M1] EncoderManager is the **ONLY owner** of FFmpegSupervisor.
- [M2] EncoderManager **never exposes supervisor** to external components.
- [M3] Public interface is limited to:
  - `next_frame(pcm_buffer: FrameRingBuffer)` → called by AudioPump each tick; handles all routing internally
  - `write_pcm(frame: bytes)` → forwards to supervisor (when allowed) - internal use or legacy
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

- [M3A] `next_frame(pcm_buffer: FrameRingBuffer)` → None:
  - **Primary entry point** for AudioPump per contract [A3], [A7].
  - Called by AudioPump on every 24ms tick.
  - EncoderManager handles ALL routing decisions internally:
    - Checks PCM buffer for available frames
    - Determines operational mode (BOOTING, LIVE_INPUT, RESTART_RECOVERY, DEGRADED)
    - Applies PCM validity threshold per [M16A]
    - Routes to `write_pcm()` for program PCM (if threshold met and in LIVE_INPUT)
    - Routes to `write_fallback()` for fallback PCM (all other cases)
  - **Non-blocking**: MUST return immediately, never stalls or deadlocks.
  - AudioPump does not need to know about routing, thresholds, or operational modes.
  - This unifies all routing logic in EncoderManager, making the architecture cleaner and tests pass naturally.
- [M3A.1] `next_frame()` MUST call either `write_pcm()` or `write_fallback()` internally exactly once per tick. It MUST NOT return PCM to AudioPump. The routing action completes inside EncoderManager.

- [M8] `write_pcm(frame: bytes)`:
  - Forwards frame to supervisor's `write_pcm()` method only when live PCM is allowed by operational mode.
  - **Non-blocking**: Must return immediately, never stalls or deadlocks.
  - **Error handling**: Handles BrokenPipeError and other I/O errors gracefully.
  - **Async restart**: If pipe is broken, restart is triggered asynchronously; write_pcm() does not wait for restart.
  - Only writes "program" PCM to FFmpeg when the encoder is in LIVE_INPUT [O3] operational mode. EncoderManager MUST NOT call supervisor.write_pcm() with live program frames in BOOTING [O2], RESTART_RECOVERY [O5], FALLBACK_TONE, or DEGRADED [O7] (per [M16], [M19H], [M19I]).
  - Multiple calls after broken pipe must all return immediately (non-blocking).
- [M9] PCM frames are written directly to supervisor (no intermediate buffering in EncoderManager).
  - The live PCM buffer is **outside** EncoderManager (owned by TowerService, passed to AudioPump).
  - Flow per contract [A3], [A7]:
      AudioInputRouter → PCM buffer → AudioPump → EncoderManager.next_frame(pcm_buffer) → [routing logic] → write_pcm() or write_fallback() → supervisor.write_pcm()
  - EncoderManager does NOT own or manage the live PCM buffer, but accesses it via `next_frame(pcm_buffer)` parameter.

## 4. MP3 Output Interface

- [M10] `get_frame() -> Optional[bytes]`:
  - **MUST NEVER BLOCK** and **SHOULD avoid returning None**.
  - Returns frame from MP3 buffer if available.
  - Returns silence frame if buffer empty (after first frame received).
  - **None return policy**: `get_frame()` MAY return `None` only during COLD_START [O1] before fallback activation, but MUST NEVER return `None` once fallback has begun or system reaches BOOTING [O2]. This matches real transmitter behavior where output must be continuous once the encoder pipeline is initialized.
  - For broadcast-grade systems: **MUST NEVER return None** once fallback is active or BOOTING is reached. If no MP3 is available, it MUST return silence.
- [M11] MP3 buffer is populated by supervisor's drain thread (not directly by EncoderManager).

## 5. State Management

- [M12] EncoderManager state tracks SupervisorState but resolves externally as Operational Modes [O1–O7]. The mapping is **conditional** and takes into account both encoder liveness and PCM admission state:
  - STOPPED / STARTING  
    → COLD_START [O1]
  - BOOTING  
    → BOOTING [O2] **until first MP3 frame is received** (supervisor has not yet proven it can emit frames).
  - RUNNING  
    → 
      - LIVE_INPUT [O3] **only when**:
        - SupervisorState == RUNNING, **and**
        - PCM validity threshold has been satisfied per [M16A]/[BG8], **and**
        - the internal audio state machine is in PROGRAM (no active PCM loss window).
      - A non-PROGRAM audio state while SupervisorState == RUNNING  
        (e.g. SILENCE_GRACE or FALLBACK_TONE during initial boot or after loss detection)  
        MUST resolve to the appropriate **fallback-oriented operational mode** (e.g. FALLBACK_ONLY [O4]) rather than LIVE_INPUT [O3].
  - RESTARTING  
    → RESTART_RECOVERY [O5]  
    (Supervisor is in the process of being restarted; output is sustained from buffered MP3/fallback per [BG13]/[BG22].)
  - FAILED  
    → DEGRADED [O7]  
    (Encoder has exceeded retry budget or entered a hard failure; output is provided solely via fallback generator per [BG2]/[BG17].)
- [M13] State transitions are synchronized via supervisor callback.

## 6. Operational Mode Integration

- [M14] EncoderManager is responsible for translating SupervisorState into Operational Modes [O1]–[O7] per ENCODER_OPERATION_MODES.md.
- [M15] `EncoderManager.get_frame()` MUST apply source selection rules defined in [O13] and [O14] (frame source priority and mode-aware frame selection).
- [M16] Live program PCM MUST only be delivered during LIVE_INPUT [O3]. During BOOTING [O2], RESTART_RECOVERY [O5], FALLBACK_TONE, and DEGRADED [O7], AudioPump MUST feed fallback PCM (silence/tone) on every tick per [M19]/[M25]; EncoderManager MUST NOT treat any PCM during these modes as valid "program" audio for state transitions.
- [M16A] **PROGRAM Admission & PCM Validity Threshold (BG8, BG11)**
  - PROGRAM/LIVE_INPUT [O3] is a **derived audio state**, not a direct alias of SupervisorState.RUNNING.
    Transition into PROGRAM/LIVE_INPUT [O3] MUST be gated by a PCM validity threshold:
    - EncoderManager, within `next_frame(pcm_frame)`, MUST observe a continuous run of N valid PCM frames
      (e.g. 10–20 consecutive ticks) from the PCM buffer; and
    - Those frames MUST pass the amplitude / silence detection rules (BG25) if such rules are enabled.
  - Threshold accounting rules:
    - The PCM validity counter is maintained **inside EncoderManager.next_frame()** and is incremented
      only when:
      - a non-None PCM frame is presented, and
      - the frame passes the validity checks.
    - Once the threshold N is satisfied, the PCM validity counter MAY be capped or reset internally,
      but subsequent routing decisions MUST treat the system as having "PCM admitted" until a PCM loss
      is detected per [BG11]/PCM loss detection rules.
  - Behavior **before** the threshold is satisfied:
    - Supervisor may already be RUNNING, but the external audio state MUST remain in SILENCE_GRACE or FALLBACK_TONE
      (or equivalent non-PROGRAM state in the audio state machine).
    - Fallback MUST remain active and continue to be injected on every AudioPump tick via `next_frame()`
      (i.e. all audio written via `write_fallback()`).
    - A single stray PCM frame MUST NOT cause a transition to PROGRAM/LIVE_INPUT [O3].
  - Behavior **after** the threshold is satisfied:
    - On each subsequent AudioPump tick, if `pcm_frame` is non-None and no PCM loss window is active,
      EncoderManager MUST route to `write_pcm()` instead of `write_fallback()`.
    - If `pcm_frame` is None (no PCM available) after admission, EncoderManager MUST:
      - consider this as a candidate PCM loss event, and
      - invoke the PCM loss detection logic (e.g. `_check_pcm_loss()`) that may transition back to SILENCE_GRACE
        or FALLBACK_TONE after the configured loss window expires.
    - While in PROGRAM/LIVE_INPUT [O3], fallback MUST NOT be mixed in or substituted for PCM
      unless a PCM loss or encoder failure is detected per [BG11]/[BG12]/[BG20].
- [M17] OFFLINE_TEST_MODE [O6] MUST bypass supervisor creation entirely: `get_frame()` returns synthetic frames, no FFmpegSupervisor is created or started.
- [M18] EncoderManager MUST NOT expose raw SupervisorState; external components interact in terms of Operational Modes only.

## 7. PCM Fallback Injection

- [M19] During BOOTING [O2], RESTART_RECOVERY [O5], FALLBACK_TONE, and DEGRADED [O7], the AudioPump + EncoderManager pipeline MUST ensure FFmpeg receives PCM data on every tick, even when no live PCM input exists. This satisfies BROADCAST_GRADE_BEHAVIOR [BG2], [BG4], [BG7], and [BG17]:
  - System MUST be able to run forever on fallback alone.
  - Encoder liveness and watchdogs MUST NOT depend on presence of external PCM.
- [M19A] EncoderManager MUST maintain an internal fallback controller (not part of public API) that automatically activates fallback when:
  - Supervisor is in BOOTING [O2], RESTART_RECOVERY [O5], FALLBACK_TONE, or DEGRADED [O7], OR
  - Supervisor is RUNNING but no valid live PCM input is available (PCM loss detected per [BG11], gated by [BG8]/[BG25]).
  Fallback MUST stop immediately upon real PCM stabilization (when PCM validity threshold is met per [BG8], [BG9]).
  The fallback controller manages grace period timing, silence-to-tone transitions, and ensures continuous PCM availability via `_get_fallback_frame()` for AudioPump to consume on every tick per [M25].
- [M19F] EncoderManager MUST expose internal fallback retrieval and activation hooks, but MUST NOT own a timing loop. Pacing remains entirely AudioPump-driven. EncoderManager MUST provide:
  - `_start_fallback_injection()` → enables fallback immediately (test-only control, and internal fail-safe).
  - `_stop_fallback_injection()` → optional, test cleanup only.
  - `_fallback_running: bool` → owns injection state (default `False`).
  Additional requirements:
  - [M19F.1] `_start_fallback_injection()` and `_stop_fallback_injection()` MUST NOT themselves generate PCM or call supervisor.write_pcm(). They only adjust internal state so that on the next AudioPump tick, the proper fallback PCM is delivered via write_fallback() / write_pcm() paths.
  - [M19F.2] These hooks MUST NOT introduce timing loops, sleep calls, or background schedulers. All pacing is driven by AudioPump per [M25].
- [M19G] EncoderManager MUST expose `_get_fallback_frame()`:
  - Returns correct fallback PCM frame (silence→tone progression per [M20], [M21], [M22] and BG4–BG7).
  - Callable synchronously with no blocking.
  - No internal sleep, no timing loop.
  - Canonical internal API for fallback PCM; any legacy helper like `get_fallback_pcm_frame()` MUST, if present, be a thin wrapper around `_get_fallback_frame()` and MUST NOT introduce divergent behavior.
- [M19H] Continuous fallback emission occurs ONLY when AudioPump ticks and `write_pcm()` is not permitted per [M16]/[M16A].
  - During BOOTING [O2], RESTART_RECOVERY [O5], FALLBACK_TONE, and DEGRADED [O7], AudioPump MUST deliver fallback via a dedicated path (e.g. `write_fallback()`), and `write_pcm()` MUST NOT forward program PCM to supervisor.
  - This ensures that all PCM reaching FFmpeg during non-PROGRAM modes is classified as fallback, consistent with BG state machine.
- [M19I] During BOOTING / RESTART_RECOVERY / FALLBACK_TONE / DEGRADED:
  - AudioPump MUST deliver fallback via `write_fallback()` on every 24ms tick.
  - `write_pcm()` MUST NOT forward program PCM to supervisor.
  - This ensures continuous PCM delivery per [M19] while respecting [M16]/[M16A] (live PCM only during PROGRAM/LIVE_INPUT [O3]).
- [M19J] In OFFLINE_TEST_MODE [O6]:
  - `_fallback_running` MUST NOT auto-activate.
  - Fallback methods may exist but MUST NOT schedule threads, timers, or clocks.
  - No supervisor/PCM injection pipeline exists; `get_frame()` is satisfied via synthetic MP3 frames only.
  - This satisfies [BG18] and ensures test isolation per [M24A].
- [M19L] After supervisor restart, fallback MUST re-activate automatically until the valid PCM threshold is reached per [BG8], [BG9]:
  - Whenever supervisor transitions back to BOOTING [O2] or RUNNING (post-restart), EncoderManager MUST enable fallback controller state and ensure `_fallback_running` is `True` until PROGRAM conditions are satisfied per [M16A].
  - This ensures continuous PCM delivery per [BG17] and prevents gaps after restart completion. There MUST be no window where FFmpeg is running but receiving no PCM from either program or fallback.
- [M20] On startup, fallback MUST begin with SILENCE, not tone.
- [M21] Silence MUST continue for GRACE_PERIOD_MS (default 1500).
- [M22] If no real PCM frames have arrived after grace period expires, system MUST inject tone PCM or continue silence (configurable fallback strategy) in alignment with BROADCAST_GRADE_BEHAVIOR.
- [M23] Fallback PCM injection MUST be continuous and real-time paced:
  - Every AudioPump tick MUST have a frame to deliver (either program PCM or fallback), ensuring [BG1] No Dead Air at MP3 layer and [BG2] No hard dependence on PCM.
- [M24] Fallback Stops on Real PCM Arrival
  - Once PROGRAM/LIVE_INPUT [O3] has been entered per [M16A] (i.e. SupervisorState == RUNNING,
    PCM validity threshold satisfied, and audio state == PROGRAM):
    - On each AudioPump tick where a non-None PCM frame is available:
      - EncoderManager MUST route audio exclusively via `write_pcm()` and MUST NOT call `write_fallback()`.
      - Fallback generator output MUST NOT be mixed into, or substituted for, the live PCM path.
    - Fallback audio (silence or tone) MUST remain **idle but ready** and MAY only re-enter the output
      chain if:
      - PCM loss is detected per the configured loss window (e.g. no valid PCM observed for T milliseconds),
        at which point the audio state machine transitions back to SILENCE_GRACE or FALLBACK_TONE; or
      - the encoder enters a degraded/failed condition per [BG11]/[BG17]/[BG22].
  - The effect of [M24] combined with [M16A]/[BG8]/[BG9] is:
    - Before PCM admission: output is derived entirely from fallback (silence then optional tone).
    - After PCM admission (PROGRAM): output is derived entirely from real PCM (via `write_pcm()`),
      with no fallback being injected while PCM remains valid.
    - If PCM is subsequently lost or the encoder fails, the system transitions back to a fallback-derived
      mode without any dead air, per broadcast-grade requirements [BG1]/[BG2]/[BG11].
- [M24A] When encoder is disabled via OFFLINE_TEST_MODE [O6], [M19]–[M24] do not apply, as no supervisor/PCM injection pipeline exists.
- [M25] PCM fallback generation MUST be compatible with the system's single metronome:
  - AudioPump remains the ONLY real-time clock ([A1], [A4]). This is the fundamental broadcast-grade architecture decision.
  - EncoderManager MUST provide non-blocking, on-demand fallback frame retrieval:
    - `get_fallback_pcm_frame()` (or `_get_fallback_frame()`) returns a valid 4608-byte frame without blocking.
    - All pacing for fallback injection comes from AudioPump calling `write_pcm()` / `write_fallback()` every 24ms.
  - EncoderManager and FallbackGenerator MUST NOT:
    - Run any background loops or `time.sleep()` to pace PCM.
    - Spawn a `_fallback_thread` that writes PCM independently.
    - Introduce their own independent timing loops that compete with AudioPump's metronome.
  - EncoderManager.next_frame() MUST only ever be called by AudioPump's 24ms tick loop. No other component may generate PCM or drive this method on its own schedule.
  - write_pcm() and write_fallback() are internal methods called by next_frame() for routing. They may also be called directly for backwards compatibility or testing, but next_frame() is the primary entry point.
  - **Contract decision**: `_fallback_thread` MUST NOT exist on EncoderManager. `_fallback_running: bool` does exist for test hooks, but it is purely a state flag (e.g., "we are routing via fallback"), not a timing indicator. Any reliance on `_fallback_thread` in tests or docs is deprecated and removed.

## 8. Shutdown Behavior

- [M30] EncoderManager Clean Shutdown Behavior:
  EncoderManager MUST expose `stop()` which:
  1. Stops the FFmpegSupervisor cleanly (calls `supervisor.stop()` per [S31]).
  2. Prevents further calls to `write_pcm()`/`write_fallback()` from processing new PCM frames (methods may no-op or return immediately).
  3. Allows `next_frame()` calls to no-op safely if invoked post-stop (must not raise exceptions or block).
  4. Releases threads (drain thread, recovery thread) - ensures all background threads associated with supervisor are terminated.
  5. Ensures no restart loops run after shutdown (restart logic must be disabled and remain disabled).

## Required Tests

- `tests/contracts/test_tower_encoder_manager.py` MUST cover:
  - [M1]–[M4]: Ownership and interface isolation
  - [M3A]: `next_frame()` routing logic (primary AudioPump entry point)
  - [M5]–[M7]: Supervisor lifecycle encapsulation
  - [M8]–[M9]: PCM input forwarding
  - [M10]–[M11]: MP3 output interface
  - [M12]–[M13]: State management
  - [M14]–[M18]: Operational mode integration
  - [M19]–[M25], [M19A], [M19F]–[M19L]: PCM fallback injection and broadcast-grade invariants (BG2, BG4–BG7, BG8–BG12, BG16–BG17) as they manifest at the EncoderManager boundary.
  - [M30]: Clean shutdown behavior (supervisor stop, thread release, restart loop prevention).
  - New test expectations for [M30]:
    - `test_shutdown_stops_restart_loops`: Verify that after `encoder_manager.stop()`, no restart loops continue to run (restart logic is disabled).
  - Tests MUST NOT rely on `_fallback_thread`; fallback is driven purely by AudioPump ticks per [M25].

