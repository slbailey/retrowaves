# DJIntent Contract

## Purpose

Defines **WHAT** an intent is. This contract specifies the structure and validity rules for DJIntent, but contains no behavior.

---

## INT1 — Structure Rules

### INT1.1 — Required Fields

**DJIntent** **MUST** contain:

- **`next_song`**: `AudioEvent?` (required for normal intents, optional for terminal intents) — The next song to play
  - **MUST** include MP3 metadata in `AudioEvent.metadata` field (title, artist, album, duration) when present
  - Metadata **MUST** be collected during THINK phase and stored with the intent
  - **MAY** be `None` for terminal intents (per INT2.4)
- **`outro`**: `AudioEvent?` (optional) — Outro clip for current song
- **`station_ids`**: `list[AudioEvent]` — List of station identification clips (0..N)
- **`intro`**: `AudioEvent?` (optional) — Intro clip for next song (or shutdown announcement for terminal intents)
- **`has_legal_id`**: `bool` — Whether any ID in `station_ids` is a legal ID

### INT1.2 — Segment Metadata Requirements

**For all non-song AudioEvents (intro, outro, station_ids, talk segments, etc.), the AudioEvent metadata MUST include:**

- **`segment_class`**: `str` (required) — What kind of segment this is
  - **MUST** be one of: `"station_id"`, `"dj_talk"`, `"promo"`, `"imaging"`, `"radio_drama"`, `"album_segment"`, `"emergency"`, `"special"`
  - **MUST** be set during THINK phase when AudioEvent is created
- **`segment_role`**: `str` (required) — Why it exists in the flow
  - **MUST** be one of: `"intro"`, `"outro"`, `"interstitial"`, `"top_of_hour"`, `"legal"`, `"transition"`, `"standalone"`
  - **MUST** be set during THINK phase when AudioEvent is created
- **`production_type`**: `str` (required) — How it was produced
  - **MUST** be one of: `"live_dj"`, `"voice_tracked"`, `"produced"`, `"system"`
  - **MUST** be set during THINK phase when AudioEvent is created

**Note:** "DJ talking" is no longer a top-level concept. DJ talk segments are represented as AudioEvents with `segment_class="dj_talk"` and appropriate `segment_role` and `production_type` values. When a non-song segment starts playing, PlayoutEngine emits a `segment_playing` event (not `dj_talking`) with this metadata.

---

## INT2 — Validity Rules

### INT2.1 — Path Resolution

**ALL** paths **MUST** be resolvable MP3 files at **THINK** time.

- All `AudioEvent.file_path` values must exist and be readable
- Paths must be absolute (not relative)
- Files must be valid MP3 format
- Validation occurs during THINK, not during DO

### INT2.2 — Immutability

**DJIntent** **MUST** be immutable once **THINK** finishes.

- Intent is created during THINK phase
- Intent is passed to DO phase as read-only
- No modifications allowed after THINK completes

### INT2.3 — Single Consumption

**DJIntent** **MUST** be consumed exactly once during **DO**.

- DO phase receives intent and executes it
- Intent is not reused for subsequent segments
- Each segment gets a new intent from THINK

### INT2.4 — Terminal Intent

**DJIntent MAY be marked as TERMINAL to signal end-of-stream.**

- DJIntent **MAY** represent a terminal lifecycle intent
- Terminal intent **MUST** be consumed exactly once (same as normal intent)
- Terminal intent **MUST** produce no follow-up THINK cycle
- Terminal intent **MUST** signal end-of-stream after execution
- Terminal intent **MAY** contain only terminal AudioEvents (e.g., shutdown announcement)
- Terminal intent **MAY** contain no AudioEvents if no shutdown announcement is available
- Terminal intent structure **MUST** remain backward compatible with existing DJIntent structure
- No new intent types or classes **MAY** be introduced
- Terminal intent **MUST** contain standard AudioEvent(s) only (per AudioEvent Contract)
- The `is_terminal` flag is a semantic marker indicating end-of-stream behavior, not a structural change to DJIntent
- After terminal intent execution, the system **MUST** transition to SHUTTING_DOWN state (per StationLifecycle Contract)

---

## Implementation Notes

- DJIntent is a dataclass or similar immutable structure
- All paths are validated during THINK phase
- MP3 metadata for `next_song` is extracted during THINK phase and stored in `AudioEvent.metadata`
- For non-song segments, `segment_class`, `segment_role`, and `production_type` **MUST** be set during THINK phase and stored in `AudioEvent.metadata`
- Metadata is retrieved from the intent when state is updated and edge-triggered events are emitted during segment start
  - `song_playing` events are emitted for song segments
  - `segment_playing` events are emitted for non-song segments (not `dj_talking`)
  - NOTE: `now_playing` event deprecated - use stateful querying via Station State Contract and edge-triggered events (`song_playing`, `segment_playing`) instead
- DO phase trusts that intent is valid and complete
- Intent may contain empty lists (e.g., no IDs) but must be structurally complete
- Intent produces `segment_playing` events (not `dj_talking`) for all non-song segments






