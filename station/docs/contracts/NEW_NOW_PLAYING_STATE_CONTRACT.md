# Now Playing State Contract

## R. Purpose

Defines the authoritative, read-only description of the currently active playout segment. This contract ensures that observers can query the system's current playout state without influencing playout behavior, timing, or decision-making.

This contract exists to enable external systems (Tower, web clients, monitoring tools) to observe what is currently playing while maintaining strict separation between observation and control. NowPlayingState is purely observational and **MUST NOT** influence any aspect of playout timing, segment duration, decoder behavior, or DJ decision-making.

**Cross-Contract References:**
- **AudioEvent:** See `AUDIO_EVENT_CONTRACT.md` for segment structure and metadata
- **PlayoutEngine:** See `PLAYOUT_ENGINE_CONTRACT.md` for segment lifecycle events (`on_segment_started`, `on_segment_finished`)
- **DJ Intent:** See `DJ_INTENT_CONTRACT.md` for intent structure and metadata sources
- **Master System:** See `MASTER_SYSTEM_CONTRACT.md` for THINK/DO event model

---

## N. NowPlayingState Definition

### N.1 — Required Fields

NowPlayingState **MUST** define the following fields:

- **`segment_type`**: `str` (required) — Type of currently playing segment
  - **MUST** be one of: `"song"`, `"intro"`, `"outro"`, `"id"`, `"talk"`, `"fallback"`
  - **MUST** be derived from the active AudioEvent's type
  - **MUST NOT** be `None` when state is active

- **`started_at`**: `float` (required) — Wall-clock timestamp when segment started
  - **MUST** be a wall-clock timestamp (e.g. `time.time()` or UTC epoch seconds) captured at segment start
  - **MUST** represent the exact moment `on_segment_started` was emitted
  - **MUST NOT** be adjusted or corrected after creation
  - **MUST NOT** be `None` when state is active

### N.2 — Optional Fields

NowPlayingState **MAY** include the following optional fields:

- **`title`**: `str?` (optional) — Song or segment title
  - **MAY** be `None` if metadata is unavailable
  - **MUST** be extracted from AudioEvent metadata when available
  - **MUST** be derived from MP3 tags for song segments

- **`artist`**: `str?` (optional) — Artist name
  - **MAY** be `None` if metadata is unavailable
  - **MUST** be extracted from AudioEvent metadata when available
  - **MUST** be derived from MP3 tags for song segments

- **`album`**: `str?` (optional) — Album name
  - **MAY** be `None` if metadata is unavailable
  - **MUST** be extracted from AudioEvent metadata when available
  - **MUST** be derived from MP3 tags for song segments

- **`year`**: `int?` (optional) — Release year
  - **MAY** be `None` if metadata is unavailable
  - **MUST** be extracted from AudioEvent metadata when available
  - **MUST** be derived from MP3 tags for song segments

- **`duration_sec`**: `float?` (optional) — Segment duration in seconds
  - **MAY** be `None` if duration cannot be determined
  - **MUST** be derived from AudioEvent metadata or file duration when available
  - **MUST** represent the actual file duration, not estimated or adjusted duration

- **`file_path`**: `str?` (optional) — Absolute path to the audio file
  - **MAY** be `None` if file path is not available
  - **MUST** be the absolute path to the MP3 file being played
  - **MUST NOT** be a relative path

### N.3 — State Absence

When no segment is currently playing, NowPlayingState **MUST** be `None` or an empty/null representation.

- State **MUST** be cleared when no segment is active
- Observers **MUST** interpret `None` or empty state as "no segment currently playing"
- State **MUST NOT** retain previous segment information after `on_segment_finished`

### N.4 — Derived Fields Prohibition

NowPlayingState **MUST NOT** include computed or derived fields that require ongoing calculation:

- **FORBIDDEN:** Elapsed time calculations
- **FORBIDDEN:** Remaining time calculations
- **FORBIDDEN:** Progress percentage
- **FORBIDDEN:** Estimated completion timestamps
- **FORBIDDEN:** Any field that requires periodic updates during segment playback

