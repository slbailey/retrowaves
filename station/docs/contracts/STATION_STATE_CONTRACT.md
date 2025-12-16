# Station State Contract

## Purpose

Defines the **authoritative, queryable runtime state** of Station. This contract establishes Station State as the single source of truth for current operational status, independent of event history.

**Hard Requirements:**
- State **MUST** be queryable at any time
- State **MUST NOT** require event replay
- State **MUST** be authoritative over events
- State **MUST** update synchronously with segment lifecycle transitions

**Cross-Contract References:**
- **Events:** See `EVENT_INVENTORY.md` for edge-triggered transition events
- **Master System:** See `MASTER_SYSTEM_CONTRACT.md` for THINK/DO event model
- **PlayoutEngine:** See `PLAYOUT_ENGINE_CONTRACT.md` for segment lifecycle
- **AudioEvent:** See `AUDIO_EVENT_CONTRACT.md` for segment structure and metadata

---

## S. State Definition

### S.1 — Allowed Station States (Finite Set)

Station **MUST** define a finite set of allowed operational states. The state **MUST** be exactly one of:

- **`STARTING_UP`**: Station startup announcement playout in progress while systems initialize
- **`SONG_PLAYING`**: Station is actively playing a song segment
- **`DJ_TALKING`**: Station is actively playing a DJ talk segment
- **`FALLBACK`**: Station is playing fallback content (error recovery or default content)
- **`SHUTTING_DOWN`**: Station shutdown announcement (terminal playout) in progress
- **`ERROR`**: Station has encountered an error condition

**State Semantics:**
- State **MUST** be exactly one of the above values at all times
- State **MUST NOT** be `None`, `null`, or undefined
- State **MUST** transition atomically (no intermediate states)
- State **MUST** reflect the current operational truth, not historical events

### S.2 — Required State Fields

Station State **MUST** define the following required fields:

#### S.2.1 — `station_state`

- **Type:** `str` (required, non-nullable)
- **Values:** **MUST** be exactly one of: `"STARTING_UP"`, `"SONG_PLAYING"`, `"DJ_TALKING"`, `"FALLBACK"`, `"SHUTTING_DOWN"`, `"ERROR"`
- **Semantics:** Represents the current operational state of Station
- **MUST** be present in all state queries
- **MUST NOT** be `None` or `null`

#### S.2.2 — `since`

- **Type:** `float` (required, non-nullable)
- **Semantics:** Monotonic timestamp indicating when the current state was entered
- **MUST** be a monotonic timestamp (e.g., `time.monotonic()` or equivalent)
- **MUST** represent the exact moment the current state was entered
- **MUST NOT** be adjusted or corrected after state entry
- **MUST NOT** be a wall-clock timestamp (must be monotonic)
- **MUST** be present in all state queries
- **MUST NOT** be `None` or `null`

#### S.2.3 — `current_audio`

- **Type:** `object?` (required field, nullable value)
- **Semantics:** Represents the currently playing audio segment
- **MUST** be an object with the following structure when audio is playing:

**`current_audio` Object Fields (when not null):**

- **`segment_type`**: `str` (required, non-nullable)
  - **MUST** be one of: `"song"`, `"segment"`, `"fallback"`
  - For song segments: **MUST** be `"song"`
  - For non-song segments (station IDs, DJ talk, promos, radio dramas, album segments, etc.): **MUST** be `"segment"`
  - For fallback content: **MUST** be `"fallback"`
  - **MUST** be derived from the active AudioEvent's type
  - **MUST NOT** be `None` or `null` when `current_audio` is not null

- **`file_path`**: `str` (required, non-nullable)
  - **MUST** be the absolute path to the audio file being played
  - **MUST NOT** be a relative path
  - **MUST NOT** be `None` or `null` when `current_audio` is not null

- **`started_at`**: `float` (required, non-nullable)
  - **MUST** be a wall-clock timestamp (e.g., `time.time()` or UTC epoch seconds) captured at segment start
  - **MUST** represent the exact moment `on_segment_started` was emitted
  - **MUST NOT** be adjusted or corrected after creation
  - **MUST NOT** be `None` or `null` when `current_audio` is not null

