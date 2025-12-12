# PCM Ingestion Contract

## I. Purpose

**PCM Ingestion** is the subsystem responsible for accepting canonical PCM frames from upstream providers (such as Station) and delivering them into Tower's upstream PCM buffer for processing by the audio pipeline.

PCM Ingestion:

- Accepts PCM frames via its configured ingest transport
- Validates frame format and atomicity
- Delivers valid frames to the upstream PCM buffer
- Discards malformed or incomplete frames safely

PCM Ingestion does not decide audio content, apply transformations, or generate fallback audio; it is a pure transport layer that delivers frames from upstream providers to Tower's processing pipeline.

---

## II. Ingest Responsibilities

### I1
PCM Ingestion **MUST** accept canonical PCM frames via its configured ingest transport mechanism.

### I2
PCM Ingestion **MUST** deliver each valid frame into the upstream PCM buffer immediately upon receipt and validation.

### I3
PCM Ingestion **MUST** drop malformed frames safely without crashing or corrupting system state.

### I4
PCM Ingestion **MUST** accept frames continuously without blocking the metronome tick (AudioPump) or EncoderManager operations.

### I5
PCM Ingestion **MUST** preserve frame atomicity: frames are delivered as complete units or not at all.

### I6
PCM Ingestion **MUST** preserve frame ordering per connection: frames from a single upstream provider **MUST** be delivered in the order received.

---

## III. Frame Format Requirements

### I7
PCM Ingestion **MUST** accept frames that conform to the canonical PCM format:

- **Frame size**: Exactly **4096 bytes** (1024 samples × 2 channels × 2 bytes per sample)
- **Sample rate**: 48,000 Hz
- **Channels**: 2 (stereo)
- **Bit depth**: 16-bit signed PCM
- **Byte order**: Little endian

### I8
PCM Ingestion **MUST** reject frames that do not match the exact frame size requirement (4096 bytes).

### I9
PCM Ingestion **MUST NOT** attempt to repair broken, truncated, or corrupted frames.

### I10
PCM Ingestion **MUST NOT** accept partial frames; frames **MUST** be atomically delivered as complete 4096-byte units.

### I11
PCM Ingestion **MUST** validate frame size before delivering to the upstream buffer; frames of incorrect size **MUST** be discarded.

---

## IV. Transport-Agnostic Behavior

### I12
The transport mechanism (Unix socket, TCP socket, named pipe, shared memory, or any future transport) is **implementation-defined** and **MUST NOT** be specified by this contract.

### I13
This contract governs **BEHAVIOR**, not transport implementation.

### I14
Switching from one transport mechanism to another (e.g., Unix socket to TCP socket) **MUST** require **NO contract changes**; only implementation changes.

### I15
PCM Ingestion **MUST** behave identically regardless of the underlying transport mechanism used.

### I16
Transport-specific concerns (connection management, reconnection logic, transport-level errors) are implementation details and **MUST NOT** affect the behavioral contract defined here.

---

## V. Error Handling

### I17
PCM Ingestion **MUST NOT** crash or raise unhandled exceptions on malformed input.

### I18
PCM Ingestion **MUST** discard incomplete frames (frames smaller than 4096 bytes) without raising exceptions or logging at error level; debug-level logging is permitted.

### I19
PCM Ingestion **MUST** validate that each frame is exactly 4096 bytes before delivery; frames that cannot be read as complete 4096-byte units **MUST** be discarded. It **MUST NOT** attempt repair.

### I20
PCM Ingestion **MUST** tolerate transport disconnections gracefully without affecting AudioPump or EncoderManager operation.

### I21
PCM Ingestion **MUST NOT** block the system waiting for frames; all operations **MUST** be non-blocking or have bounded timeouts.

### I22
Transport-level errors (connection failures, timeouts, protocol violations) **MUST** be handled internally by PCM Ingestion without propagating to AudioPump or EncoderManager.

### I23
If the upstream PCM buffer is full, PCM Ingestion **MUST** handle the condition according to the buffer's overflow policy (as defined by the buffer contract) without blocking or crashing.

---

## VI. Multiple Upstream Providers

### I24
PCM Ingestion **MAY** accept multiple simultaneous ingest connections from different upstream providers.

### I25
If multiple connections are supported, ordering guarantees **MUST** be per-connection: frames from connection A **MUST** be delivered in order relative to other frames from connection A, but ordering between connections A and B is not guaranteed.

