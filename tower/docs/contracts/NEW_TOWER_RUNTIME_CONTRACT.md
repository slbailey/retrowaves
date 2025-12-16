# TowerRuntime Contract

## R. Purpose

**TowerRuntime** is the HTTP-facing surface of the Tower system. It is responsible for:

- Exposing the live MP3 stream over HTTP to clients
- Exposing a buffer-health endpoint for upstream adaptive sending
- Accepting Station heartbeat events and exposing them via WebSocket endpoints for observability
- Wiring together `AudioPump`, `EncoderManager`, `FFmpegSupervisor`, and buffer structures at startup

TowerRuntime does not decide audio content; it passes through what it receives from the encoder pipeline. TowerRuntime does not use Station events to influence timing or behavior; events are purely observational.

**Tower Statelessness:**
- Tower **MUST** remain stateless with respect to Station state
- Tower **MUST NOT** query, cache, or reconstruct Station state
- Tower **MUST NOT** infer state from events or event absence
- Events are edge-triggered transitions only, not authoritative state
- Tower forwards events to WebSocket clients but does not interpret or track state

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

### TR-TIMING3 — No MP3 Synthesis
TowerRuntime **MUST NOT** synthesize MP3 frames. Continuous MP3 output is guaranteed by the audio pipeline (EncoderManager → FFmpegSupervisor).

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

#### T-BUF6 (Pre-Fill Support)
The `/tower/buffer` endpoint **MUST** support high-frequency polling during Station pre-fill operations.

- Endpoint **MUST** remain non-blocking and performant even when polled at high frequency (e.g., every 50-100ms)
- Response time requirements (T-BUF3) apply during pre-fill: <10ms typical, <100ms maximum
- Tower **MUST NOT** signal Station to start or stop pre-fill (Station decides autonomously)
- Tower **MUST** accept frames at any rate during pre-fill (non-blocking ingestion per I4)
- Buffer overflow during pre-fill **MUST** be handled gracefully (drop-oldest semantics per TR-AIR3)

**Note:** Pre-fill is a Station-internal optimization. Tower is unaware of pre-fill mode and simply provides buffer status and accepts frames.

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
4. Start PCM Ingestion (must be ready to accept frames before AudioPump begins ticking, per I51)
5. Construct AudioPump
6. Initialize event broadcaster (no storage or buffering; real-time delivery only)
7. Start FFmpegSupervisor
8. Start HTTP server (including event endpoints)
9. Start the frame-driven broadcast loop which retrieves MP3 frames from EncoderManager as they become available.

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

---

## Y. Station Heartbeat Events

TowerRuntime **MUST** accept Station heartbeat events and expose them via WebSocket endpoints for observability. Events are one-way (Station→Tower) and **MUST NOT** influence Tower timing or behavior.

### T-EVENTS — Station Event Reception

#### T-EVENTS1 — Event Acceptance
TowerRuntime **MUST** accept Station heartbeat events via HTTP POST to `/tower/events/ingest` (or equivalent internal interface).

**Accepted event types (ONLY these four):**
- `station_startup` — Station has started up and playout has begun
- `station_shutdown` — Station is shutting down after terminal playout completes
- `song_playing` — Song segment has started playing (edge-triggered transition)
- `segment_playing` — Non-song segment has started playing (edge-triggered transition)

**DEPRECATED event types (MUST be explicitly rejected):**
- `station_starting_up` — **DEPRECATED** - TowerRuntime **MUST** reject with validation error
- `station_shutting_down` — **DEPRECATED** - TowerRuntime **MUST** reject with validation error
- `now_playing` — **DEPRECATED** - TowerRuntime **MUST** reject with validation error
- `dj_talking` — **DEPRECATED** - TowerRuntime **MUST** reject with validation error (use `segment_playing` instead)
- Any other event type not listed in accepted event types — **FORBIDDEN** - TowerRuntime **MUST** reject with validation error

**Event sending requirements:**
- `station_startup` **MUST** be sent exactly once when Station.start() completes and playout begins
- `station_shutdown` **MUST** be sent exactly once when terminal playout completes (or timeout), before shutdown
- `song_playing` **MUST** be sent when a song segment starts playing (on_segment_started with segment_type="song")
  - `song_playing` events **MUST** include full AudioEvent metadata when available (title, artist, album, year, duration_sec, file_path)
  - `song_playing` **MUST** be sent synchronously before audio begins
  - This is an edge-triggered transition event - events represent transitions, not current state