- **`title`**: `str?` (optional, nullable)
  - **MAY** be `None` or `null` if metadata is unavailable
  - **MUST** be extracted from AudioEvent metadata when available
  - **MUST** be derived from MP3 tags for song segments

- **`artist`**: `str?` (optional, nullable)
  - **MAY** be `None` or `null` if metadata is unavailable
  - **MUST** be extracted from AudioEvent metadata when available
  - **MUST** be derived from MP3 tags for song segments

- **`duration_sec`**: `float?` (optional, nullable)
  - **MAY** be `None` or `null` if duration cannot be determined
  - **MUST** be derived from AudioEvent metadata or file duration when available
  - **MUST** represent the actual file duration, not estimated or adjusted duration

- **`segment_class`**: `str?` (optional, nullable, for non-song segments only)
  - **MAY** be `None` or `null` for song segments
  - **MUST** be present for non-song segments (`segment_type="segment"`)
  - **MUST** be one of: `"station_id"`, `"dj_talk"`, `"promo"`, `"imaging"`, `"radio_drama"`, `"album_segment"`, `"emergency"`, `"special"`
  - **MUST** mirror the `segment_class` value from the corresponding `segment_playing` event metadata

- **`segment_role`**: `str?` (optional, nullable, for non-song segments only)
  - **MAY** be `None` or `null` for song segments
  - **MUST** be present for non-song segments (`segment_type="segment"`)
  - **MUST** be one of: `"intro"`, `"outro"`, `"interstitial"`, `"top_of_hour"`, `"legal"`, `"transition"`, `"standalone"`
  - **MUST** mirror the `segment_role` value from the corresponding `segment_playing` event metadata

- **`production_type`**: `str?` (optional, nullable, for non-song segments only)
  - **MAY** be `None` or `null` for song segments
  - **MUST** be present for non-song segments (`segment_type="segment"`)
  - **MUST** be one of: `"live_dj"`, `"voice_tracked"`, `"produced"`, `"system"`
  - **MUST** mirror the `production_type` value from the corresponding `segment_playing` event metadata

**Note:** For non-song segments, the segment metadata (`segment_class`, `segment_role`, `production_type`) **MUST** mirror the metadata from the corresponding `segment_playing` event. This ensures consistency between state queries and event announcements.

**`current_audio` Nullability Rules:**

**MUST be non-null when station_state is:**
- `STARTING_UP`
- `SONG_PLAYING`
- `DJ_TALKING`
- `FALLBACK`
- `SHUTTING_DOWN`

**MUST be null when station_state is:**
- `ERROR`

### S.3 — Derived Fields Prohibition

Station State **MUST NOT** include computed or derived fields that require ongoing calculation:

- **FORBIDDEN:** Elapsed time calculations
- **FORBIDDEN:** Remaining time calculations
- **FORBIDDEN:** Progress percentage
- **FORBIDDEN:** Estimated completion timestamps
- **FORBIDDEN:** Any field that requires periodic updates during segment playback

Observers **MAY** compute these values from `started_at` and `duration_sec`, but the state itself **MUST NOT** contain them.

---

## Q. Query Semantics

### Q.1 — Pull-Based Querying

Station **MUST** expose a pull-based query interface for state retrieval.

**Query interface requirements:**
- **MUST** be accessible via HTTP GET endpoint (e.g., `/station/state`)
- **MUST** return current state synchronously (no polling or async callbacks)
- **MUST** be idempotent (safe to call multiple times)
- **MUST** be non-blocking (must not delay playout operations)
- **MUST** return state in consistent format (JSON recommended)
- **MUST** be queryable at any time (no timing guarantees required)
- **MUST** return a coherent snapshot (atomic read)

### Q.2 — Query Response Format

Query response **MUST** include the following structure:

```json
{
  "station_state": "<STARTING_UP|SONG_PLAYING|DJ_TALKING|FALLBACK|SHUTTING_DOWN|ERROR>",
  "since": <float>,
  "current_audio": {
    "segment_type": "<string>",
    "file_path": "<string>",
    "started_at": <float>,
    "title": "<string> | null",
    "artist": "<string> | null",
    "duration_sec": <float> | null,
    "segment_class": "<string> | null",
    "segment_role": "<string> | null",
    "production_type": "<string> | null"
  } | null
}
```