### I26
PCM Ingestion **MUST NOT** interleave frames from different providers; frames from a single connection **MUST** be delivered atomically and in order.

### I27
If multiple connections are supported, PCM Ingestion **MUST** handle disconnection of one provider without affecting other active connections.

### I28
Multi-provider support is **OPTIONAL**; a single-provider implementation **MUST** still satisfy all other contract requirements.

---

## VII. Prohibited Behaviors

### I29
PCM Ingestion **MUST NOT** perform routing decisions (EncoderManager owns routing logic).

### I30
PCM Ingestion **MUST NOT** apply gain, mixing, decoding, or any audio transformations to frames.

### I31
PCM Ingestion **MUST NOT** inspect audio content beyond what is necessary for format validation.

### I32
PCM Ingestion **MUST NOT** generate silence or fallback frames (EncoderManager selects fallback via FallbackProvider).

### I33
PCM Ingestion **MUST NOT** act as a metronome or timing source (AudioPump is the sole timing authority).

### I34
PCM Ingestion **MUST NOT** block the system waiting for frames; all frame acceptance operations **MUST** be non-blocking.

### I35
PCM Ingestion **MUST NOT** buffer frames internally beyond what is necessary for atomic frame delivery; frames **MUST** be delivered to the upstream buffer immediately upon validation.

### I36
PCM Ingestion **MUST NOT** modify frame content, byte order, or format; frames **MUST** be passed through unchanged (except for validation and atomicity guarantees).

---

## VIII. Downstream Obligations

### I37
Valid frames (frames that pass format validation) **MUST** be written to the upstream PCM buffer immediately upon validation.

### I38
PCM Ingestion **MUST** preserve frame atomicity when writing to the buffer: either the complete 4096-byte frame is written, or no frame is written.

### I39
PCM Ingestion **MUST NOT** write partial frames to the upstream buffer.

### I40
PCM Ingestion **MUST** preserve frame ordering per connection when writing to the buffer: frames from a single connection **MUST** be written in the order received.

### I41
PCM Ingestion **MUST** respect the upstream buffer's capacity and overflow policies; if the buffer is full, PCM Ingestion **MUST** handle the condition according to the buffer contract without blocking.

### I42
PCM Ingestion **MUST NOT** hold references to frames after they have been written to the buffer or discarded.

---

## IX. Integration with Audio Pipeline

### I43
PCM Ingestion **MUST** deliver frames to the same upstream PCM buffer that AudioPump reads from.

### I44
PCM Ingestion **MUST NOT** have direct knowledge of AudioPump, EncoderManager, or FFmpegSupervisor; it interacts only with the upstream PCM buffer.

### I45
PCM Ingestion **MUST NOT** interfere with AudioPump's tick loop or timing; all operations **MUST** be non-blocking relative to the 21.333ms tick interval (PCM cadence).

### I46
PCM Ingestion **MUST** operate independently of the audio processing pipeline; frame delivery **MUST** continue even if EncoderManager is in fallback mode or FFmpegSupervisor is restarting.

---

## X. Frame Validation Requirements

### I47
PCM Ingestion **MUST** validate that each received frame is exactly 4096 bytes before delivery.

### I48
PCM Ingestion **MAY** perform additional format validation (e.g., sanity checks on byte patterns) for observability, but frames that are exactly 4096 bytes **MUST** be treated as valid for delivery to the upstream buffer regardless of content validation results.

### I49
Format validation **MUST** be fast and non-blocking; validation **MUST NOT** introduce latency that affects real-time frame delivery.

### I50
Validation failures **MAY** be logged at debug level only; they **MUST NOT** be propagated to upstream providers or cause ingest to crash or block.

---

## XI. Startup and Shutdown

### I51
PCM Ingestion **MUST** be ready to accept frames before AudioPump begins ticking.

### I52
PCM Ingestion **MUST** continue accepting frames during system operation until explicitly shut down.

### I53
PCM Ingestion **MUST** handle shutdown gracefully: stop accepting new connections, finish processing in-flight frames, and close transport connections cleanly.

### I54
PCM Ingestion **MUST NOT** require frames to be present at startup; it **MUST** operate correctly even if no upstream provider is connected initially.

---

## XII. Observability

### I55
PCM Ingestion **MAY** expose metrics or statistics (frames received, frames discarded, connection count) but **MUST NOT** require such observability for contract compliance.

### I56
If observability is provided, it **MUST** be non-blocking and **MUST NOT** affect frame delivery performance.