- `segment_playing` **MUST** be sent when a non-song segment starts playing (on_segment_started with segment_type not equal to "song")
  - `segment_playing` events **MUST** include required metadata: `segment_class`, `segment_role`, `production_type` (see EVENT_INVENTORY.md for metadata schema)
  - `segment_playing` **MUST** be sent synchronously before audio begins
  - This is an edge-triggered transition event - events represent transitions, not current state
  - Tower **MUST** treat all metadata as opaque and **MUST NOT** interpret or validate metadata fields
- Station **MUST NOT** send multiple `station_startup` or `station_shutdown` events
- Station **MUST** track whether lifecycle events have been sent to prevent duplicates
- Station **MUST NOT** send "end" or "clear" events - events represent transitions only, not state

#### T-EVENTS1.4 — Event Ingestion Access Control
TowerRuntime **MUST** expose `/tower/events/ingest` only to trusted internal systems.

**The ingestion endpoint:**
- **MUST NOT** be accessible by public clients
- **MUST NOT** require authentication for Station (relies on network-level isolation)
- **MUST** rely on network-level isolation (e.g., private interface, Unix socket, localhost-only binding)

This mirrors the PCM ingest contract (Station→Tower PCM is also internal-only). The ingestion endpoint is an internal interface, not a public API.

#### T-EVENTS2 — Event Delivery
TowerRuntime **MUST NOT** store events.

- Events are delivered only to currently connected WebSocket clients
- Events **MUST** be dropped immediately if no clients are connected
- Events **MUST** include `tower_received_at` timestamp (Tower wall-clock time when received) before delivery

#### T-EVENTS2.5 — Overload Handling
Since no event storage exists, overload conditions do not apply.

- TowerRuntime **MUST** drop events that cannot be delivered immediately
- TowerRuntime **MUST NOT** block ingestion
- TowerRuntime **MUST NOT** exert backpressure on Station
- TowerRuntime **MUST NOT** queue events for clients who are not currently connected

Since Tower does not influence Station timing, it also cannot influence event pacing. Tower **MUST** accept events at whatever rate Station sends them, delivering them immediately to connected clients or dropping them if no clients are connected, without blocking or backpressure.

#### T-EVENTS3 — Event Format
Received events **MUST** conform to Station heartbeat event format:

```json
{
  "event_type": "<event_type>",
  "timestamp": <float>,  // Station Clock A timestamp (time.monotonic())
  "tower_received_at": <float>,  // Tower wall-clock timestamp when received
  "metadata": {
    // Event-specific metadata (varies by event type)
    // For "song_playing" events:
    //   "segment_type": "<string>",  // "song"
    //   "started_at": <float>,        // Wall-clock timestamp when segment started
    //   "file_path": "<string>",      // Path to MP3 file
    //   "title": "<string>",          // Song title (from MP3 metadata, if available)
    //   "artist": "<string>",         // Artist name (from MP3 metadata, if available)
    //   "album": "<string>",          // Album name (from MP3 metadata, if available)
    //   "year": <int>,                // Release year (from MP3 metadata, if available)
    //   "duration_sec": <float>,      // Duration in seconds (from MP3 metadata, if available)
    // For "segment_playing" events:
    //   "segment_class": "<string>",  // Required: segment_class enum (station_id, dj_talk, promo, imaging, radio_drama, album_segment, emergency, special)
    //   "segment_role": "<string>",    // Required: segment_role enum (intro, outro, interstitial, top_of_hour, legal, transition, standalone)
    //   "production_type": "<string>", // Required: production_type enum (live_dj, voice_tracked, produced, system)
    //   "file_path": "<string>",      // Optional: Absolute path to audio file
    //   "duration_sec": <float>,      // Optional: Duration in seconds
    //   "series_id": "<string>",      // Optional: Series identifier
    //   "episode_id": "<string>",      // Optional: Episode identifier
    //   "part_number": <int>,         // Optional: Part number within multi-part segment
    //   "total_parts": <int>,          // Optional: Total number of parts
    //   "legal": <boolean>            // Optional: Whether segment satisfies legal ID requirements
    // For lifecycle events ("station_startup", "station_shutdown"):
    //   (no metadata required)
  }
}
```

**Event Format Semantics:**
- Events **MUST** represent edge-triggered transitions only
- Events **MUST NOT** represent current state or authoritative truth
- Events **MUST NOT** include empty metadata to signal "end of segment" or "no content"
- Events **MUST NOT** be used to infer "current playing" state

