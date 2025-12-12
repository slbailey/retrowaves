# FFmpegSupervisor Contract

## S. Purpose

**FFmpegSupervisor** is a dumb, robust process wrapper around an ffmpeg encoder process. Its sole purpose is to:

- Accept a continuous PCM frame stream
- Feed that PCM to ffmpeg
- Expose the encoded MP3 stream to the rest of Tower
- Monitor and restart ffmpeg as needed

FFmpegSupervisor **NEVER** decides what audio content to encode.

---

## T. Responsibilities

### F1
FFmpegSupervisor **MUST**:

- Start the ffmpeg process with the correct input and output arguments
- Provide an API to push PCM frames into ffmpeg's stdin or input pipe
- Monitor the ffmpeg process for exit, crash, or error conditions
- Restart ffmpeg according to policy if it exits unexpectedly

### F2
FFmpegSupervisor **MUST**:

- Accept PCM frames at the tick frequency defined in core timing
- Not block the `AudioPump` / `EncoderManager` tick loop

### F2.1
FFmpegSupervisor **MUST** accept PCM frames exactly matching the format defined in the Core Timing & Formats contract.

This ensures the supervisor contract never drifts if core timing evolves.

---

## U. No Audio Decisions

### F3
FFmpegSupervisor **MUST NOT**:

- Decide when to send silence, tone, or program
- Implement grace periods or fallback state machines
- Inspect PCM to deduce content type

### F4
FFmpegSupervisor **MUST** treat all incoming PCM frames as equally valid, and **MUST** encode them as-is.

> All audio source decisions are made by `EncoderManager`.

---

## V. Process Lifecycle

### F5
On initialization, FFmpegSupervisor **MUST**:

- Start ffmpeg in a mode that reads PCM frames of the format defined in core timing
- Ensure ffmpeg is ready to consume data before frames are pushed
- Accept PCM frames exactly matching the format defined in the Core Timing & Formats contract (per F2.1)

### F6
If ffmpeg exits or crashes:

- **F6.1** — FFmpegSupervisor **MUST** log the event
- **F6.2** — It **MUST** attempt a restart according to configurable policy (e.g., exponential backoff)
- **F6.3** — It **MUST** expose its health status to `TowerRuntime` / observability

---

## W. Interface Contract

### F7
FFmpegSupervisor **MUST** expose a method (or equivalent API) such as:

```python
push_pcm_frame(frame: bytes)  # called once per tick with a full PCM frame
```

### F8
`push_pcm_frame` **MUST**:

- Accept a frame of exactly the size defined by core timing
- Enqueue or write this frame to ffmpeg's input without blocking the caller beyond reasonable backpressure

### F9
FFmpegSupervisor **MUST** expose the MP3 output via:

- A file descriptor, pipe, or in-memory stream that `TowerRuntime` or `TOWER_ENCODER` will read and serve to HTTP clients

### F9.1
MP3 packetization is handled entirely by FFmpeg; no packetizer contract required.

---

## X. Error Handling and Backpressure

### F10
If ffmpeg's input pipe is temporarily blocked:

- FFmpegSupervisor **MUST** handle local buffering or drop frames according to configured policy
- It **MUST NOT** cause `AudioPump` to stop ticking

### F11
FFmpegSupervisor **MUST NOT** attempt to regulate upstream send rates; global rate control is handled by the buffer and `TowerRuntime`'s status endpoint, not by the Supervisor.

### F12
FFmpegSupervisor **MUST** sustain PCM write throughput at or above PCM cadence rate without introducing drift or buffering delays.

This protects against subtle "pipe buffering stalls" in implementations.

### F13
During **RESTARTING**, `push_pcm_frame` **MUST NOT** block.

Frames **MAY** be dropped if ffmpeg is not ready to receive input.

This keeps AudioPump real-time.