Observers **MAY** compute these values from `started_at` and `duration_sec`, but the state itself **MUST NOT** contain them.

---

## U. Update Rules

### U.1 — State Creation

NowPlayingState **MUST** be created when `on_segment_started` is emitted.

- State **MUST** be created synchronously with `on_segment_started` event
- State **MUST** be populated from the AudioEvent that triggered `on_segment_started`
- State **MUST** capture `started_at` timestamp at the exact moment of creation
- State **MUST** be immediately available to all observers after creation

### U.2 — State Immutability During Playback

NowPlayingState **MUST NOT** be mutated during segment playback.

- Once created, state fields **MUST NOT** be modified until segment completion
- State **MUST** remain constant throughout segment playback
- No mid-segment updates **MAY** occur, even if metadata becomes available later
- State **MUST NOT** be updated based on decoder progress, buffer state, or timing corrections

### U.3 — State Clearing

NowPlayingState **MUST** be cleared when `on_segment_finished` is emitted.

- State **MUST** be cleared synchronously with `on_segment_finished` event
- State **MUST** be set to `None` or empty representation immediately
- State **MUST NOT** retain any information from the completed segment
- Clearing **MUST** occur before the next segment's `on_segment_started` event
- If Station restarts mid-segment, NowPlayingState **MUST** be cleared and **MUST NOT** attempt reconstruction of the interrupted segment

### U.4 — Update Authority

Station is the **ONLY** writer of NowPlayingState.

- Station **MUST** be the sole authority for creating, updating, and clearing state
- Tower **MUST NOT** modify NowPlayingState
- External clients **MUST NOT** modify NowPlayingState
- HTTP endpoints **MUST NOT** accept state modifications
- WebSocket events **MUST NOT** accept state modifications
- No write operations **MAY** be exposed to external systems

### U.5 — Update Timing

State updates **MUST** occur only at segment lifecycle boundaries.

- Updates **MUST** occur only at `on_segment_started` and `on_segment_finished` events
- Updates **MUST NOT** occur during segment playback
- Updates **MUST NOT** occur based on polling or periodic checks
- Updates **MUST NOT** occur based on buffer state changes
- Updates **MUST NOT** occur based on decoder progress

---

## E. Exposure Rules

### E.1 — Exposure Mechanisms

NowPlayingState **MAY** be exposed through the following mechanisms:

- **WebSocket events:** State **MAY** be broadcast via WebSocket when state changes
- **REST endpoint:** State **MAY** be queried via HTTP GET request
- **Metadata injection:** State **MAY** be injected into stream metadata (implementation-defined)

All exposure mechanisms **MUST** represent the same underlying state.

### E.2 — WebSocket Events

If WebSocket exposure is implemented:

- State **MUST** be broadcast when `on_segment_started` occurs
- State **MUST** be broadcast (as `None` or empty) when `on_segment_finished` occurs
- Events **MUST** be non-blocking and **MUST NOT** delay playout
- Events **MUST** include complete state representation
- Events **MUST NOT** include partial or incremental updates

### E.3 — REST Endpoint

If REST endpoint exposure is implemented:

- Endpoint **MUST** respond to GET requests with current state
- Endpoint **MUST** return `None` or empty representation when no segment is playing
- Endpoint **MUST** return state in a consistent format (JSON recommended)
- Endpoint **MUST NOT** accept POST, PUT, PATCH, or DELETE requests
- Endpoint **MUST NOT** modify state
- Endpoint **MUST** be read-only

### E.4 — State Consistency

All exposure mechanisms **MUST** represent identical state.

- WebSocket events and REST endpoint **MUST** return the same state for the same segment
- State **MUST** be consistent across all observers
- State **MUST NOT** differ between exposure mechanisms
- State **MUST** be derived from a single authoritative source (Station)

### E.5 — Non-Blocking Exposure

All exposure operations **MUST** be non-blocking.