#### T-EVENTS3.4 — Event Content Integrity
TowerRuntime **MUST NOT** modify the semantic meaning of events received from Station.

**Allowed modifications:**
- Adding `tower_received_at` timestamp
- Adding `event_id` (Tower-side unique ID for tracking)

**Forbidden:**
- Altering metadata fields
- Renaming event types
- Synthesizing new fields
- Modifying existing field values
- Removing fields

This protects system-level invariants for downstream systems that consume events. Events must remain semantically identical to what Station emitted, with only Tower-side tracking fields added.

#### T-EVENTS4 — One-Way Communication
Events are **one-way** (Station→Tower). Tower **MUST NOT**:

- Send timing information back to Station
- Use events to influence Tower timing (Clock B)
- Use events to influence PCM pacing or MP3 output timing
- Use events to influence encoder behavior
- Provide feedback to Station about event reception

#### T-EVENTS5 — Observational Only
Events **MUST** be purely observational. Tower **MUST NOT**:

- Use events to make timing decisions
- Use events to adjust PCM buffer behavior
- Use events to influence encoder cadence
- Use events to modify broadcast timing
- React to absence of events (e.g., infer silence or fallback from lack of events)

Events are for observability only (monitoring, debugging, health checks).

**Exception:** The `station_shutdown` event **MAY** be used to suppress PCM loss warnings. When Tower receives a `station_shutdown` event, it **MUST** suppress PCM loss detection warnings until a `station_startup` event is received. This prevents false alarms during expected shutdown periods.

#### T-EVENTS6 — Non-Blocking Reception
Event reception **MUST** be non-blocking.

- Event ingestion **MUST NOT** block the audio tick loop
- Event ingestion **MUST NOT** block PCM processing
- Event ingestion **MUST NOT** block MP3 encoding
- Event ingestion **MUST NOT** block HTTP streaming

Event delivery **MUST** complete quickly (< 1ms typical, < 10ms maximum).

#### T-EVENTS7 — Event Validation
TowerRuntime **MUST** validate received events:

- Event type **MUST** be exactly one of: `station_startup`, `station_shutdown`, `song_playing`, `segment_playing`
- Event **MUST** include required fields (`event_type`, `timestamp`, `metadata`)
- **DEPRECATED event types MUST be explicitly rejected**: TowerRuntime **MUST** reject the following with validation error (logged but not stored):
  - `now_playing` — **REJECTED** (deprecated)
  - `station_starting_up` — **REJECTED** (deprecated, use `station_startup`)
  - `station_shutting_down` — **REJECTED** (deprecated, use `station_shutdown`)
  - `dj_talking` — **REJECTED** (deprecated, use `segment_playing`)
  - Any other event type not in the accepted list — **REJECTED**
- TowerRuntime **MUST** treat all metadata as opaque and **MUST NOT** interpret or validate metadata fields
- Invalid events **MUST** be silently dropped (logged but not stored)
- Validation **MUST** be fast (< 1ms) and non-blocking
- Rejection of deprecated events **MUST** be logged for observability

#### T-EVENTS8 — State Inference and Query Prohibition
TowerRuntime **MUST NOT** infer, track, query, cache, or reconstruct Station state.

**Explicit Prohibitions:**
- Tower **MUST NOT** query Station state (no HTTP requests to Station state endpoints)
- Tower **MUST NOT** cache or store Station state internally
- Tower **MUST NOT** reconstruct Station state from event history
- Tower **MUST NOT** track "current playing" state based on events
- Tower **MUST NOT** assume absence of events implies absence of state
- Tower **MUST NOT** infer silence or fallback from lack of events
- Tower **MUST NOT** derive "current playing" from events
- Tower **MUST** treat events as one-way, observational transitions only
- Events remain purely observational and do not represent current truth

**Event Semantics:**
- Events represent edge-triggered transitions, not state
- Events are observational announcements only
- Tower **MUST NOT** use events to determine what is currently playing
- Tower **MUST NOT** react to absence of events

#### T-EVENTS9 — Explicit State Prohibitions
TowerRuntime **MUST** remain stateless with respect to Station state. The following behaviors are **EXPLICITLY FORBIDDEN**:

**Tower MUST NOT Query Station State:**
- Tower **MUST NOT** make HTTP requests to Station state endpoints
- Tower **MUST NOT** query Station state via any mechanism
- Tower **MUST NOT** poll Station for current state
- Tower **MUST NOT** maintain connections to Station state APIs

