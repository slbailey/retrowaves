# Contract: FFMPEG_SUPERVISOR

This contract defines the behavior of the FFmpeg encoder supervisor, which monitors encoder health and ensures continuous MP3 output.

**IMPORTANT:** FFmpegSupervisor is an **internal component** owned exclusively by EncoderManager. External components (AudioPump, TowerService, etc.) must **never** access FFmpegSupervisor directly. All interaction must go through EncoderManager's public interface.

## 1. Core Invariants

- [S1] Encoder is considered **"live"** only when all liveness criteria are met (see [S2]–[S6]).
- [S2] Supervisor must **restart encoder** on any liveness failure and log the error reason.
- [S3] Supervisor must **never block** the output path (MP3 frame delivery).
- [S4] Supervisor must **preserve MP3 buffer contents** during restarts.

## 2. Liveness Criteria

An encoder is considered "live" when **all** of the following are true:

- [S5] **Process starts successfully**: FFmpeg subprocess is created and `poll()` returns `None` (process is running).
- [S6] **Stderr output is captured**: A dedicated stderr drain thread is running and logging all FFmpeg error/warning messages line-by-line with `[FFMPEG]` prefix.
- [S6A] **BOOTING state**: Startup introduces a new encoder state: BOOTING. BOOTING → RUNNING only after first MP3 frame received. BOOTING timeout governed by `TOWER_FFMPEG_STARTUP_TIMEOUT_MS` per [S7A].
- [S7] **First MP3 frame arrival**: Encoder SHOULD produce first MP3 frame rapidly (~500ms target). If no frame arrives by 500ms → log LEVEL=WARN "slow startup". This is not a restart condition.
- [S7A] **Hard startup timeout**: A hard startup timeout MUST exist and be configurable:
  - ENV: `TOWER_FFMPEG_STARTUP_TIMEOUT_MS`
  - DEFAULT: 1500ms
  - If timeout exceeded → trigger restart per [S13].
- [S7B] First-frame timer MUST use wall-clock time, not frame timestamps or asyncio loop time.
🔥 S7.1 – Encoder Boot Admission Rules

- [S7.1A] BOOTING state begins when ffmpeg is launched.
- [S7.1B] EncoderManager + Supervisor MUST feed PCM every frame during BOOTING.
- [S7.1C] Silence is the default input during BOOTING.
- [S7.1D] Continuous feed prevents starvation but DOES NOT imply RUNNING.
- [S7.1E] **RUNNING Transition Requirement**: RUNNING MUST NOT be entered until first MP3 frame is detected on stdout. Supervisor must promote state → RUNNING only after first MP3 frame observed, NOT after boot start. The transition occurs in `_stdout_drain()` when the first complete MP3 frame is received from the packetizer.
- [S7.1F] If MP3 is not observed before startup timeout → RESTARTING.
- [S7.1G] After max restarts → FAILED, continuity maintained via silence.
- [S8] **Continuous frames are received**: After the first frame, subsequent frames arrive within `FRAME_INTERVAL` tolerance (default 24ms for 1152-sample frames at 48kHz, with tolerance of ±50% = 12ms to 36ms between frames).

## 3. Failure Detection

- [S9] **Process failure**: Detected when `process.poll() != None` (process exited). Immediate exit detection MUST NOT skip BOOTING. After BOOTING is reached, failure may trigger restart per [S13]. During STARTING, failure handling MUST be deferred per [S19.14].
- [S10] **Startup timeout**: Detected when first MP3 frame does not arrive within the hard startup timeout per [S7A] (`TOWER_FFMPEG_STARTUP_TIMEOUT_MS`, default 1500ms). On startup timeout exceeding the configured maximum startup window, restart per [S13].
- [S11] **Stall detection**: Detected when no MP3 frames are received for `TOWER_ENCODER_STALL_THRESHOLD_MS` (default 2000ms) after the first frame.
- [S12] **Frame interval violation**: Detected when time between consecutive frames exceeds `FRAME_INTERVAL * 1.5` (150% of expected interval).

## 4. Restart Behavior