**Response rules:**
- `station_state` **MUST** always be present and exactly one of the finite state set
- `since` **MUST** always be present and a valid monotonic timestamp
- `current_audio` **MUST** always be present (as a field), but its value **MAY** be `null`
- When `current_audio` is not `null`, `segment_type`, `file_path`, and `started_at` **MUST** be present and non-null
- When `current_audio` is not `null`, `title`, `artist`, and `duration_sec` **MAY** be `null` if metadata is unavailable
- When `current_audio` is not `null` and `segment_type` is `"segment"`, `segment_class`, `segment_role`, and `production_type` **MUST** be present and non-null
- When `current_audio` is not `null` and `segment_type` is `"song"`, `segment_class`, `segment_role`, and `production_type` **MAY** be `null`

### Q.3 — Query Timing Guarantees

**No timing guarantees are required for state queries.**

- Queries **MUST** return a coherent snapshot of current state
- Queries **MUST NOT** guarantee real-time updates
- Queries **MUST NOT** guarantee freshness (state may be slightly stale)
- Queries **MUST** be safe to call at any time without side effects
- Queries **MUST** return immediately (no blocking)

### Q.4 — Query Performance

State queries **MUST** be performant:

- Query response time **MUST** be < 10ms typical, < 100ms maximum
- Query **MUST NOT** block playout thread
- Query **MUST NOT** acquire locks that could delay playout
- Query **MUST** read state atomically (snapshot semantics)

---

## R. Relationship to Events

### R.1 — State is Authoritative

**State represents current truth. Events announce transitions.**

- State **MUST** be the authoritative source of truth for current operational status
- State **MUST** be queryable without knowledge of event history
- State **MUST** remain correct even if events are lost
- State **MUST NOT** depend on event replay to determine current truth

### R.2 — Events Announce Transitions

**Events represent edge-triggered transitions, not current state.**

- Events fire ONCE per transition (e.g., `song_playing` fires when song starts)
- Events **MUST NOT** fire "end" or "clear" events
- Events are observational announcements of state changes
- Events **MUST NOT** be treated as authoritative truth

### R.3 — State Updates Synchronized with Lifecycle

**State updates MUST occur synchronously with segment lifecycle transitions.**

- State **MUST** be updated when `on_segment_started` is emitted
- State **MUST** be updated when `on_segment_finished` is emitted
- State **MUST** be updated atomically (no partial state visible)
- State **MUST** reflect the segment that triggered the most recent `on_segment_started` event
- State **MUST** update synchronously with segment lifecycle transitions

### R.4 — Events May Be Lost; State Must Remain Correct

**Events are best-effort announcements. State must remain authoritative.**

- If events are lost (e.g., Tower disconnection), state **MUST** remain correct
- If events are reordered, state **MUST** remain correct
- If events are duplicated, state **MUST** remain correct
- State queries **MUST** provide authoritative truth regardless of event delivery
- Observers **MUST NOT** infer state from event presence or absence

---

## P. Prohibitions

### P.1 — Inferring State from Event History

**FORBIDDEN: Inferring state from event history.**

- **FORBIDDEN:** Replaying events to determine current state
- **FORBIDDEN:** Inferring state from event presence or absence
- **FORBIDDEN:** Treating event history as authoritative truth
- **FORBIDDEN:** Requiring event replay to query current state
- **REQUIRED:** State must be directly queryable without event history

### P.2 — Treating Events as Authoritative Truth

**FORBIDDEN: Treating events as authoritative truth.**

- **FORBIDDEN:** Using events to determine current operational state
- **FORBIDDEN:** Assuming absence of events implies absence of state
- **FORBIDDEN:** Using event timestamps to determine current state
- **REQUIRED:** Query state directly to determine current truth

### P.3 — Emitting Events to Represent "No Content"

**FORBIDDEN: Emitting events to represent "no content".**

- **FORBIDDEN:** Emitting "clear" or "end" events when segments finish
- **FORBIDDEN:** Emitting empty metadata events
- **FORBIDDEN:** Emitting events to signal absence of content
- **REQUIRED:** State query returns `current_audio: null` only when `station_state` is `ERROR`
- **REQUIRED:** Events only announce transitions, not absence

### P.4 — State Mutation Based on Events