- WebSocket broadcasts **MUST NOT** block playout thread
- REST endpoint reads **MUST NOT** block playout thread
- State queries **MUST NOT** delay segment lifecycle events
- Exposure failures **MUST NOT** affect playout behavior

---

## F. Forbidden Behaviors

### F.1 — Consumer Feedback Loops

NowPlayingState **MUST NOT** enable consumer feedback loops.

- Consumers **MUST NOT** influence Station behavior via state queries
- State queries **MUST NOT** trigger timing adjustments
- State queries **MUST NOT** influence DJ decision-making
- State queries **MUST NOT** affect segment selection
- State queries **MUST NOT** modify playout queue

### F.2 — Timing Authority

NowPlayingState **MUST NOT** control, adjust, or influence timing.

- State **MUST NOT** influence Clock A (Station decode/content clock)
- State **MUST NOT** influence Clock B (Tower AudioPump clock)
- State **MUST NOT** influence segment duration
- State **MUST NOT** influence decoder pacing
- State **MUST NOT** influence buffer behavior
- State **MUST NOT** be used for timing synchronization
- State **MUST NOT** be used for drift correction
- State **MUST NOT** be used for cadence alignment

### F.3 — Decoder Seeking

NowPlayingState **MUST NOT** trigger decoder seeking or position changes.

- State queries **MUST NOT** cause decoder to seek
- State updates **MUST NOT** trigger decoder position adjustments
- State **MUST NOT** be used to control decoder behavior
- Decoder **MUST** operate independently of NowPlayingState

### F.4 — Buffer-Based State Mutation

NowPlayingState **MUST NOT** be mutated based on buffer state.

- State **MUST NOT** be updated when buffer depth changes
- State **MUST NOT** be updated when buffer underflow occurs
- State **MUST NOT** be updated when buffer overflow occurs
- Buffer state **MUST NOT** influence NowPlayingState updates

### F.5 — Poll-Driven Recomputation

NowPlayingState **MUST NOT** be recomputed based on polling.

- State **MUST NOT** be recalculated periodically
- State **MUST NOT** be updated based on timer events
- State **MUST NOT** be updated based on heartbeat events
- State **MUST** be updated only at segment lifecycle boundaries

### F.6 — State-Based Decision Making

NowPlayingState **MUST NOT** influence DJ or playout decisions.

- DJ THINK **MUST NOT** read NowPlayingState for decision-making
- DJ DO **MUST NOT** read NowPlayingState for execution
- PlayoutEngine **MUST NOT** use NowPlayingState for playout control
- State **MUST NOT** influence segment selection logic
- State **MUST NOT** influence rotation management

### F.7 — Write Operations

No write operations **MAY** be exposed for NowPlayingState.

- HTTP POST/PUT/PATCH/DELETE **MUST NOT** be accepted
- WebSocket write messages **MUST NOT** modify state
- No API **MAY** allow external modification of state
- State **MUST** be modified only by Station's internal segment lifecycle handlers

---

## I. Invariants

### I.1 — Read-Only Authority

**NowPlayingState is observational only. No consumer may influence Station behavior via this state.**

- All consumers **MUST** be read-only
- Station **MUST** be the only writer
- No external system **MAY** modify state
- State queries **MUST NOT** affect playout behavior

### I.2 — Single Writer

**Station is the only writer of NowPlayingState. Tower and all clients are read-only consumers.**

- Station **MUST** be the sole authority for state updates
- Tower **MUST NOT** write to NowPlayingState
- External clients **MUST NOT** write to NowPlayingState
- All state modifications **MUST** originate from Station's segment lifecycle handlers

### I.3 — No Timing Authority

**NowPlayingState MUST NOT control, adjust, or influence Clock A, Clock B, segment duration, decoder pacing, or buffer behavior.**

- State **MUST NOT** influence any timing mechanism
- State **MUST NOT** be used for synchronization
- State **MUST NOT** affect playout timing decisions
- Timing systems **MUST** operate independently of NowPlayingState

### I.4 — Update Discipline