- [S13] On any liveness failure ([S9]–[S12], [S7A]), supervisor must:
  - [S13.1] Log the specific failure reason (process exit code, timeout type, stall duration, etc.).
  - [S13.2] Transition encoder state to `RESTARTING`.
  - [S13.3] Preserve MP3 buffer contents (do not clear).
  - [S13.3B] During restart, MP3 output MUST remain continuous — Supervisor restarts MUST NOT stall or block the broadcast loop.
  - [S13.3C] Frame delivery MUST continue from existing buffer during restart until new frames arrive. Fallback/silence may be injected upstream if buffer depletes, but output MUST NOT stop.
  - [S13.4] Follow exponential backoff schedule (`TOWER_ENCODER_BACKOFF_MS`).
  - [S13.5] Attempt restart up to `TOWER_ENCODER_MAX_RESTARTS` times.
  - [S13.6] Enter `FAILED` state if max restarts exceeded.
  - [S13.7] **Thread Safety Requirements**:
      - All state transitions must be thread-safe and use `_state_lock`.
      - Any method holding `_state_lock` MUST NOT call another method that also acquires `_state_lock`.
      - State assignments must release the lock *before* invoking callbacks or restart logic.
      - State change callbacks MUST run strictly **outside** the lock to prevent recursive lock deadlocks.
  - [S13.8] Restart startup sequence: On each restart, after a new FFmpeg process is spawned, the supervisor MUST follow the same logical startup sequence defined in [S19]:
      - Immediately transition to BOOTING state (not RUNNING) once the spawn attempt has completed.
      - Start the 500ms first-frame timer as in [S7], using wall-clock time per [S7B].
      - Only transition to RUNNING after at least one complete MP3 frame has been received within the startup window.
      - RESTARTING state covers the window between detecting a failure and successfully spawning the replacement process. Once the new process is spawned, state MUST become BOOTING, not RUNNING, until [S7] is satisfied.
  - [S13.8A] **Observable restart state sequence**:
      - For each restart attempt, the externally observable state sequence MUST include a transition through BOOTING after RESTARTING, even if the newly spawned process fails immediately:
        - `… → RESTARTING → BOOTING → (RUNNING | RESTARTING | FAILED)`
      - Tests MAY rely on BOOTING being visible (even briefly) before any subsequent failure handling transitions the supervisor back to RESTARTING or FAILED.
      - This requirement does NOT imply any special failure deferral in BOOTING beyond [S19.14]; failures detected after BOOTING is reached MUST still be handled immediately by [S13].
  - [S13.9] On any unexpected ffmpeg exit — including during BOOTING — the supervisor MUST enter RESTARTING state before scheduling the restart or attempting a new launch. During a restart attempt, the state machine MUST still emit the sequence RESTARTING → BOOTING → … per [S13.8A]; "immediately" here means "as soon as that sequence is satisfied", not "prior to BOOTING being observable". This ensures failures are processed promptly while maintaining the observable state sequence required by [S13.8A].
  - [S13R] On restart, FFmpegSupervisor MUST transition states in order:
    - RUNNING → RESTARTING → BOOTING → RUNNING
    - This sequence MUST be encapsulated and observable to EncoderManager via callback.
    - Tests MAY rely on this complete state sequence being visible during restart operations.

## 5. Stderr Capture

- [S14] Stderr drain thread must:
  - [S14.1] After a new FFmpeg process is created, the supervisor MUST start both a stdout drain thread and a stderr drain thread without undue delay. The contract does not require a strict ordering between them; it only requires that both be running while the process is in BOOTING or RUNNING state.
  - [S14.2] Stderr file descriptor must be set to non-blocking mode (same as stdout) to ensure reliable capture, especially when FFmpeg exits quickly.
  - [S14.3] Use `readline()` in a continuous loop: `for line in iter(proc.stderr.readline, b'')`.
  - [S14.4] Log each line with `[FFMPEG]` prefix: `logger.error(f"[FFMPEG] {line.decode(errors='ignore').rstrip()}")`.
  - [S14.5] Never block the main thread (runs as daemon thread).
  - [S14.6] Continue reading until stderr closes (process ends).
  - [S14.7] Implementations are free to start stdout and stderr drain threads in any order, so long as:
      - Both threads are started promptly after process creation and before the encoder is considered fully live per [S6A]/[S7].
      - Stopping either thread MUST NOT block process termination (threads MUST be daemon threads or joined with bounded timeouts; no unbounded joins on shutdown).
      The intent is that stdout and stderr are continuously drained for the lifetime of the process, but thread start/stop mechanics MUST NEVER jeopardize shutdown or restart behavior.

## 6. Frame Timing

- [S15] Frame interval is calculated as: `FRAME_INTERVAL = FRAME_SIZE_SAMPLES / SAMPLE_RATE` (1152 / 48000 = 0.024s = 24ms).
- [S16] Tolerance window: frames are considered "on time" if received within `FRAME_INTERVAL * 0.5` to `FRAME_INTERVAL * 1.5` (12ms to 36ms).
- [S17] Supervisor tracks the timestamp of the last received frame and calculates elapsed time since last frame.
- [S18] If elapsed time exceeds `FRAME_INTERVAL * 1.5`, supervisor logs a warning and may trigger restart if persistent.

## 7. Startup Sequence