### F14
FFmpegSupervisor **MUST** detect the first MP3 frame to transition external state from **BOOTING**/**RESTARTING** → **RUNNING**.

This codifies the meaning of "first frame."

### F15
Supervisor **MUST** continuously drain ffmpeg stdout/stderr using non-blocking background threads.

This ensures stdout/stderr do not block the ffmpeg process or cause pipe buffer overflows.

---

## Y. Self-Healing Expectations

### F-HEAL1
Supervisor **MUST** restart ffmpeg after crash or exit.

### F-HEAL2
Supervisor **MUST** apply restart rate limiting to avoid "thrash crashes."
(Default: exponential backoff or max one restart per second.)

### F-HEAL3
Supervisor health **MUST NOT** block AudioPump or EM.

### F-HEAL4
EM **MUST** continue providing frames even while ffmpeg is restarting.

---

## Z. External vs Internal States

### Cold Boot Semantics

External state **MUST** be:

**STARTING → BOOTING → RUNNING**

**BOOTING** is externally visible only during initial process creation.

### Restart Semantics

When a failure occurs (EOF, stall, timeout, broken pipe):

External transition **MUST** be:

**RUNNING → RESTARTING → RUNNING**

**BOOTING MUST NOT** be exposed externally during restarts.

Internally, Supervisor may enter **BOOTING** while launching the new process,
but external state **MUST** remain **RESTARTING** until first MP3 frame is received.

### Rationale

Downstream systems treat **RESTARTING** as an "intermediate degraded state."

**BOOTING** is reserved exclusively for initial cold-start visibility.

Masking internal **BOOTING** under external **RESTARTING** ensures:

- Deterministic transitions
- No state flicker
- No race conditions in state observation
- Contract compliance with S13.2, S13.7, S21.1
- Compatibility with tower runtime and encoder manager expectations

### State Transition Table

| Event | Internal State | External State |
|-------|---------------|----------------|
| First startup | BOOTING | BOOTING |
| First MP3 frame | RUNNING | RUNNING |
| Failure occurs | RESTARTING | RESTARTING |
| Restart new process | BOOTING | RESTARTING |
| New MP3 frame | RUNNING | RUNNING |

### S13.8.1
**External BOOTING Visibility Rule**

**BOOTING** is externally visible only during cold startup and **MUST NOT** be externally visible during restart sequences.

During restarts, the Supervisor **SHALL** internally enter **BOOTING** while launching the replacement process, but external state **SHALL** remain **RESTARTING** until the first MP3 frame is produced.

---

## LOG — Logging and Observability

### LOG1 — Log File Location
FFmpegSupervisor **MUST** write all log output to `/var/log/retrowaves/ffmpeg.log`.

- Log file path **MUST** be deterministic and fixed
- Log file **MUST** be readable by the retrowaves user/group
- FFmpegSupervisor **MUST NOT** require elevated privileges at runtime to write logs

### LOG2 — Non-Blocking Logging
Logging operations **MUST** be non-blocking and **MUST NOT** interfere with PCM frame processing.

- Logging **MUST NOT** block `push_pcm_frame()` calls
- Logging **MUST NOT** delay PCM writes to ffmpeg stdin
- Logging **MUST NOT** block process monitoring or restart logic
- Logging **MUST NOT** affect MP3 output availability
- Logging failures **MUST** degrade silently (stderr fallback allowed)

### LOG3 — Rotation Tolerance
FFmpegSupervisor **MUST** tolerate external log rotation without crashing or stalling.

- FFmpegSupervisor **MUST** assume logs may be rotated externally (e.g., via logrotate)
- FFmpegSupervisor **MUST** handle log file truncation or rename gracefully
- FFmpegSupervisor **MUST NOT** implement rotation logic in application code
- FFmpegSupervisor **MUST** reopen log files if they are rotated (implementation-defined mechanism)
- Rotation **MUST NOT** cause PCM processing interruption
- Rotation **MUST NOT** cause ffmpeg process restart

### LOG4 — Failure Behavior
If log file write operations fail, FFmpegSupervisor **MUST** continue processing PCM frames normally.

- Logging failures **MUST NOT** crash the process
- Logging failures **MUST NOT** interrupt PCM frame processing
- Logging failures **MUST NOT** interrupt ffmpeg process management
- FFmpegSupervisor **MAY** fall back to stderr for critical errors, but **MUST NOT** block on stderr writes

---

## Required Tests

This contract requires the following logging compliance tests:

- LOG1 — Log File Location
- LOG2 — Non-Blocking Logging
- LOG3 — Rotation Tolerance
- LOG4 — Failure Behavior

See `tests/contracts/LOGGING_TEST_REQUIREMENTS.md` for test specifications.