**FORBIDDEN: Mutating state based on event replay or event history.**

- **FORBIDDEN:** Replaying events to reconstruct state
- **FORBIDDEN:** Mutating state based on event order
- **FORBIDDEN:** Mutating state based on event presence or absence
- **REQUIRED:** State must be updated synchronously with lifecycle transitions, not from event replay

---

## I. Invariants

### I.1 — State is Always Queryable

**State MUST be queryable at any time, without requiring event replay.**

- State queries **MUST** return a valid response at any time
- State queries **MUST NOT** require event history
- State queries **MUST NOT** require event replay
- State **MUST** be directly accessible without inference

### I.2 — State is Authoritative Over Events

**State MUST be authoritative over events. Events announce transitions; state represents current truth.**

- State **MUST** be the single source of truth for current operational status
- Events **MUST NOT** be used to determine current state
- State **MUST** remain correct even if events are lost
- State **MUST** be queryable without knowledge of event history

### I.3 — State Updates Synchronously with Lifecycle

**State MUST update synchronously with segment lifecycle transitions.**

- State **MUST** be updated when `on_segment_started` is emitted
- State **MUST** be updated when `on_segment_finished` is emitted
- State **MUST** be updated atomically (no partial state visible)
- State **MUST** reflect the segment that triggered the most recent `on_segment_started` event

### I.4 — Single Source of Truth

**Station is the ONLY writer of state. All state queries return the same underlying truth.**

- Station **MUST** be the sole authority for state updates
- Tower **MUST NOT** modify state
- External clients **MUST NOT** modify state
- HTTP endpoints **MUST NOT** accept state modifications
- All query mechanisms **MUST** return identical state

### I.5 — State Consistency

**State MUST be consistent across all query mechanisms and observers.**

- All query mechanisms **MUST** return identical state
- State **MUST** be consistent across all observers
- State **MUST** be derived from a single authoritative source
- State **MUST** be updated atomically (no partial state visible)

### I.6 — Non-Blocking Queries

**State queries MUST NOT block playout operations.**

- Queries **MUST NOT** delay segment lifecycle events
- Queries **MUST NOT** block playout thread
- Queries **MUST NOT** acquire locks that could delay playout
- Query failures **MUST NOT** affect playout behavior

### I.7 — No Timing Authority

**State MUST NOT control, adjust, or influence timing.**

- State **MUST NOT** influence Clock A (Station decode/content clock)
- State **MUST NOT** influence Clock B (Tower AudioPump clock)
- State **MUST NOT** influence segment duration
- State **MUST NOT** influence decoder pacing
- State **MUST NOT** influence buffer behavior

### I.8 — Observational Only

**State is observational only. No consumer may influence Station behavior via state queries.**

- All consumers **MUST** be read-only
- Station **MUST** be the only writer
- No external system **MAY** modify state
- State queries **MUST NOT** affect playout behavior

---

## E. Example JSON Responses

### E.1 — STARTING_UP State

```json
{
  "station_state": "STARTING_UP",
  "since": 12345.678,
  "current_audio": {
    "segment_type": "segment",
    "file_path": "/path/to/startup_announcement.mp3",
    "started_at": 1699123456.789,
    "title": null,
    "artist": null,
    "duration_sec": 10.0,
    "segment_class": "dj_talk",
    "segment_role": "standalone",
    "production_type": "system"
  }
}
```

### E.2 — SONG_PLAYING State

```json
{
  "station_state": "SONG_PLAYING",
  "since": 12345.678,
  "current_audio": {
    "segment_type": "song",
    "file_path": "/path/to/song.mp3",
    "started_at": 1699123456.789,
    "title": "Example Song",
    "artist": "Example Artist",
    "duration_sec": 180.5
  }
}
```

### E.3 — DJ_TALKING State

```json
{
  "station_state": "DJ_TALKING",
  "since": 12345.678,
  "current_audio": {
    "segment_type": "segment",
    "file_path": "/path/to/talk.mp3",
    "started_at": 1699123456.789,
    "title": null,
    "artist": null,
    "duration_sec": 30.0,
    "segment_class": "dj_talk",
    "segment_role": "interstitial",
    "production_type": "live_dj"
  }
}
```

### E.4 — FALLBACK State

