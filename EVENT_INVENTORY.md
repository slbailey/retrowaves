# Event Inventory - Station → Tower System

## Purpose

This document defines the complete inventory of **edge-triggered transition events** emitted in the Station → Tower system. All events originate from Station and are received and broadcast by Tower.

**CRITICAL:** Events represent **edge-triggered transitions only**. There are NO "clear", "end", or empty-metadata events. Current state MUST be queried via Station State Contract (see `STATION_STATE_CONTRACT.md`).

---

## Events vs State: Non-Overlapping Responsibilities

**Events are EDGE-TRIGGERED transitions only. State is LEVEL-TRIGGERED and queryable.**

- **Events** fire ONCE per state transition (e.g., `song_playing` fires when song starts)
- **State** is queryable current truth at any moment (query via Station State Contract)
- **No overlap**: Events do NOT represent state; state is NOT represented by events
- **No inference**: Absence of events NEVER implies absence of state
- **Explicit querying**: Current state MUST be queried; it cannot be inferred from events

See `MASTER_SYSTEM_CONTRACT.md` (E0.8) for complete Events vs State separation principles.

---

## System-Wide Edge-Triggered Events

The following events represent the complete set of edge-triggered transitions for system-wide observability:

| Event Name | Authority | Emitter | When It Fires | Metadata Requirements | Idempotency |
|------------|-----------|---------|---------------|----------------------|-------------|
| `station_startup` | Station | Station | When `Station.start()` completes and playout begins, synchronously before first segment starts | **MUST** be empty `{}` | Idempotent-safe: may be re-emitted on restart |
| `song_playing` | Station | PlayoutEngine | When song segment starts (`on_segment_started` with `segment_type="song"`), before audio begins | **MUST** include full AudioEvent metadata: `segment_type: "song"`, `started_at` (required), `title?`, `artist?`, `album?`, `year?`, `duration_sec?`, `file_path?` (optional when unavailable) | Idempotent-safe: may be re-emitted on restart; each song start is distinct |
| `segment_playing` | Station | PlayoutEngine | When non-song segment starts (`on_segment_started` with `segment_type` not equal to `"song"`), before audio begins | **MUST** include required metadata: `segment_class`, `segment_role`, `production_type` (see metadata schema below) | Idempotent-safe: may be re-emitted on restart; each segment start is distinct |
| `station_shutdown` | Station | Station | When terminal playout completes (or timeout), synchronously after last segment finishes, before SHUTTING_DOWN state | **MUST** be empty `{}` | Idempotent-safe: may be re-emitted on restart; each shutdown is distinct |

### Event Lifecycle Moments

**`station_startup`:**
- Fires exactly ONCE when `Station.start()` completes
- Fires synchronously before the first segment (startup announcement or first song) starts
- Represents transition from non-operational to operational state

**`song_playing`:**
- Fires exactly ONCE per song segment start
- Fires synchronously when `on_segment_started` is emitted with `segment_type="song"`
- Represents transition to song content state
- Metadata **MUST NOT** be empty; if metadata unavailable, fallback metadata (e.g., empty strings) **MUST** be provided

**`segment_playing`:**
- Fires exactly ONCE per non-song segment start
- Fires synchronously when `on_segment_started` is emitted with `segment_type` not equal to `"song"`
- Represents transition to non-song content state (station IDs, DJ talk, promos, radio dramas, album segments, etc.)
- **MUST** include required metadata: `segment_class`, `segment_role`, `production_type`

**`station_shutdown`:**
- Fires exactly ONCE when terminal playout completes (or timeout occurs)
- Fires synchronously after the last segment finishes (or timeout)
- Fires before Station enters SHUTTING_DOWN state and performs final cleanup
- Represents transition from operational to non-operational state

### segment_playing Event Metadata Schema

**Station IDs, DJ talk, promos, radio dramas, and all non-song audio are represented as `segment_playing`.**

The `segment_playing` event **MUST** include the following required metadata fields:

