# AudioEvent Contract

## Purpose

Defines the atomic unit of scheduled playout. AudioEvent represents a single audio file to be played.

---

## AE1 — Requirements

### AE1.1 — Required Fields

**MUST** define:

- **`file_path`**: `str` — Absolute path to MP3 file (required)
- **`gain`**: `float?` — Gain adjustment in dB (optional, default: 0.0)
- **`start_offset_ms`**: `int?` — Start offset in milliseconds (optional, default: 0)

### AE1.2 — Immutability

**MUST** be immutable once queued.

- AudioEvent is created during THINK phase
- AudioEvent is passed to DO phase and queued
- No modifications allowed after queuing

### AE1.3 — File Existence

**MUST** reference an existing file.

- File must exist at THINK time (validated during THINK)
- File must be readable and valid MP3 format
- File path must be absolute (not relative)

---

## AE2 — Lifecycle Announcements

Startup and shutdown announcements **MUST** be standard AudioEvent instances with no special handling.

### AE2.1 — Standard AudioEvent

**Startup and shutdown announcements MUST follow all existing AudioEvent validation rules.**

- Startup and shutdown announcements **MUST** be represented as standard AudioEvent instances
- Announcements **MUST** contain valid `file_path`, `gain`, and `start_offset_ms` fields
- Announcements **MUST** reference existing, playable MP3 files
- Announcements **MUST** be validated during THINK phase (not during DO)
- All validation rules apply unchanged to lifecycle announcements

### AE2.2 — No Special Handling

**Lifecycle announcements REQUIRE no special decode, mix, or output handling.**

- Announcements **MUST** be decoded using standard decoder (per FFmpegDecoder Contract)
- Announcements **MUST** be mixed using standard mixer (per Mixer Contract)
- Announcements **MUST** be output using standard output sink (per OutputSink Contract)
- No special processing or handling **MAY** be applied to lifecycle announcements
- Announcements are treated like any other segment

### AE2.3 — Lifecycle Control

**Lifecycle announcements are controlled by lifecycle state, not AudioEvent structure.**

- Startup and shutdown announcements are standard AudioEvents with no special structure
- Selection and timing are controlled by Station lifecycle state (per StationLifecycle Contract)
- PlayoutEngine distinguishes terminal segments via Station lifecycle state (DRAINING), not via AudioEvent structure
- AudioEvent Contract does not define lifecycle semantics (see DJIntent Contract for terminal intent marking)
- No special casing exists beyond lifecycle control

---

## Implementation Notes

- AudioEvent is a dataclass or similar immutable structure
- File validation occurs during THINK phase (not during DO)
- Gain is applied by Mixer during playback
- Start offset allows skipping intro portions of files
- AudioEvent is the unit passed from THINK → DO → PlayoutEngine
- Offline announcements are standard AudioEvents with no special handling required