- [S19] Supervisor startup sequence:
  The "startup sequence" applies both to the initial encoder start and to each restart attempt triggered under [S13]. For every new FFmpeg process (initial or restart), the supervisor MUST:
  1. **Test isolation check per [I25]**: Before spawning process, MUST check if running in non-integration test environment. If FFmpeg would be started in a test not marked as integration test, MUST raise RuntimeError with clear message per [I25]. See [S19.12] for details.
  2. Spawn the process (Popen).
  3. Log process PID: `logger.info(f"Started ffmpeg PID={process.pid}")`.
  4. Write initial silence frame to stdin to keep FFmpeg alive.
  5. Set stdin, stdout, and stderr file descriptors to non-blocking mode.
  6. Start the stdout drain thread and stderr drain thread as soon as their corresponding pipes are available. The contract does not impose a strict ordering between them; see [S14.1] and [S14.7].
  7. Begin BOOTING state and start the 500ms first-frame timer per [S6A] and [S7], using wall-clock time per [S7B].
  8. Monitor for first MP3 frame arrival.
  9. If no frame arrives by 500ms → log LEVEL=WARN "slow startup" per [S7] (not a restart condition).
  10. If first frame arrives within hard timeout → transition to RUNNING state per [S6A], encoder is "live".
  11. If timeout exceeds hard timeout per [S7A] → treat as failure per [S10]/[S9]/[S13].
- [S19.4] **Supervisor MUST accept priming burst without terminating**: Supervisor MUST accept the priming burst (per [S7.3]) without terminating the FFmpeg process. The supervisor MUST NOT treat the priming burst as an error condition or cause process termination. The priming burst is a required part of the startup sequence and must be handled gracefully.
- [S19.11] Because raw PCM has no headers, FFmpeg MUST be instructed to begin MP3 encoding without waiting for `avformat_find_stream_info()`. The encoding command MUST include:
  - `-frame_size 1152`
  This forces MP3 packetization at correct Tower frame boundaries and guarantees first-frame emission within the configured startup timeout [S7]. Without this flag, FFmpeg may wait indefinitely in PROBE phase, causing startup timeout and continuous supervisor restarts.
- [S19.12] **Test Isolation Enforcement per [I25]**:
  - Test isolation check MUST occur in `_start_encoder_process()` before `subprocess.Popen()` is called (step 1 of [S19]).
  - FFmpegSupervisor MUST accept `allow_ffmpeg` parameter in constructor (default: False for test safety).
  - FFmpeg startup is allowed ONLY if:
    - `allow_ffmpeg=True` is passed to constructor (production code sets this), OR
    - Environment variable `TOWER_ALLOW_FFMPEG_IN_TESTS=1` is set (test override).
  - **Enforcement Mechanism (Implementor Guidance)**: The enforcement of [I25] SHALL be implemented as a single explicit allow/block check, not test-environment introspection or automatic test detection. The Supervisor must honor `allow_ffmpeg` or environment flag before spawning a process.
  - Production code MUST NOT detect test context through heuristics. Test harness controls allowance via DI.
  - If FFmpeg would start without permission, MUST raise RuntimeError with clear message referencing [I25].
  - RuntimeError from test isolation check MUST propagate (not be caught and swallowed) per [I25].
  - This ensures tests fail loudly when FFmpeg is started inappropriately, while allowing explicit opt-in.
- [S19.13] **Supervisor start() completion guarantee**:
  Supervisor.start() MUST synchronously transition to BOOTING before returning, regardless of ffmpeg exit timing. Upon return from `start()`, the supervisor state as observable via `get_state()` MUST be BOOTING (not RESTARTING and not FAILED), regardless of any asynchronous stderr/stdout events during initialization. Subsequent failure detection may transition the state away from BOOTING immediately after `start()` returns, but callers are guaranteed to see BOOTING at least once.
- [S19.14] **Deferred failure handling during STARTING and before BOOTING**:
  - If ffmpeg exits during STARTING or before first-frame detection, failure handling MUST be deferred until after BOOTING state is set.
  - Exit detection MUST NOT override BOOTING during STARTING. Failure must be queued/deferred until BOOTING has been observed.
  - `start()` MUST complete the transition to BOOTING first per [S19.13]. After state has become BOOTING (and `start()` has returned), any deferred failures MUST be processed immediately, transitioning to RESTARTING or FAILED according to [S13].
  - Once BOOTING is visible → normal restart rules apply. This deferral rule applies ONLY while `state == STARTING` in the initial startup. It MUST NOT be applied to the BOOTING state or to restart attempts. During BOOTING and all restarts, failures (including EOF, process_exit, and startup_timeout) MUST be handled immediately by [S13].
