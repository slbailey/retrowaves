# DJIntent Contract

## Purpose

Defines **WHAT** an intent is. This contract specifies the structure and validity rules for DJIntent, but contains no behavior.

---

## INT1 — Structure Rules

### INT1.1 — Required Fields

**DJIntent** **MUST** contain:

- **`next_song`**: `AudioEvent` (required) — The next song to play
- **`outro`**: `AudioEvent?` (optional) — Outro clip for current song
- **`station_ids`**: `list[AudioEvent]` — List of station identification clips (0..N)
- **`intro`**: `AudioEvent?` (optional) — Intro clip for next song
- **`has_legal_id`**: `bool` — Whether any ID in `station_ids` is a legal ID

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

---

## Implementation Notes

- DJIntent is a dataclass or similar immutable structure
- All paths are validated during THINK phase
- DO phase trusts that intent is valid and complete
- Intent may contain empty lists (e.g., no IDs) but must be structurally complete