**State is created on segment_started, cleared on segment_finished, and MUST NOT be mutated mid-segment.**

- State **MUST** be created only at `on_segment_started`
- State **MUST** be cleared only at `on_segment_finished`
- State **MUST NOT** be modified during segment playback
- No mid-segment updates **MAY** occur

### I.5 — State Consistency

**All exposure mechanisms MUST represent the same underlying state.**

- WebSocket events and REST endpoints **MUST** return identical state
- State **MUST** be consistent across all observers
- State **MUST** be derived from a single authoritative source

### I.6 — Non-Blocking Observation

**State queries and updates MUST NOT block playout operations.**

- State queries **MUST NOT** delay segment lifecycle events
- State updates **MUST NOT** block playout thread
- Exposure failures **MUST NOT** affect playout behavior

### I.7 — Lifecycle Alignment

**State MUST align with segment lifecycle events.**

- State creation **MUST** occur synchronously with `on_segment_started`
- State clearing **MUST** occur synchronously with `on_segment_finished`
- State **MUST** reflect the segment that triggered the most recent `on_segment_started` event
- State **MUST NOT** reflect segments that have completed

---

## Non-Goals

**This contract does NOT define:**

- **UI behavior:** How state is displayed to users
- **Styling:** Visual presentation of state information
- **Polling rates:** How frequently clients should query state
- **Analytics:** How state is used for metrics or logging
- **Timing control:** How timing is managed (see PlayoutEngine Contract)
- **Playout logic:** How segments are selected and played (see DJ Engine Contract, PlayoutEngine Contract)
- **Metadata extraction:** How MP3 metadata is retrieved (see AudioEvent Contract, DJ Intent Contract)
- **Event delivery guarantees:** Reliability or ordering of WebSocket events
- **Caching strategies:** How state is cached or stored

**This contract focuses exclusively on:**

- The structure and meaning of NowPlayingState
- When and how state is created and cleared
- How state is exposed to observers
- What behaviors are explicitly forbidden
- Invariants that protect playout timing and decision-making

---

## Related Contracts

This contract references and depends on:

- **`AUDIO_EVENT_CONTRACT.md`** — Defines AudioEvent structure and metadata fields
- **`PLAYOUT_ENGINE_CONTRACT.md`** — Defines segment lifecycle events (`on_segment_started`, `on_segment_finished`)
- **`DJ_INTENT_CONTRACT.md`** — Defines DJIntent structure and metadata sources
- **`MASTER_SYSTEM_CONTRACT.md`** — Defines THINK/DO event model and segment lifecycle

**This contract complements these contracts by:**

- Providing observational access to segment state without influencing playout behavior
- Enabling external systems to observe current playout without affecting timing or decisions
- Maintaining strict separation between observation and control

---

## Implementation Notes

- NowPlayingState **MUST** be implemented as an immutable data structure
- State **MUST** be created in the handler for `on_segment_started` event
- State **MUST** be cleared in the handler for `on_segment_finished` event
- State **MUST** be stored in a thread-safe location accessible to all exposure mechanisms
- State queries **MUST** be non-blocking and **MUST NOT** acquire locks that could delay playout
- WebSocket broadcasts **MUST** be emitted from a non-blocking thread or queue
- REST endpoint **MUST** read state atomically without blocking playout operations
- State **MUST** be derived from AudioEvent metadata populated during THINK phase
- State **MUST NOT** trigger additional metadata extraction during DO or playout phases

---

## Rationale

This contract exists to enable external systems to observe what is currently playing while maintaining strict architectural boundaries. By prohibiting state from influencing timing, decisions, or playout behavior, this contract ensures that "Now Playing" features remain purely observational and do not compromise Phase 1.0 invariants.

The key insight is that observation and control must remain strictly separated. NowPlayingState provides a read-only window into the system's current playout state, but it must never become a timing surface or decision-making input. This separation allows fun, visible features (like "Now Playing" displays) while protecting the core playout timing and decision-making systems from external influence.