- [S19.15] **Method boundary neutrality**: The startup sequence in [S19] specifies observable behavior, not internal method boundaries. Implementations MAY distribute these steps across `start()`, `_start_encoder_process()`, restart workers, or other helpers, provided that:
  - From the outside, the sequence of process spawn, initial silence write, non-blocking configuration, drain-thread startup, BOOTING state entry, and first-frame timing behaves as specified.
  - Tests MUST target the behavior (state transitions, timing, logging, restart semantics), not the presence of a specific private method or call graph.
  - This is important for keeping your "contract → tests → implementation" discipline while still allowing refactors (like moving thread start logic between `start()` and `_restart_worker`) without rewriting the contract every time.
- [S19.16] **Drain thread ordering before initial PCM write**: The supervisor MUST attach stdout/stderr drain threads BEFORE writing initial PCM into stdin. Rationale: FFmpeg output buffers can deadlock or close early if no reader is attached, causing firmware-level shutdown. This requirement ensures that both stdout and stderr drain threads are running and actively reading from their respective pipes before any PCM data is written to stdin. The ordering MUST be: (1) Process spawned, (2) Stdout drain thread started, (3) Stderr drain thread started, (4) Initial silence frame written to stdin. This applies to both initial startup and restart sequences per [S13.8].

### 7.1 Operational Mode Integration (cross-referenced with ENCODER_OPERATION_MODES.md)

**Note:** Supervisor is source-agnostic and does not distinguish between silence, tone, or live PCM. The operational mode transitions below occur at the EncoderManager/AudioPump layer, not within the supervisor.

| Supervisor State | Operational Mode |
|------------------|------------------|
| BOOTING → first frame (from silence/tone/live PCM) | RUNNING → maps to operational mode based on PCM source |
| BOOTING → first frame (silence during grace) | RUNNING → operational mode determined by EncoderManager (typically BOOTING [O2] until grace expires) |
| BOOTING → first frame (live PCM arrives) | RUNNING → LIVE_INPUT [O3] |
| RUNNING (any PCM source) | Operational mode determined by EncoderManager based on PCM source availability |

🔥 S7.2 – PCM Continuity Rules

- [S7.2] **Continuous Feed Requirement**: FFmpeg must receive a PCM frame at every FRAME_INTERVAL without exception. No gaps, no conditional pauses, no "wait for audio to arrive". Silence must always be available as fallback. Violation → restart behavior is permitted, but only after feed requirements are satisfied.
  - **During BOOTING state**: EncoderManager.next_frame() MUST provide continuous PCM frames (typically silence frames) at FRAME_INTERVAL cadence until real PCM becomes available. Supervisor only writes what it is given. This ensures FFmpeg receives a steady stream of data during startup, preventing encoder starvation or initialization failures.

- [S7.2A] **Allowed PCM Sources**: The Supervisor may receive PCM from only these providers:
  - Station PCM (primary)
  - Tone Generator (fallback)
  - Silence Generator (base fallback)
  - Other sources prohibited.

- [S7.2B] **Selection Hierarchy (strict priority)**: The PCM source selection hierarchy (Station PCM > Tone > Silence) is enforced in EncoderManager, not in Supervisor. At every tick, EncoderManager MUST select PCM using this exact rule:
  - If Station PCM available → use Station PCM
  - Else if fallback_mode == TONE → use Tone
  - Else → use Silence
  - This hierarchy is stable, stateless per tick, and no special-case branches may bypass it.
  - Supervisor receives already-selected frames and MUST NOT override or modify the selection priority.

- [S7.2C] **Boot-State Agnostic Behavior**: The PCM selection rules (enforced in EncoderManager) apply identically whether Supervisor is:
  - BOOTING
  - RUNNING
  - RESTARTING (during process spawn)
  - FAILED
  - Supervisor forwards frames regardless of its state; selection priority is determined upstream in EncoderManager.

- [S7.2D] **Silence During Startup**: During BOOTING:
  - Silence is valid default PCM source
  - It must continue until first Station PCM OR tone fallback triggers
  - Silence must not stop once initial frame is written
  - (Single-frame silence is noncompliant.)

- [S7.2E] **Fallback Tone Activation Rule**: Tone may activate only if:
  - Supervisor is RUNNING
  - AND station PCM is unavailable
  - AND grace window has expired
  - Tone must not be used in BOOTING unless explicitly contracted later.

- [S7.2F] **Zero PCM Availability Never Halts Feed**: If Station PCM missing and tone generator not operational:
  - Feed = Silence (mandatory)
  - FFmpeg must still receive data.