#### Required Metadata Fields

| Field | Type | Description |
|-------|------|-------------|
| `segment_class` | enum | What kind of segment this is (see segment_class enum below) |
| `segment_role` | enum | Why it exists in the flow (see segment_role enum below) |
| `production_type` | enum | How it was produced (see production_type enum below) |

#### segment_class Enum (closed but extensible)

The `segment_class` field **MUST** be exactly one of:

- `station_id` — Station identification clip (produced or DJ)
- `dj_talk` — DJ talking (intro, outro, general)
- `promo` — Promotional content
- `imaging` — Station imaging/imaging elements
- `radio_drama` — Radio drama content
- `album_segment` — Album segment (e.g., album intro, outro, interlude)
- `emergency` — Emergency alert/announcement
- `special` — Special segment type (future extensibility)

#### segment_role Enum

The `segment_role` field **MUST** be exactly one of:

- `intro` — Introduction segment (e.g., song intro, show intro)
- `outro` — Outro segment (e.g., song outro, show outro)
- `interstitial` — Interstitial content between main segments
- `top_of_hour` — Top-of-hour identification
- `legal` — Legal ID requirement
- `transition` — Transitional content
- `standalone` — Standalone segment (not tied to another segment)

#### production_type Enum

The `production_type` field **MUST** be exactly one of:

- `live_dj` — Live DJ-produced content
- `voice_tracked` — Voice-tracked content
- `produced` — Pre-produced content
- `system` — System-generated content

#### Optional Metadata Fields

The following fields **MAY** be included but are not required:

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | string | Absolute path to the audio file |
| `duration_sec` | float | Duration of the segment in seconds |
| `series_id` | string | Series identifier (for radio dramas, etc.) |
| `episode_id` | string | Episode identifier (for radio dramas, etc.) |
| `part_number` | int | Part number within a multi-part segment |
| `total_parts` | int | Total number of parts in a multi-part segment |
| `legal` | boolean | Whether this segment satisfies legal ID requirements |

**Metadata Semantics:**
- Tower treats all metadata as opaque and does not interpret or validate metadata fields
- Metadata is provided for observability and downstream system consumption
- Required fields **MUST** be present on every `segment_playing` event
- Optional fields **MAY** be omitted if not applicable or unavailable

### Content Plane Invariant

**There is no such thing as "nothing is playing" in the content plane. Absence is represented ONLY via lifecycle or error states.**

- When Station is operational (RUNNING state), there is ALWAYS content playing or about to play
- Fallback content is a STATE, not an absence
- Empty or cleared state does NOT represent "nothing playing" — it represents a lifecycle transition or error condition
- Consumers **MUST NOT** infer absence of content from state queries; absence is a lifecycle state (startup, shutdown, error)

---

## THINK/DO Events

The following events are emitted during THINK/DO lifecycle phases (see `MASTER_SYSTEM_CONTRACT.md`):

| Event Name | Authority | Emitter | When It Fires | Metadata | Idempotency |
|------------|-----------|---------|---------------|----------|-------------|
| `dj_think_started` | Station | DJEngine | Before THINK logic begins (`on_segment_started` callback) | `{current_segment}` | Idempotent-safe: may be re-emitted on restart |
| `dj_think_completed` | Station | DJEngine | After THINK logic completes (before DO phase) | `{think_duration_ms, dj_intent?}` | Idempotent-safe: may be re-emitted on restart |

---

## Buffer Health Events

The following events are emitted when buffer conditions are detected (see `OUTPUT_SINK_CONTRACT.md`):

| Event Name | Authority | Emitter | When It Fires | Metadata | Idempotency |
|------------|-----------|---------|---------------|----------|-------------|
| `station_underflow` | Station | OutputSink (TowerPCMSink) | When buffer depth transitions from non-zero to zero (checked periodically during frame writes) | `{buffer_depth, frames_dropped}` | Idempotent-safe: may be re-emitted on restart |
| `station_overflow` | Station | OutputSink (TowerPCMSink) | When buffer depth transitions to capacity/overflow condition (checked periodically during frame writes) | `{buffer_depth, frames_dropped}` | Idempotent-safe: may be re-emitted on restart |

