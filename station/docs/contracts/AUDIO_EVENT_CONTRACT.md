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

## Implementation Notes

- AudioEvent is a dataclass or similar immutable structure
- File validation occurs during THINK phase (not during DO)
- Gain is applied by Mixer during playback
- Start offset allows skipping intro portions of files
- AudioEvent is the unit passed from THINK → DO → PlayoutEngine