- [S7.2G] **Minimum Sustained Feed Duration During BOOTING**: A single burst is NOT sufficient. During BOOTING, the supervisor MUST maintain a minimum sustained feed duration of ≥5 frames at FRAME_INTERVAL cadence for test simulation continuity. This requirement ensures that the continuous feed mechanism is properly established and can be verified by tests that wait for multiple frame intervals. The sustained feed must continue until real PCM becomes available or the supervisor transitions to RUNNING state.
  - **Clarification**: Minimum sustained feed (S7.2G) is evaluated at the system level, not enforced by Supervisor internally. Supervisor's compliance means accepting sustained PCM without blocking. Supervisor does not generate frames; it receives frames from EncoderManager and forwards them to FFmpeg. The ≥5 frame requirement is verified by tests that observe system behavior, not by Supervisor's internal logic.

- [S7.2H] **Seamless Transition to Live PCM**: Transition to live PCM must happen without a timing gap ≥1 FRAME_INTERVAL. When Station PCM becomes available during BOOTING, EncoderManager.next_frame() MUST switch from silence frames to live PCM frames within the same FRAME_INTERVAL window, and Supervisor MUST write the frames it receives without delay, ensuring no gap in the continuous feed. The transition must be immediate and must not cause any delay that would violate the continuous feed requirement per [S7.2].

- [S7.2I] **Continuous feed requirement is fulfilled by EncoderManager+AudioPump, not internally by Supervisor**: Supervisor may not generate PCM. It only writes what it is given.

🔥 S7.3 – Encoder Boot Priming Requirements

**Purpose**: Guarantee FFmpeg receives enough PCM during startup to initialize the MP3 encoder and emit first frame before timeout.

