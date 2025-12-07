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
TowerRuntime **MUST** expose an HTTP endpoint (existing name preserved, e.g. `/tower/stream` or `/stream.mp3`) that:

- Returns HTTP 200 on successful connection
- Streams MP3 frames continuously until the client disconnects or server shuts down

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
TowerRuntime depends on an upstream PCM router ("AudioInputRouter") that supplies whole **4608-byte PCM frames**.

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

---

## X. Observability and Health

### T14
TowerRuntime **SHOULD** expose health/metrics endpoints (existing ones preserved) to report:

- Encoder health (via `FFmpegSupervisor` status)
- Buffer occupancy
- Number of connected clients

### T15
These endpoints **MUST NOT** interfere with or slow down the audio tick loop.
