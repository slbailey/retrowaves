# TowerRuntime Contract

## R. Purpose

**TowerRuntime** is the HTTP-facing surface of the Tower system. It is responsible for:

- Exposing the live MP3 stream over HTTP to clients
- Exposing a buffer-health endpoint for upstream adaptive sending
- Wiring together `AudioPump`, `EncoderManager`, `FFmpegSupervisor`, and buffer structures at startup

TowerRuntime does not decide audio content; it passes through what it receives from the encoder pipeline.

---

## S. HTTP Stream Endpoint

### T1
TowerRuntime **MUST** expose an HTTP endpoint /stream that:

- Returns HTTP 200 on successful connection
- Streams MP3 frames continuously until the client disconnects or server shuts down
- No other endpoints shall output MP3

### T2
The stream endpoint **MUST**:

- Read MP3 data from the encoder output (via `FFmpegSupervisor`)
- Write MP3 data to the client as a continuous chunked or streaming response

### T3
The stream endpoint **MUST**:

- Never intentionally send invalid MP3 data
- Close the connection cleanly on end-of-stream or server shutdown

---

## T. Multiple Clients and Fanout

### T4
TowerRuntime **MUST** support multiple simultaneous clients connected to the stream endpoint.

### T5
Each client **MUST**:

- Receive a continuous MP3 byte stream, independent of other clients
- Be able to disconnect without affecting other clients

### T6
TowerRuntime **MUST**:

- Avoid per-client ffmpeg instances; all clients **MUST** fan out from the same encoded stream
- Ensure that client-facing I/O does not block the encoder pipeline

---

## T-CLIENTS — Client Handling Requirements

### T-CLIENTS1
Writes **MUST** be non-blocking; slow clients must not block others.

### T-CLIENTS2
A client stalled for >250ms **MUST** be disconnected.

### T-CLIENTS3
Client registry **MUST** be thread-safe.

### T-CLIENTS4
Socket send return values **MUST** be validated (0 or error = disconnect).

---

## TR-TIMING — MP3 Output Timing Requirements (Revised)

### TR-TIMING1 — Frame-Driven Output
TowerRuntime **MUST** broadcast MP3 frames immediately as they become available from EncoderManager. TowerRuntime **MUST NOT** synthesize or enforce a fixed MP3 cadence (e.g., sleeping 24ms).

### TR-TIMING2 — No Independent MP3 Clock
TowerRuntime **MUST NOT** create or maintain its own timing interval for MP3 output. Timing **MUST** be derived solely from upstream PCM cadence via: AudioPump → EncoderManager → FFmpegSupervisor → MP3 frame availability.

### TR-TIMING3 — Bounded Wait
If no MP3 frame becomes available within a bounded timeout (≤250ms), the broadcast loop **MUST** output a fallback MP3 frame (silence or tone) to prevent stalling.

### TR-TIMING4 — Zero Drift Guarantee
Broadcast timing **MUST** follow encoder-produced MP3 frames directly. Timing drift between PCM cadence and MP3 output **MUST** be impossible by design.

---

## TR-HTTP — HTTP Streaming Contract

### TR-HTTP1 — Push-Based Streaming
The /stream endpoint **MUST** deliver MP3 frames immediately upon receipt from the broadcast loop. The HTTP layer **MUST NOT** impose its own timing cadence.

### TR-HTTP2 — Non-Blocking Writes
Writing MP3 bytes to clients **MUST** be non-blocking. Slow clients **MUST NOT** block the broadcast loop or other clients.

### TR-HTTP3 — Slow Client Disconnect
Any client unable to accept data for >250ms **MUST** be disconnected.

### TR-HTTP4 — Fanout Model
All clients **MUST** receive bytes from the same MP3 frame source. Per-client state **MUST NOT** create additional timing paths.

### TR-HTTP5 — No Timing Responsibilities
The HTTP layer **MUST NOT**:

- Sleep to enforce cadence
- Estimate MP3 frame durations
- Retry timing compensation

It **MUST** simply forward frames as they arrive.

---

## U. PCM Buffer Status / Backpressure Endpoint

### T7
TowerRuntime **MUST** expose an HTTP endpoint (existing name preserved, e.g. `/tower/buffer` or similar) that:

- Returns the current state of the PCM input buffer used by `AudioPump`

### T8
The buffer status response **MUST** include:

- Total buffer capacity (from AudioInputRouter's `get_stats().capacity`)
- Current fill level (from AudioInputRouter's `get_stats().count`)
- Fill ratio (0.0–1.0, calculated as `count / capacity`)

### T9
The buffer status endpoint **MUST** be:

- Read-only (no side effects)
- Cheap to serve (non-blocking where possible)
- Safe to call at high frequency by upstream (for adaptive sending / backpressure)

---

### T-BUF — Buffer Status Endpoint Specification

#### T-BUF1
Endpoint path **MUST** remain `/tower/buffer` for backward compatibility.

#### T-BUF2
Response **MUST** be JSON with fields:

```json
{
  "capacity": <int>,
  "count": <int>,
  "overflow_count": <int>,
  "ratio": <float between 0–1>
}
```

#### T-BUF3
Must return in <10ms typical, <100ms maximum.

#### T-BUF4
Endpoint **MUST** be non-blocking (no locks that block the PCM path).

#### T-BUF5
Stats **MUST** originate from `AudioInputRouter.get_stats()`.

---

## TR-AIR — Audio Input Router Interface Requirements

### TR-AIR1
TowerRuntime depends on an upstream PCM router ("AudioInputRouter") that supplies whole **4096-byte PCM frames** (canonical PCM frame size as defined in `NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md`).

### TR-AIR2
Partial frames **MUST** be discarded by the AudioInputRouter.

### TR-AIR3
Overflow behavior **MUST** follow ring-buffer rules (drop newest or oldest depending on chosen buffer type).

### TR-AIR4
AudioInputRouter **MUST** expose `get_stats()` method that returns:

- `capacity` — maximum number of frames the buffer can hold
- `count` — current number of frames in the buffer
- `overflow_count` — total number of frames dropped due to buffer overflow

### TR-AIR5
The `/tower/buffer` endpoint **MUST** consume these stats from AudioInputRouter's `get_stats()` method to provide buffer status to upstream systems.

---

## V. Integration Responsibilities

### T10
On startup, TowerRuntime **MUST**:

Construct or obtain:

- `AudioPump` instance
- `EncoderManager` instance
- `FFmpegSupervisor` instance
- PCM input buffer and downstream buffer(s)
- Precomputed silence and tone frames

Wire these components together according to their contracts.

### T11
TowerRuntime **MUST** ensure that:

- `AudioPump` runs continuously, driving the tick loop
- `FFmpegSupervisor` is started and monitored
- HTTP endpoints are registered and served

---

## T-ORDER — Startup & Shutdown Sequence

### T-ORDER1
Startup order **MUST** be:

1. Construct buffers
2. Construct FallbackProvider
3. Construct EncoderManager
4. Construct AudioPump
5. Start FFmpegSupervisor
6. Start HTTP server
7. Start the frame-driven broadcast loop which retrieves MP3 frames from EncoderManager as they become available.

### T-ORDER2
Shutdown **MUST** be reverse order.

### T-ORDER3
In test mode, FFmpegSupervisor **MUST NOT** be started.

---

## T-MODE — Operational Modes

### T-MODE1
OFFLINE_TEST_MODE disables FFmpegSupervisor startup but keeps AudioPump + EncoderManager running.

This preserves testability without needing the entire old modes contract.

---

## W. Non-responsibilities

### T12
TowerRuntime **MUST NOT**:

- Implement grace period logic
- Decide silence vs tone vs program
- Inspect PCM data to decide behaviour

### T13
TowerRuntime **MUST** rely on `EncoderManager`, `AudioPump`, and `FFmpegSupervisor` for:

- Audio content selection
- Tick timing
- Encoding and process management

### T13.5
TowerRuntime **MUST NOT** implement MP3 timing, cadence enforcement, or synthetic frame intervals. Timing responsibilities belong exclusively to upstream PCM cadence.

---

## X. Observability and Health

### T14
TowerRuntime **SHOULD** expose health/metrics endpoints (existing ones preserved) to report:

- Encoder health (via `FFmpegSupervisor` status)
- Buffer occupancy
- Number of connected clients

### T15
These endpoints **MUST NOT** interfere with or slow down the audio tick loop.