**Tower MUST NOT Cache or Reconstruct State:**
- Tower **MUST NOT** cache Station state internally
- Tower **MUST NOT** store Station state in memory or on disk
- Tower **MUST NOT** reconstruct Station state from event history
- Tower **MUST NOT** maintain any internal representation of "current playing" state
- Tower **MUST NOT** track state transitions internally

**Tower MUST NOT Infer State from Events:**
- Tower **MUST NOT** derive "current playing" from events
- Tower **MUST NOT** infer silence from absence of events
- Tower **MUST NOT** infer fallback from absence of events
- Tower **MUST NOT** assume absence of events implies any particular state
- Tower **MUST NOT** use event history to determine current state

**Tower MUST NOT React to Event Absence:**
- Tower **MUST NOT** react to lack of events
- Tower **MUST NOT** infer behavior from missing events
- Tower **MUST NOT** use event presence or absence to make decisions
- Tower **MUST** treat events as one-way, observational transitions only

**Rationale:**
Tower is stateless and observational. Events are announcements of transitions, not authoritative state. Tower forwards events to WebSocket clients but does not interpret, cache, or query state. Current state must be queried directly from Station via Station State Contract, not inferred from events.

---

## Z. Event Exposure Endpoints

TowerRuntime **MUST** expose WebSocket endpoints for clients to observe Station heartbeat events.

### T-EXPOSE — Event Exposure Requirements

#### T-EXPOSE1 — `/tower/events` WebSocket Endpoint
TowerRuntime **MUST** expose a WebSocket endpoint `/tower/events` that:

- Accepts WebSocket upgrade requests from clients
- Maintains a persistent, bidirectional WS connection (Tower will only send; clients MAY send pings)
- Broadcasts heartbeat events immediately upon receipt to all connected WebSocket clients
- Supports multiple simultaneous WS clients
- Ensures each new event is broadcast to all connected clients without batching or delay
- **MUST NOT** queue or buffer events for clients who are not currently connected
- Disconnects any client that cannot accept data for >250ms
- Closes WS connections cleanly on server shutdown

**WebSocket message format:**
- Each WS message **MUST** contain exactly one event as a complete JSON object
- Messages **MUST** be text-format JSON (not binary)
- Events **SHOULD** be delivered in arrival order, but TowerRuntime **MUST NOT** store events for ordering enforcement

**Query parameters (optional, supported during WS upgrade):**
- `event_type`: Filter by event type (e.g., `?event_type=song_playing` or `?event_type=dj_talking`)

#### T-EXPOSE1.2 — WebSocket Fanout
TowerRuntime **MUST** maintain a registry of connected WebSocket clients.

When a new event arrives, TowerRuntime **MUST** broadcast it to all connected clients immediately, using non-blocking writes.

Slow or stalled WS clients **MUST** be dropped without impacting other clients.

WebSocket client handling **MUST** follow T-WS* requirements (see T-WS section below).

#### T-EXPOSE1.7 — Immediate Flush Requirement
When a new event is received, and clients are connected to `/tower/events`, TowerRuntime **MUST** send the event to all connected WebSocket clients immediately upon receipt, with no batching or intentional delay.

- Events **MUST** be pushed to clients as soon as they are received
- Events **MUST NOT** be batched or delayed for efficiency
- Events **MUST** be flushed immediately to maintain real-time synchronization
- TowerRuntime **MAY** drop events if a WebSocket write is non-blocking and fails or stalls
- This ensures event visual overlays stay in sync with audio as closely as possible (observational sync)

**Note:** All event exposure **MUST** occur exclusively via WebSocket. TowerRuntime **MUST NOT** expose HTTP endpoints for event retrieval.

#### T-EXPOSE3 — Non-Blocking Endpoints
The WebSocket event endpoint **MUST** be non-blocking:

- Endpoints **MUST NOT** block the audio tick loop
- Endpoints **MUST NOT** block PCM processing
- Endpoints **MUST NOT** block MP3 encoding
- Endpoints **MUST NOT** block HTTP streaming
- WebSocket operations **MUST NOT** block event ingestion

Event delivery **MUST** complete quickly (< 10ms typical, < 100ms maximum).


#### T-EXPOSE5 — Client Handling
Event endpoints **MUST** follow T-WS* requirements (see T-WS section below).

