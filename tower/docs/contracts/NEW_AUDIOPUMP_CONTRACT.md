# AudioPump Contract

## A. Purpose

The purpose of **AudioPump** is to be the single global metronome of the Tower system and to drive the audio processing pipeline at a fixed tick interval.

**AudioPump:**

- Owns the system clock tick
- Calls into `EncoderManager` once per tick
- Pushes the chosen PCM frame into the downstream buffer that ultimately feeds `FFmpegSupervisor`

AudioPump does not decide whether to send program, silence, or tone; it simply executes the tick loop and delegates that decision to `EncoderManager`.

---

## B. Relationship to Core Timing

### A1
AudioPump **MUST** use the tick interval implied by the canonical PCM frame defined in `NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md` (i.e., one tick per PCM frame).

### A2
AudioPump **MUST** assume the PCM frame format defined there (48kHz, stereo, 1024 samples per frame, 4096 bytes), and **MUST NOT** invent its own PCM shape.

### A3
AudioPump **MUST NOT** invent or use a different tick interval for any part of the system.

---

## C. Tick Loop Responsibilities

### A4
AudioPump **MUST** run a periodic loop at that global tick interval (currently ≈21.333ms for 1024-sample frames at 48kHz), and **MUST NOT** redefine the cadence independently of the Core Timing contract.

### A5
On each tick, AudioPump **MUST**:

1. **A5.1** — Attempt to obtain at most one PCM frame from the upstream PCM input buffer (may be absent for this tick)
2. **A5.2** — Pass the obtained frame (or `None` if absent) into `EncoderManager`
3. **A5.3** — Receive from `EncoderManager` exactly one PCM frame (program, silence, or tone)
4. **A5.4** — Push that PCM frame into the downstream PCM → FFmpeg pipeline (e.g., ring buffer / queue) consumed by `FFmpegSupervisor`

### A6
AudioPump **MUST** ensure that the call into `EncoderManager` occurs exactly once per tick and that exactly one PCM frame is emitted per tick.

---

## D. No Routing Logic

### A7
AudioPump **MUST NOT**:

- Decide whether to send program, silence, or tone
- Implement grace period timing
- Generate silence or tone frames

### A8
AudioPump **MUST NOT**:

- Call `write_pcm()` / `write_fallback()` on `EncoderManager` or `Supervisor` directly
- Inspect audio content beyond what is necessary to pass PCM through

### A9
All decisions about source selection (program vs silence vs tone) are owned by `EncoderManager` and **MUST NOT** be duplicated inside AudioPump.

---

## E. Interaction with Other Components

### A10
AudioPump **MUST** be constructed with:

- A reference to the upstream PCM input buffer (from the MP3 decoder / upstream feeder)
- A reference to `EncoderManager`
- A reference (directly or indirectly) to the downstream PCM buffer feeding `FFmpegSupervisor`

### A11
AudioPump **MUST NOT** hold references to:

- FFmpeg process objects
- HTTP connection objects
- Any networking primitives

---

## F. Error Handling

### A12
If `EncoderManager` raises unexpected errors, AudioPump **MAY**:

- Log the error
- Replace the emitted frame with silence for that tick
- Continue ticking on subsequent intervals

### A13
AudioPump **MUST** never stop ticking solely because upstream PCM is absent; it **MUST** continue calling `EncoderManager` each tick.

---

## LOG — Logging and Observability

### LOG1 — Log File Location
AudioPump **MUST** write all log output to `/var/log/retrowaves/tower.log`.

- Log file path **MUST** be deterministic and fixed
- Log file **MUST** be readable by the retrowaves user/group
- AudioPump **MUST NOT** require elevated privileges at runtime to write logs

### LOG2 — Non-Blocking Logging
Logging operations **MUST** be non-blocking and **MUST NOT** interfere with tick loop timing.

- Logging **MUST NOT** block the tick loop
- Logging **MUST NOT** introduce timing drift or jitter
- Logging **MUST NOT** delay calls to `EncoderManager`
- Logging **MUST NOT** delay PCM frame emission
- Logging failures **MUST** degrade silently (stderr fallback allowed)

### LOG3 — Rotation Tolerance
AudioPump **MUST** tolerate external log rotation without crashing or stalling.

- AudioPump **MUST** assume logs may be rotated externally (e.g., via logrotate)
- AudioPump **MUST** handle log file truncation or rename gracefully
- AudioPump **MUST NOT** implement rotation logic in application code
- AudioPump **MUST** reopen log files if they are rotated (implementation-defined mechanism)
- Rotation **MUST NOT** cause tick loop interruption

### LOG4 — Failure Behavior
If log file write operations fail, AudioPump **MUST** continue ticking normally.

- Logging failures **MUST NOT** crash the process
- Logging failures **MUST NOT** interrupt the tick loop
- Logging failures **MUST NOT** interrupt PCM frame production
- AudioPump **MAY** fall back to stderr for critical errors, but **MUST NOT** block on stderr writes

---

## Required Tests

This contract requires the following logging compliance tests:

- LOG1 — Log File Location
- LOG2 — Non-Blocking Logging
- LOG3 — Rotation Tolerance
- LOG4 — Failure Behavior

See `tests/contracts/LOGGING_TEST_REQUIREMENTS.md` for test specifications.