### I57
Observability interfaces **MUST NOT** expose internal transport details; they **MUST** present transport-agnostic metrics only.

---

## XIII. Buffer Telemetry for Adaptive Upstream Pacing

### I58
Tower **SHALL** expose the fill-level and capacity of its upstream PCM buffer through the `/tower/buffer` endpoint defined in `NEW_TOWER_RUNTIME_CONTRACT`.

### I59
PCM Ingestion **SHALL** write frames into the upstream PCM buffer immediately upon validation and **MUST NOT** perform pacing, throttling, or rate regulation.

### I60
Upstream providers (e.g., Station) **SHALL** rely exclusively on Tower's buffer telemetry (via `/tower/buffer` endpoint) to determine appropriate pacing to avoid buffer overflow or starvation.

### I61
Tower **SHALL NOT** interpret, modify, or enforce any pacing decisions; pacing is wholly the responsibility of the upstream provider.

### I62
The buffer telemetry endpoint **SHALL** remain low-latency, non-blocking, and cheap to access to ensure stable pacing feedback loops.

### I63
PCM Ingestion **MUST NOT** implement any backpressure mechanisms or rate limiting; frame delivery **MUST** proceed at the rate frames are received from upstream providers.

### I64
PCM Ingestion **MUST NOT** delay frame delivery based on buffer fill level; frames **MUST** be written immediately upon validation regardless of buffer state.

### I65
Buffer overflow handling (when buffer is full) **MUST** follow the buffer's overflow policy as defined by the buffer contract; PCM Ingestion **MUST NOT** implement additional overflow prevention beyond respecting the buffer's capacity.

---

## XIV. Contract Compliance

### I66
All requirements in this contract **MUST** be satisfied by any PCM Ingestion implementation.

### I67
Implementation details (transport choice, threading model, buffer management) are **NOT** specified by this contract and **MAY** vary between implementations.

### I68
This contract **MUST** be compatible with all other Tower contracts and **MUST NOT** contradict requirements defined in:

- `NEW_CORE_TIMING_AND_FORMATS_CONTRACT`
- `NEW_AUDIOPUMP_CONTRACT`
- `NEW_ENCODER_MANAGER_CONTRACT`
- `NEW_FFMPEG_SUPERVISOR_CONTRACT`
- `NEW_TOWER_RUNTIME_CONTRACT`
- `NEW_FALLBACK_PROVIDER_CONTRACT`

---

## LOG — Logging and Observability

### LOG1 — Log File Location
PCM Ingestion **MUST** write all log output to `/var/log/retrowaves/tower.log`.

- Log file path **MUST** be deterministic and fixed
- Log file **MUST** be readable by the retrowaves user/group
- PCM Ingestion **MUST NOT** require elevated privileges at runtime to write logs

### LOG2 — Non-Blocking Logging
Logging operations **MUST** be non-blocking and **MUST NOT** interfere with frame ingestion.

- Logging **MUST NOT** block frame acceptance from upstream providers
- Logging **MUST NOT** delay frame validation or delivery
- Logging **MUST NOT** delay writes to upstream PCM buffer
- Logging **MUST NOT** affect transport connection handling
- Logging failures **MUST** degrade silently (stderr fallback allowed)

### LOG3 — Rotation Tolerance
PCM Ingestion **MUST** tolerate external log rotation without crashing or stalling.

- PCM Ingestion **MUST** assume logs may be rotated externally (e.g., via logrotate)
- PCM Ingestion **MUST** handle log file truncation or rename gracefully
- PCM Ingestion **MUST NOT** implement rotation logic in application code
- PCM Ingestion **MUST** reopen log files if they are rotated (implementation-defined mechanism)
- Rotation **MUST NOT** cause frame ingestion interruption

### LOG4 — Failure Behavior
If log file write operations fail, PCM Ingestion **MUST** continue accepting frames normally.

- Logging failures **MUST NOT** crash the process
- Logging failures **MUST NOT** interrupt frame acceptance
- Logging failures **MUST NOT** interrupt frame delivery to buffer
- PCM Ingestion **MAY** fall back to stderr for critical errors, but **MUST NOT** block on stderr writes

---

## Required Tests

This contract requires the following logging compliance tests:

- LOG1 — Log File Location
- LOG2 — Non-Blocking Logging
- LOG3 — Rotation Tolerance
- LOG4 — Failure Behavior

See `tests/contracts/LOGGING_TEST_REQUIREMENTS.md` for test specifications.