- [S7.3] **Boot Priming is Mandatory During BOOTING**: Boot priming is mandatory during BOOTING. System MUST write ≥N PCM frames within T ms of BOOTING state entry (where T = 50ms per [S7.3D] requirement #2). System MUST complete priming before first PCM routing decision.

- [S7.3A] **Priming Trigger**: Priming occurs only when entering BOOTING state and before first FRAME_INTERVAL tick.

- [S7.3B] **Priming Content**: Priming frames follow the selection hierarchy defined in [S7.2B].

- [S7.3C] **Burst Size**: A minimum of N PCM frames MUST be written back-to-back without delay to pre-fill FFmpeg input buffers.
  - N initially fixed = 5 frames
  - Value becomes tunable later but contract requires ≥1 frame and enough to meet encoder startup needs

- [S7.3D] **Priming Burst Timing Requirements**:
  1. Boot priming MUST write ≥N frames back-to-back with no intentional sleep.
  2. The total priming burst MUST complete within 50ms of entering BOOTING.
  3. The interval between writes MAY exceed 1ms for the FIRST interval only, due to FFmpeg cold-start initialization and OS pipe wake-up.
  4. All subsequent intervals (writes 2→3, 3→4, ..., N-1→N) SHOULD be <5ms under normal scheduler conditions. A sub-millisecond interval is ideal but not required for correctness.
  5. Compliance is measured by burst completion time (requirement #2) and write immediacy (requirement #1), not strict microsecond precision.

- [S7.3E] **Continuous Feed After Priming**: After the priming burst completes, EncoderManager.next_frame() MUST continue providing PCM frames (typically silence frames) at FRAME_INTERVAL cadence without waiting for any external trigger or pipeline readiness event. A minimum of 2 post-priming frames MUST be provided within the normal write cadence (~20–30ms) following the burst. Supervisor only writes what it is given. This ensures:
  - Priming burst = rapid ≤1ms writes
  - Continuous feed resumes automatically via EncoderManager.next_frame()
  - First write occurs immediately after burst
  - ≥2 additional frames prove cadence resumed
  - **Note**: Continuous feed is maintained by EncoderManager+AudioPump. Supervisor must continue to accept/carry PCM writes uninterrupted. Per [S7.2] and [S7.4], continuous feed is guaranteed at the system level, and Supervisor's role is to forward PCM frames without blocking.

- [S7.3F] **Observability**: Supervisor MUST log:
  - start of priming
  - number of frames written
  - completion of priming
  - first MP3 frame observed OR startup timeout

- [S7.3G] **Testable Outcomes**:
  - **Boot success criteria**:
    - ffmpeg MUST remain alive past priming
    - First MP3 frame MUST appear before startup timeout
    - Supervisor MUST reach RUNNING if MP3 observed
  - **Boot failure criteria**:
    - If ffmpeg exits before priming completes → BOOTING → RESTARTING
    - If timeout hits without MP3 → startup_timeout failure
    - Restart attempts must follow existing restart contract

🔥 S7.4 – Cadence Source of Truth

- [S7.4] **PCM cadence MUST be driven exclusively by AudioPump**: PCM cadence MUST be driven exclusively by AudioPump calling EncoderManager.next_frame(). Supervisor MUST NOT generate timing-based writes. Silence threads are prohibited.
- [S7.4A] **Supervisor SHALL NOT operate a cadence or write silence autonomously**: Supervisor SHALL NOT operate a cadence or write silence autonomously. Continuous feed MUST originate from AudioPump → EncoderManager.write_pcm(). Supervisor.write_pcm(bytes) is sink-only.

## 8. Error Logging

- [S20] Supervisor must log all failure reasons:
  - Process exit: `"🔥 FFmpeg exited immediately at startup (exit code: {code})"`.
  - Slow startup (WARN): `"⚠ FFmpeg slow startup: first frame not received within 500ms"` per [S7] (not a restart condition).
  - [S20.1] On every successful RUNNING transition, log INFO "Encoder LIVE (first frame received)".
  - [S20.1A] **RUNNING-transition log emission MUST be atomic with state change**: The log emission required by [S20.1] MUST occur atomically with the state transition from BOOTING to RUNNING. Implementation may use a helper method to ensure this atomicity, but the contract guarantees behavior (log emission on every successful RUNNING transition), not method structure. The helper method is an implementation detail, not a contract requirement.
  - Startup timeout: `"🔥 FFmpeg did not produce first MP3 frame within {TOWER_FFMPEG_STARTUP_TIMEOUT_MS}ms"` per [S7A].
  - Stall: `"🔥 FFmpeg stall detected: {elapsed_ms}ms without frames"`.
  - Frame interval violation: `"🔥 FFmpeg frame interval violation: {elapsed_ms}ms (expected ~{FRAME_INTERVAL}ms)"`.
  - Stdin broken: `"🔥 FFmpeg stdin broken (exit code: {code})"`.
  - Stdout EOF: `"🔥 FFmpeg stdout EOF (exit code: {code})"`.
  - **When exit code is unavailable** (process killed, terminated abnormally, or race condition): Supervisor MUST log a clear message indicating the exit code is unknown, e.g. `"exit code: unknown - process may have been killed"` or similar wording that indicates the exit code could not be determined.
- [S20.2] **PCM flow during BOOTING**: During BOOTING, supervisor MUST receive PCM frames from AudioPump (via EncoderManager.write_pcm()) and MUST forward them to ffmpeg stdin without gaps longer than FRAME_INTERVAL. PCM frames must continue flowing during BOOTING regardless of whether the first MP3 frame has been received. The supervisor MUST NOT wait for the BOOTING → RUNNING transition before forwarding PCM frames; PCM flow is independent of the state transition and must be continuous.
- [S21] On process exit, supervisor must attempt to read and log all available stderr output before restarting.
- [S21.2] **Non-string stderr/exit log hygiene**:
  - Supervisor MUST defensively handle cases where `exit_code` or stderr data is not a plain string (e.g., unittest mocks). Logs MUST degrade gracefully without logging MagicMock representations.
- [S21.1] Exit code logging on stdout/stderr EOF and stdin failures:
  - On any failure where FFmpeg stdout reaches EOF or the process is detected as exited (poll() is not None), the supervisor MUST:
    - Attempt to retrieve and log the encoder process return code.
    - If the return code is unavailable (None) due to process being killed, terminated abnormally, or race conditions, the supervisor MUST log a clear message indicating the exit code could not be determined (e.g. "exit code: unknown - process may have been killed").
    - Log the failure type (eof, process_exit, stdin_broken, etc.).
    - Ensure that any available stderr output is captured either by:
      - The stderr drain thread, or
      - A one-shot _read_and_log_stderr() call if the stderr thread never started or has already exited.
  - **When a BrokenPipeError or equivalent stdin write failure occurs while feeding FFmpeg, the supervisor MUST:**
    - Attempt to retrieve and log the FFmpeg exit code (if available).
    - If exit code is unavailable, log a clear message indicating it could not be determined.
    - Include wording indicating an stdin failure, e.g. containing "stdin" or "broken".
    - This is in addition to any generic "ffmpeg exited immediately at startup (exit code: X)" messages.
  - **For state machine purposes, an EOF on stdout that indicates encoder termination MUST be treated as a liveness failure equivalent to `process_exit` and handled via [S13]:**
    - State MUST transition to RESTARTING or FAILED (per restart policy).
    - Implementations MUST NOT silently swallow EOF as a non-failure condition, even during BOOTING.
- [S21.3] **FFmpeg stderr diagnostics on spawn failure**: FFmpeg MUST produce diagnostic stderr output on spawn failure (e.g., when FFmpeg exits immediately due to invalid command, missing codec, or other startup errors). The supervisor MUST capture and expose this stderr output so that the exit reason is visible. When FFmpeg fails at startup, the supervisor MUST ensure stderr is read and made available (either via logging or through a queryable interface) before the process is considered failed. This enables debugging of FFmpeg startup failures by exposing the actual error messages from FFmpeg itself.

## 9. Public API Visibility

- [S22] FFmpegSupervisor methods are **internal-only**:
  - `write_pcm(frame: bytes)` → used internally by EncoderManager
  - `get_stdin() -> Optional[BinaryIO]` → **INTERNAL ONLY**, used by EncoderManager.write_pcm()
  - `get_state() -> SupervisorState` → used internally by EncoderManager
- [S22A] Supervisor MUST NOT know about noise/silence generation — it only handles PCM→MP3 encoding. Silence fallback is handled above at EncoderManager per Operational Modes contract. Supervisor is source-agnostic and MUST forward frames exactly as provided by EncoderManager without modifying priority or selection decisions.
- [S23] External components must **never** call FFmpegSupervisor methods directly:
  - AudioPump must call `encoder_manager.write_pcm()`, not `supervisor.write_pcm()`
  - TowerService must not access `supervisor.get_stdin()` or any supervisor methods
- [S24] `get_stdin()` exists for EncoderManager's internal use only (not part of public contract).

## 10. Debug Mode & PCM Validation Harness

To support deterministic debugging and avoid guess-driven changes, the encoder layer MUST provide:

1. A runtime **debug mode** for FFmpeg supervisor logging.
2. A standalone **PCM → MP3 validation harness** that uses the same FFmpeg flags as the Tower runtime.

### 10.1 Debug Mode (Supervisor-Level)

- [S25] Supervisor MUST support a debug mode controlled by environment variable `TOWER_ENCODER_DEBUG`.
  - [S25.1] When `TOWER_ENCODER_DEBUG=1`, supervisor MUST:
    - Run FFmpeg with `-loglevel debug` (or more verbose than the default runtime level).
    - Log the full FFmpeg command line once at startup (with any secrets redacted if applicable).
    - Log all stderr lines from FFmpeg at `DEBUG` level in addition to any existing ERROR/WARNING logs.
  - [S25.2] When `TOWER_ENCODER_DEBUG` is unset or `0`, supervisor MUST:
    - Use the normal runtime loglevel (e.g. `warning`).
    - Preserve existing behavior and performance characteristics.
  - [S25.3] Debug mode MUST NOT change functional behavior of the encoder (no different PCM handling, no timing changes, no retries). It ONLY affects:
    - FFmpeg verbosity.
    - Logging detail.

### 10.2 PCM Source Validation Harness

- [S26] Tower MUST provide a standalone PCM validation tool that:
  - Lives at: `tools/pcm_ffmpeg_test.py`.
  - Uses the **same FFmpeg audio flags** as FFmpegSupervisor (format, sample rate, channels, codec, bitrate, output container).
  - Streams Tower-format PCM frames (s16le, 48kHz, stereo, 1152 samples = 4608 bytes per frame) into FFmpeg via stdin.
  - Reads both stdout and stderr to determine whether FFmpeg:
    - Encodes valid MP3 frames.
    - Exits immediately (process failure).
    - Times out waiting for data.
    - Rejects input format or flags.
- [S26.1] The tool MUST provide a CLI interface:
  ```bash
  python tools/pcm_ffmpeg_test.py --silence
  python tools/pcm_ffmpeg_test.py --tone
  python tools/pcm_ffmpeg_test.py --file /path/to/input.wav   # optional future extension
  ```
  - `--silence`: Generate valid Tower-format silence frames (all zeros) and feed them continuously to FFmpeg.
  - `--tone`: Generate a 440Hz sine tone in Tower PCM format and feed continuously to FFmpeg.
  - `--file`: (Future enhancement) Read PCM or WAV and feed its decoded PCM as Tower-format frames.
- [S26.2] The tool MUST:
  - Spawn FFmpeg with the exact same audio pipeline as the supervisor, e.g.:
    ```bash
    ffmpeg -hide_banner -nostdin \
      -loglevel debug \
      -f s16le -ar 48000 -ac 2 -i pipe:0 \
      -c:a libmp3lame -b:a 128k \
      -frame_size 1152 \
      -f mp3 -fflags +nobuffer -flush_packets 1 -write_xing 0 pipe:1
    ```
  - Continuously read FFmpeg's stdout and:
    - Count valid MP3 bytes and/or frames produced.
  - Continuously read FFmpeg's stderr and:
    - Print all diagnostic messages to the console (with `[FFMPEG]` prefix).
- [S26.3] Exit behavior:
  - Exit with code 0 if:
    - FFmpeg remains running and produces at least one MP3 frame (or a minimum number of bytes) within a configurable timeout (e.g. 500ms–2s).
  - Exit with non-zero code if:
    - FFmpeg exits immediately.
    - No MP3 data is produced within the timeout window.
    - Input format is rejected.
    - Any unexpected exception occurs.
  - On failure, the tool MUST:
    - Print a final summary line, e.g.:
      - `FFmpeg exited with code 1 (no frames produced)`.
      - `Timeout: no MP3 output within 1000ms`.
      - `Startup error: {stderr_line}`.
- [S26.4] This tool is purely diagnostic:
  - It MUST NOT be imported or used by Tower runtime.
  - It exists to validate:
    - PCM format correctness.
    - FFmpeg flags correctness.
    - Environment compatibility (e.g. platform issues).
  - It is the canonical way to debug FFmpeg failures before changing Tower code.
- [S26.5] The PCM harness must include the same `-frame_size 1152` parameter as required by [S19.11] to ensure consistent behavior with the supervisor.
- [S26.6] The PCM validation harness proved FFmpeg is correct with the right flags. A supervisor startup without continuous PCM will cause timeout per [S7A]. PCM source selection (silence during grace, then tone after grace expires) is handled by AudioPump/EncoderManager, not the supervisor.

## 11. Operational Mode Mapping

- [S27] SupervisorState maps into Encoder Operational Modes (per ENCODER_OPERATION_MODES.md) as follows:
  - `STOPPED`/`STARTING` → [O1] COLD_START
  - `BOOTING` → [O2] BOOTING
  - `RUNNING` → [O3] LIVE_INPUT
  - `RESTARTING` → [O5] RESTART_RECOVERY
  - `FAILED` → [O7] DEGRADED
- [S28] Supervisor MUST NOT attempt to decide fallback behavior; fallback is handled at EncoderManager layer via Operational Modes.
- [S29] After restart spawn, Supervisor MUST enter BOOTING [O2], not RUNNING, until first MP3 frame is confirmed per [S13.8].
- [S30] Supervisor MUST continuously write frames it receives into buffer even if input is silence or tone (per [S7.1]). EncoderManager.next_frame() always provides something.

## 12. Shutdown Guarantees

- [S31] Supervisor Shutdown Guarantees:
  On `supervisor.stop()`:
  1. stdin/stdout/stderr drain threads MUST terminate (threads must exit cleanly, no hanging or blocking).
  2. FFmpeg process MUST be killed if alive (process must be terminated, not left running).
  3. Restart logic MUST be disabled (no further restart attempts may be scheduled or executed).
  4. No background threads may remain running (all threads associated with supervisor must be stopped).
  5. Shutdown MUST complete within 200ms in test mode (for deterministic test behavior, shutdown must be bounded in time).

## Required Tests

- `tests/contracts/test_tower_ffmpeg_supervisor.py` MUST cover:
  - [S5]–[S8]: Liveness criteria validation.
  - [S6A]: BOOTING state transitions.
  - [S7A]: Hard startup timeout configuration and enforcement.
  - [S7B]: First-frame timer uses wall-clock time.
  - [S9]–[S12]: Failure detection mechanisms.
  - [S13], [S13R]: Restart behavior and state transitions.
  - [S13.3B]–[S13.3C]: Restart continuity (MP3 output remains continuous, frame delivery continues from buffer).
  - [S14]: Stderr capture functionality.
  - [S14.7]: Stdout drain thread ordering and non-blocking termination.
  - [S15]–[S18]: Frame timing and interval validation.
  - [S19]: Startup sequence correctness.
  - [S19.12]: Test isolation enforcement per [I25].
  - [S19.13]: State guarantee on start() return (BOOTING state immediately after start() returns).
  - [S19.14]: Failure handling deferral during STARTING state.
  - [S20]–[S21]: Error logging completeness.
  - [S21.2]: Non-string stderr/exit log hygiene (MagicMock handling).
  - [S20.1]: INFO log on RUNNING transition.
  - [S22]–[S24]: Public API visibility (internal-only methods).
  - [S22A]: Process boundaries (Supervisor must not know about noise/silence generation).
  - [S25]: Debug mode behavior and environment variable handling.
  - [S26]: PCM validation harness functionality (if implemented as part of contract tests).
  - [S27]–[S30]: Operational mode mapping and behavior.
  - [S31]: Supervisor shutdown guarantees (thread termination, process kill, restart disable, timing).
  - New test expectations for [S31]:
    - `test_shutdown_leaves_no_supervisor_threads`: Verify that after `supervisor.stop()`, no background threads (stdin/stdout/stderr drain threads) remain running.