```json
{
  "station_state": "FALLBACK",
  "since": 12345.678,
  "current_audio": {
    "segment_type": "fallback",
    "file_path": "/path/to/fallback.mp3",
    "started_at": 1699123456.789,
    "title": null,
    "artist": null,
    "duration_sec": 60.0
  }
}
```

### E.5 — SHUTTING_DOWN State

```json
{
  "station_state": "SHUTTING_DOWN",
  "since": 12345.678,
  "current_audio": {
    "segment_type": "segment",
    "file_path": "/path/to/shutdown_announcement.mp3",
    "started_at": 1699123456.789,
    "title": null,
    "artist": null,
    "duration_sec": 8.0,
    "segment_class": "dj_talk",
    "segment_role": "standalone",
    "production_type": "system"
  }
}
```

### E.6 — ERROR State

```json
{
  "station_state": "ERROR",
  "since": 12345.678,
  "current_audio": null
}
```

### E.7 — SONG_PLAYING State (Minimal Metadata)

```json
{
  "station_state": "SONG_PLAYING",
  "since": 12345.678,
  "current_audio": {
    "segment_type": "song",
    "file_path": "/path/to/song.mp3",
    "started_at": 1699123456.789,
    "title": null,
    "artist": null,
    "duration_sec": null
  }
}
```

---

## F. Forbidden Behaviors

### F.1 — Consumer Feedback Loops

State **MUST NOT** enable consumer feedback loops.

- Consumers **MUST NOT** influence Station behavior via state queries
- State queries **MUST NOT** trigger timing adjustments
- State queries **MUST NOT** influence DJ decision-making
- State queries **MUST NOT** affect segment selection
- State queries **MUST NOT** modify playout queue

### F.2 — Timing Authority

State **MUST NOT** control, adjust, or influence timing.

- State **MUST NOT** influence Clock A or Clock B
- State **MUST NOT** influence segment duration
- State **MUST NOT** influence decoder pacing
- State **MUST NOT** influence buffer behavior
- State **MUST NOT** be used for timing synchronization

### F.3 — Write Operations

No write operations **MAY** be exposed for state.

- HTTP POST/PUT/PATCH/DELETE **MUST NOT** be accepted
- WebSocket write messages **MUST NOT** modify state
- No API **MAY** allow external modification of state
- State **MUST** be modified only by Station's internal segment lifecycle handlers

### F.4 — Event-Based State Inference

State **MUST NOT** be inferred from events.

- State **MUST NOT** be reconstructed from event history
- State **MUST NOT** be determined by replaying events
- State **MUST NOT** be inferred from event presence or absence
- State **MUST** be directly queryable without event knowledge

---

## Implementation Notes

- State **MUST** be implemented as an immutable data structure
- State **MUST** be created/updated in the handler for `on_segment_started` event
- State **MUST** be updated in the handler for `on_segment_finished` event
- State **MUST** be stored in a thread-safe location accessible to all query mechanisms
- State queries **MUST** be non-blocking and **MUST NOT** acquire locks that could delay playout
- HTTP endpoint **MUST** read state atomically without blocking playout operations
- State **MUST** be derived from AudioEvent metadata populated during THINK phase
- State **MUST NOT** trigger additional metadata extraction during DO or playout phases
- `since` **MUST** use monotonic timestamps (e.g., `time.monotonic()`) to ensure monotonicity
- `started_at` **MUST** use wall-clock timestamps (e.g., `time.time()`) for absolute time reference

---

## Rationale

This contract establishes Station State as the authoritative, queryable runtime state of Station, independent of event history. By requiring state to be directly queryable without event replay, this contract ensures:

- **Authoritative truth**: State is always the source of truth, not events
- **Resilience**: State remains correct even if events are lost
- **Simplicity**: Observers query state directly, without inferring from events
- **Separation of concerns**: Events announce transitions; state represents current truth

The key principles are:
- **State is authoritative**: Events announce transitions; state represents current truth
- **No event replay required**: State is directly queryable without event history
- **Synchronous updates**: State updates synchronously with segment lifecycle transitions
- **Explicit prohibitions**: Inferring state from events is explicitly forbidden

This contract ensures that Station State remains the single source of truth for current operational status, regardless of event delivery guarantees or event history.
