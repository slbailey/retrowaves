# RotationManager Contract

## Purpose

Defines **WHAT** song selection must achieve. RotationManager is responsible for selecting the next track according to rotation rules.

---

## ROT1 — Rotation Guarantees

### ROT1.1 — Cooldown Enforcement

Next track **MUST NOT** be in the cooldown window.

- Cooldown window is configurable (e.g., last N tracks, time-based)
- Recently played tracks must be excluded from selection
- Cooldown state must be maintained and persisted

### ROT1.2 — Weighted Rules

Weighted rules **MUST** favor:

- **Long-unplayed tracks**: Tracks that haven't been played recently get higher weight
- **Never-played tracks**: Tracks that have never been played get highest weight
- **Seasonal/holiday pools**: Automatic date-ramping for seasonal content
  - Holiday tracks get higher weight near relevant dates
  - Seasonal tracks ramp up weight as dates approach
  - Weight decays after holiday/season passes

---

## ROT2 — Output

### ROT2.1 — Single Track Return

**MUST** return exactly one valid file path.

- Return value is a single MP3 file path (absolute)
- Path must be validated (file exists, is readable)
- Path must be playable (valid MP3 format)

### ROT2.2 — Atomic History Update

**MUST** update play history atomically.

- Play history must be updated when track is selected
- Update must be atomic (no partial updates)
- History must be persisted to DJStateStore
- Cooldown state must be updated atomically with history

---

## Implementation Notes

- RotationManager is called by DJEngine during THINK phase
- Selection algorithm must be deterministic (same state = same result)
- Weight calculation must be efficient (no O(n²) operations)
- History updates must be thread-safe if accessed from multiple threads
- Seasonal/holiday detection must use system date/time






