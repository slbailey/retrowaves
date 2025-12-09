# Mixer Contract

## Purpose

Defines the gain/combination layer. Mixer applies gain adjustments and combines audio streams (if multiple sources are mixed).

---

## MX1 — Guarantees

### MX1.1 — Gain Application

**MUST** apply gain accurately per frame.

- Gain is applied as dB adjustment (converted to linear multiplier)
- Gain is applied to each sample in the frame
- Gain application must not introduce clipping (unless intentional)
- Gain from AudioEvent.gain is applied to each frame

### MX1.2 — Timing Preservation

**MUST** preserve timing (1:1 input/output frame count).

- One input frame produces exactly one output frame
- No frame dropping or duplication
- Frame boundaries are preserved

### MX1.3 — Latency

**MUST NOT** introduce latency or buffering beyond 1 frame.

- Mixer processes frames immediately (no buffering)
- Maximum latency is one frame (21.333ms)
- No accumulation or delay

---

## MX2 — Prohibitions

### MX2.1 — Prohibited Operations

**MUST NOT**:

- Alter playout order (order is determined by queue)
- Change file selection (selection is DJEngine's responsibility)
- Perform ducking or overlays unless explicitly configured
  - Mixer applies gain only
  - No automatic ducking, crossfading, or effects
  - Effects must be explicitly configured if needed

---

## Implementation Notes

- Mixer is stateless (no memory between frames)
- Gain is applied per-frame using AudioEvent.gain
- Mixer operates on PCM frames (4096 bytes, 1024 samples)
- Mixer output goes to OutputSink
- Mixer must be real-time and non-blocking