#### T-EXPOSE6 — Event Ordering
Events **SHOULD** be delivered in arrival order, but TowerRuntime **MUST NOT** store events for ordering enforcement.

- TowerRuntime cannot guarantee strict FIFO ordering across clients because events are not queued
- Events are delivered immediately upon receipt to all connected clients

#### T-EXPOSE7 — Event Filtering
The WebSocket event endpoint **MAY** support filtering by:

- Event type (e.g., only `song_playing` events or only `segment_playing` events)
- Other metadata fields (implementation-defined)

Filtering parameters **MUST** be specified during WebSocket upgrade (via query parameters). Filtering **MUST** be fast (< 1ms) and **MUST NOT** block the audio tick loop.

**Note:** Timestamp-based filtering (e.g., `since`) is not supported because events are not stored.

#### T-EXPOSE8 — Error Handling
The WebSocket event endpoint **MUST** handle errors gracefully:

- Invalid query parameters during upgrade **MUST** reject the WebSocket upgrade with HTTP 400 (Bad Request)
- Server errors **MUST** close the WebSocket connection with appropriate close code
- Errors **MUST NOT** affect audio processing or other endpoints
- WebSocket connection failures **MUST NOT** block event ingestion

#### T-EXPOSE9 — No Timing Dependencies
WebSocket event endpoints **MUST NOT** depend on Station timing:

- Endpoints **MUST NOT** wait for Station events
- Endpoints **MUST NOT** block if no events are available
- Endpoints **MUST** send events immediately as they become available (or send empty/keepalive if no events)
- Endpoints **MUST NOT** use Station timing to influence Tower behavior

---

## T-WS — WebSocket Transport Requirements

### T-WS1 — RFC6455 Compliance
TowerRuntime **MUST** implement WebSocket connections in compliance with RFC6455.

- WebSocket upgrade handshake **MUST** follow RFC6455
- Frame format **MUST** comply with RFC6455
- Close handshake **MUST** follow RFC6455

### T-WS2 — Idle Connections
TowerRuntime **MUST** allow WebSocket connections to remain idle (no data frames sent) for extended periods.

- Idle connections **MUST NOT** be disconnected based solely on lack of data transfer
- Idle connections **MAY** remain open indefinitely as long as the connection is healthy
- Idle timeout **MUST** be configurable with a default of ≥120 seconds, or **MAY** be disabled

### T-WS3 — Activity Definition
Activity on a WebSocket connection **MUST** be defined as any WebSocket frame (control or data) sent or received.

- Ping frames (sent or received) **MUST** be considered activity
- Pong frames (sent or received) **MUST** be considered activity
- Data frames (sent or received) **MUST** be considered activity
- Close frames **MUST** be considered activity

### T-WS4 — Slow-Consumer Drop Semantics
Slow-consumer detection and disconnection **MUST** apply only when an actual send operation stalls.

- A client **MUST** be considered slow only when a non-blocking send operation fails or indicates the socket buffer is full
- A client **MUST NOT** be disconnected based solely on connection age or idle time
- A client **MUST** be disconnected if a send operation cannot complete within a bounded timeout (implementation-defined, typically ≤250ms for send operations)
- Slow-consumer drop **MUST NOT** affect other clients
- Send stall detection **MUST** be based on OS-level socket writability (e.g., select/poll), not elapsed time or mocked send behavior

### T-WS5 — Ping/Pong Support
TowerRuntime **MUST** respond to ping frames from clients with pong frames per RFC6455.

- TowerRuntime **MUST** respond to incoming ping frames with pong frames (RFC6455 requirement)
- TowerRuntime **MAY** send periodic ping frames to clients for connection liveness (optional)
- Ping/pong frames **MUST NOT** be considered data frames for event delivery purposes

### T-WS6 — Thread-Safe Registry
The WebSocket client registry **MUST** be thread-safe.

- Concurrent registration and removal **MUST** be safe
- Concurrent broadcast operations **MUST** be safe
- Registry operations **MUST NOT** block event ingestion or audio processing

### T-WS7 — Non-Blocking Writes
WebSocket write operations **MUST** be non-blocking.

- Send operations **MUST** use non-blocking I/O
- Write failures **MUST** be handled gracefully without blocking
- Slow clients **MUST** be detected via send operation failures, not connection age

---

## LOG — Logging and Observability

### LOG1 — Log File Location
TowerRuntime **MUST** write all log output to `/var/log/retrowaves/tower.log`.

