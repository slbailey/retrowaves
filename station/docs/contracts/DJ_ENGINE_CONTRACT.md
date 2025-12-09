# DJEngine Contract

## Purpose

This is the behavioral heart of Station: the DJ is the brain that makes all content decisions during the THINK phase.

---

## DJ1 — THINK Responsibilities

### DJ1.1 — THINK Operations

**THINK** **MUST**:

- Select `next_song` via RotationManager
- Select 0..N IDs (station identification clips)
- Optionally select `intro` and/or `outro` for the next song
- Determine whether selected ID is legal (metadata only, no file I/O)

### DJ1.2 — DJIntent Production

**THINK** **MUST** produce a complete **DJIntent** containing **ONLY** concrete MP3 paths.

- All paths must be absolute file paths
- All paths must reference existing, playable MP3 files
- Intent must be complete and immutable once THINK finishes

### DJ1.3 — THINK Prohibitions

**THINK** **MUST NOT**:

- Alter playout queue (queue modification is DO's responsibility)
- Perform audio decoding (decoding is PlayoutEngine's responsibility)
- Make network calls (all data must be cached or local)
- Perform file I/O except via cached discovery (AssetDiscoveryManager provides cached lists)

---

## DJ2 — Decision Rules

### DJ2.1 — Pacing Rules

Selection **MUST** follow pacing rules:

- **Cooldowns**: Next song must not be in cooldown window
- **Last-N avoidance**: Recently played tracks must be avoided
- **Legal ID timing**: IDs must be spaced according to legal requirements
- All rules must be checked before selection

### DJ2.2 — Fallback Substitutions

**THINK** **MUST** apply fallback substitutions if requested assets are missing.

- If selected intro is missing, use no intro (not an error)
- If selected outro is missing, use no outro (not an error)
- If selected ID is missing, skip ID (not an error)
- If next_song is missing, fall back to safe default (tone or silence)

### DJ2.3 — Time Bounded

**THINK** **MUST** be time-bounded — it **MAY NOT** exceed segment runtime.

- THINK must complete before current segment finishes
- If THINK takes too long, fall back to safe default intent
- No blocking operations allowed during THINK

---

## DJ3 — State Rules

### DJ3.1 — State Maintenance

**DJEngine** **MUST** maintain:

- **Recent rotations**: History of recently played tracks
- **Cooldowns**: Timestamps of when tracks can be played again
- **Legal ID timestamps**: When IDs were last played (for legal spacing)
- **Tickler queue**: Future content requests (if applicable)

### DJ3.2 — State Mutation Prohibition

**DJEngine** **MUST NOT** mutate playout or audio pipeline directly.

- DJEngine only produces DJIntent
- Queue mutations occur only during DO phase
- Audio pipeline is controlled by PlayoutEngine

---

## DJ4 — THINK Lifecycle Events

DJEngine **MUST** emit control-channel events for THINK phase observability. These events are purely observational and **MUST NOT** influence THINK execution or decision-making.

### DJ4.1 — THINK Started Event

**MUST** emit `dj_think_started` event before THINK logic begins.

- Event **MUST** be emitted synchronously before any THINK operations
- Event **MUST NOT** block THINK execution
- Event **MUST** include metadata:
  - `timestamp`: Wall-clock timestamp (`time.monotonic()`) when event is emitted
  - `current_segment`: The AudioEvent currently playing (that triggered this THINK phase)
- Event **MUST** be emitted from the THINK thread (typically during `on_segment_started()` callback)
- Event **MUST NOT** modify queue or state
- Event **MUST NOT** rely on Tower timing or state

### DJ4.2 — THINK Completed Event

**MUST** emit `dj_think_completed` event after THINK logic completes (before DO phase begins).

- Event **MUST** be emitted synchronously after all THINK operations complete
- Event **MUST NOT** block DO phase execution
- Event **MUST** include metadata:
  - `timestamp`: Wall-clock timestamp (`time.monotonic()`) when event is emitted
  - `dj_intent`: The DJIntent produced by THINK (read-only reference)
  - `think_duration_ms`: Duration of THINK phase in milliseconds
- Event **MUST** be emitted from the THINK thread (typically during `on_segment_started()` callback)
- Event **MUST NOT** modify queue or state
- Event **MUST NOT** rely on Tower timing or state
- Event **MUST** be emitted after DJIntent is complete and immutable

### DJ4.3 — Event Emission Rules

All THINK lifecycle events **MUST** follow these behavioral rules:

- **Non-blocking**: Events **MUST NOT** block THINK execution or delay decision-making
- **Observational only**: Events **MUST NOT** influence song selection, ID selection, or any THINK decisions
- **Station-local**: Events **MUST NOT** rely on Tower timing, Tower state, or PCM write success/failure
- **Clock A only**: Events **MUST** use Clock A (wall clock) for all timing measurements
- **No state mutation**: Events **MUST NOT** modify queue, rotation history, or any system state
- **Lifecycle boundaries**: Events **MUST** be emitted at the correct lifecycle boundaries (before/after THINK logic)
- **Metadata completeness**: Events **MUST** include all required metadata fields
- **THINK/DO separation**: Events **MUST** respect THINK/DO boundaries (events emitted during THINK, not DO)

---

## Implementation Notes

- DJEngine is called during `on_segment_started()` callback (THINK phase)
- DJEngine uses RotationManager for song selection
- DJEngine uses AssetDiscoveryManager for asset lists
- DJEngine uses DJStateStore for persisted state
- All decisions are made synchronously during THINK