---

## Deprecated Events

**`now_playing` event is COMPLETELY DEPRECATED and MUST NOT be emitted.**

- **FORBIDDEN**: Emitting `now_playing` events with any metadata (including empty metadata)
- **FORBIDDEN**: Using `now_playing` events to represent current state
- **FORBIDDEN**: Inferring state from `now_playing` event presence or absence
- **REQUIRED**: Use stateful querying via Station State Contract for current state
- **REQUIRED**: Use edge-triggered events (`song_playing`, `segment_playing`, `station_startup`, `station_shutdown`) for transitions
- Consumers **MUST NOT** rely on `now_playing` events; all consumers MUST migrate to stateful querying

**`dj_talking` event is COMPLETELY DEPRECATED and MUST NOT be emitted.**

- **FORBIDDEN**: Emitting `dj_talking` events with any metadata (including empty metadata)
- **FORBIDDEN**: Using `dj_talking` events to represent DJ talk or non-song segments
- **REQUIRED**: Use `segment_playing` event with appropriate `segment_class`, `segment_role`, and `production_type` metadata instead
- **REQUIRED**: DJ talk segments must emit `segment_playing` with `segment_class="dj_talk"` and appropriate `segment_role` and `production_type`
- No backward compatibility promises; no transitional aliases
- Consumers **MUST NOT** rely on `dj_talking` events; all consumers MUST migrate to `segment_playing`

**`station_starting_up` and `station_shutting_down` events are DEPRECATED.**

- **DEPRECATED**: Use `station_startup` instead of `station_starting_up`
- **DEPRECATED**: Use `station_shutdown` instead of `station_shutting_down`
- These deprecated events **MUST NOT** be emitted going forward

---

## Event Authority and Flow

### Event Authority

- **Station Authority**: Events are emitted by Station components (PlayoutEngine, DJEngine, OutputSink, Station)
- **Tower Authority**: Tower receives and broadcasts Station events. Tower does NOT emit events in this system
- **Event Flow**: Station → Tower (one-way). Tower adds `tower_received_at` timestamp and `event_id` to received events but does NOT modify semantic meaning

### Tower Event Processing

- Tower receives events via `/tower/events/ingest` endpoint
- Tower adds `tower_received_at` timestamp and `event_id` to received events
- Tower broadcasts events to WebSocket clients via `/tower/events` endpoint
- Tower does NOT modify event semantic meaning
- Tower does NOT emit its own events (one-way: Station → Tower)
- Tower does NOT infer state from events; Tower remains stateless and non-influential

---

## Event Flow Summary

1. **Station Lifecycle Events**: `station_startup` → (playout) → `station_shutdown`
2. **Content Events**: `song_playing` (when song segments start), `segment_playing` (when non-song segments start)
3. **THINK/DO Events**: `dj_think_started` → (THINK logic) → `dj_think_completed` → (DO phase)
4. **Buffer Health Events**: `station_underflow`, `station_overflow` (when buffer conditions detected)

**Note:** Events represent edge-triggered transitions only. Current state must be queried via Station State Contract. No event implies absence of state; query state to determine current truth.

---

## Related Contracts

- **Master System Contract** (`MASTER_SYSTEM_CONTRACT.md`): Defines Events vs State separation (E0.8) and event definitions (E0.9)
- **Station State Contract** (`STATION_STATE_CONTRACT.md`): Defines stateful querying interface
- **Station Lifecycle Contract** (`STATION_LIFECYCLE_CONTRACT.md`): Defines startup and shutdown lifecycle
- **PlayoutEngine Contract** (`PLAYOUT_ENGINE_CONTRACT.md`): Defines event emission from PlayoutEngine
- **OutputSink Contract** (`OUTPUT_SINK_CONTRACT.md`): Defines buffer health event emission