- Log file path **MUST** be deterministic and fixed
- Log file **MUST** be readable by the retrowaves user/group
- TowerRuntime **MUST NOT** require elevated privileges at runtime to write logs

### LOG2 — Non-Blocking Logging
Logging operations **MUST** be non-blocking and **MUST NOT** interfere with audio processing.

- Logging **MUST NOT** block HTTP stream endpoint operations
- Logging **MUST NOT** block MP3 broadcast loop
- Logging **MUST NOT** block event ingestion or delivery
- Logging **MUST NOT** block buffer status endpoint
- Logging failures **MUST** degrade silently (stderr fallback allowed)

### LOG3 — Rotation Tolerance
TowerRuntime **MUST** tolerate external log rotation without crashing or stalling.

- TowerRuntime **MUST** assume logs may be rotated externally (e.g., via logrotate)
- TowerRuntime **MUST** handle log file truncation or rename gracefully
- TowerRuntime **MUST NOT** implement rotation logic in application code
- TowerRuntime **MUST** reopen log files if they are rotated (implementation-defined mechanism)
- Rotation **MUST NOT** cause audio pipeline interruption

### LOG4 — Failure Behavior
If log file write operations fail, TowerRuntime **MUST** continue operating normally.

- Logging failures **MUST NOT** crash the process
- Logging failures **MUST NOT** interrupt HTTP streaming
- Logging failures **MUST NOT** interrupt audio processing
- TowerRuntime **MAY** fall back to stderr for critical errors, but **MUST NOT** block on stderr writes

---

## Required Tests

This contract requires the following tests:

### Logging Compliance Tests
- LOG1 — Log File Location
- LOG2 — Non-Blocking Logging
- LOG3 — Rotation Tolerance
- LOG4 — Failure Behavior

See `tests/contracts/LOGGING_TEST_REQUIREMENTS.md` for test specifications.

### WebSocket Transport Tests
- T-WS1 — RFC6455 Compliance: Verify WebSocket upgrade handshake, frame format, and close handshake comply with RFC6455
- T-WS2 — Idle Connection Survival: Verify WebSocket connections remain open when idle (no data frames) for extended periods (≥120 seconds default)
- T-WS3 — Ping/Pong Handling: Verify TowerRuntime responds to ping frames with pong frames per RFC6455, and ping/pong frames are considered activity
- T-WS4 — Slow-Consumer Drop-on-Send-Stall: Verify clients are disconnected only when an actual send operation stalls (socket buffer full or send timeout), not based on connection age or idle time

### Buffer Endpoint Tests
- T-BUF1 — Endpoint Path: Verify the buffer endpoint is accessible at `/tower/buffer` (not `/tower/pcm-buffer-status` or other paths)
- T-BUF2 — Response Schema: Verify the response JSON contains exactly the fields specified in T-BUF2: `capacity`, `count`, `overflow_count`, and `ratio`

---

## Implementation Notes

### Event Reception
- Events may be received via HTTP POST to `/tower/events/ingest` (internal endpoint)
- Events may be received via Unix socket or other IPC mechanism (implementation-defined)
- Event reception must be asynchronous and non-blocking

### Event Delivery
- Events are not stored; they are delivered immediately to connected WebSocket clients
- Events are dropped if no clients are connected
- No buffering or queuing of events

### Event Exposure
- `/tower/events` **MUST** use WebSockets for real-time event streaming
- The WebSocket endpoint should support filtering via query parameters during upgrade
- TowerRuntime **MUST NOT** expose HTTP endpoints for event retrieval

### Performance
- Event ingestion: < 1ms typical, < 10ms maximum
- Event retrieval: < 10ms typical, < 100ms maximum
- Event endpoints must not affect audio processing latency

### WebSocket Event Broadcast (Implementation Notes)
- WebSocket server **MUST** run inside TowerRuntime's HTTP server, using WS upgrade
- Tower **MUST NOT** initiate outbound WS connections
- Tower **MUST NOT** expect clients to send data; WS is used for push/broadcast only
- Tower **MAY** support ping/pong frames for liveness
- Writes **MUST** be non-blocking; stalled clients **MUST** be disconnected
- Events are delivered immediately upon receipt; no ordering guarantees across clients

### Security
- Event ingestion endpoint should be internal-only (not exposed to external clients)
- Event exposure endpoints may be public (for monitoring/debugging)
- Authentication/authorization is implementation-defined (not specified in contract)
