# Fallback Provider Contract

## FP1 — Purpose

The Fallback Provider is the exclusive source of non-program audio used when upstream PCM is unavailable beyond the grace period.

It abstracts all fallback audio generation or retrieval mechanisms so that EncoderManager can request "a fallback PCM frame" without knowing how it is produced.

---

## FP2 — Responsibilities

The Fallback Provider **MUST**:

### FP2.1
Produce exactly one **4096-byte PCM frame** on every call to `next_frame()`.

### FP2.2 — Immediate Return Requirement (Zero Latency Concept)
Guarantee that `next_frame()` returns **immediately without blocking**.

"Zero latency" is a conceptual requirement meaning the operation must be:
- **Non-blocking** — never wait for I/O, locks, or external resources
- **Very fast** — typically completes in microseconds to low milliseconds
- **Deterministic** — predictable execution time, not dependent on external factors
- **Real-time capable** — supports continuous audio playout at 21.333ms tick intervals (PCM cadence)

**MUST NOT**:
- Block or wait for any I/O operations
- Perform slow computations (file decoding, network requests, etc.)
- Depend on external resources that may cause delays

**MUST**:
- Return a frame quickly enough to support real-time playout
- Be precomputed or generated in-memory when possible
- Support continuous audio output without gaps

This ensures that EncoderManager can always obtain a fallback frame without any blocking delay, supporting continuous audio output.

### FP2.3
Frame format **MUST** match Tower's canonical PCM format (per `NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md`):

- Sample rate: 48,000 Hz
- Channels: 2 (stereo)
- Frame size: 1024 samples per frame (4096 bytes)

### FP2.4
Guarantee that it always returns a valid frame — **no exceptions**.

### FP2.5 — Phase Continuity
The fallback tone generator, when used, **MUST** maintain phase continuity across frame boundaries to prevent discontinuities in PCM output.

This ensures purity and avoids audible or visual artifacts. The phase accumulator **MUST** be updated once per frame (by `step * 1024`) and wrapped using modulo arithmetic, rather than updating and wrapping per sample within the frame loop.

---

## FP3 — Priority of Fallback Sources

The Fallback Provider **MUST** support and apply the following priority order internally:

### FP3.1 — File-Based Fallback (if configured)

A looping audio file (MP3, WAV, or PCM).

- **MUST** decode or read frames matching system PCM format
- **MUST** seamlessly loop when reaching EOF
- **MUST NOT** block the tick loop during decode

### FP3.2 — Tone-Based Fallback (440Hz) — Preferred Fallback

**440Hz tone is the preferred fallback source** when file-based fallback is unavailable.

- **MUST** always be available as a guaranteed fallback
- **MUST** generate 440Hz sine wave tone
- **MUST** maintain phase continuity across frames
- **MUST** match the PCM format exactly
- **MUST** be precomputed or generated with zero latency
- **MUST** be used whenever file fallback is unavailable or fails

The tone generator **MUST** be designed to return frames immediately without any blocking or slow computation.

### FP3.3 — Silence — Last Resort Fallback

Silence **MUST** be used **only if tone generation is not possible for any reason**.

- Used only if both file and tone sources fail
- **MUST** be a precomputed zero-filled frame (4096 bytes, per `NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md`)
- **MUST** be available instantly with zero latency
- **MUST** serve as the final fallback to ensure continuous PCM output

The priority order is: **File → 440Hz Tone → Silence**. Tone is strongly preferred over silence whenever possible.

This ensures graceful degradation without spreading priority logic across multiple components.

---

## FP4 — Interface

The Fallback Provider **MUST** expose:

```python
next_frame() -> bytes
```

### FP4.1
Returns a PCM frame of size **4096 bytes** (canonical PCM frame size as defined in `NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md`).

### FP4.2
**MUST** be safe to call once per tick (21.333ms cadence - PCM cadence).

### FP4.3
**MUST NOT** raise exceptions during normal operation.

### FP4.4
**MUST NOT** return `None` or partial frames.

---

## FP5 — Error Handling

The Fallback Provider **MUST**:

### FP5.1
Treat file decode errors as "file unavailable" and fall back automatically to **440Hz TONE**.

### FP5.2
Treat tone generator failure as "tone unavailable" and fall back to **SILENCE** only as a last resort.

The Fallback Provider **MUST** make every effort to provide 440Hz tone before falling back to silence. Silence should only be used if tone generation is genuinely impossible (e.g., system resource exhaustion, critical error).

### FP5.3
**NEVER** propagate errors to EncoderManager.

### FP5.4
Log internal errors for observability but always return a valid frame.

---

## FP6 — Phase and Loop Continuity

To ensure broadcast-grade audio experience:

### FP6.1
Tone generator **MUST** maintain accurate sine-wave phase between ticks.

### FP6.2
File fallback **MUST** maintain continuous looping without audible seams.

### FP6.3
Continuity **MUST** persist across:

- EncoderManager resets
- FFmpeg restarts
- Client connection changes

This ensures consistent, clean fallback audio.

---

## FP7 — Construction and Configuration

### FP7.1
The Fallback Provider **MUST** be constructed before EncoderManager.

### FP7.2
It **MUST** not require runtime arguments beyond configuration (environment variables or file paths).

### FP7.3
If a file fallback path is unset or invalid, **440Hz TONE** is automatically the primary source.

The tone generator **MUST** be ready to provide frames immediately with zero latency, ensuring continuous PCM output even when file fallback is unavailable.

### FP7.4
All providers **MUST** share the same PCM format invariants.

---

## FP8 — Relationship to EncoderManager

EncoderManager **MUST**:

### FP8.1
Treat Fallback Provider as a **black box**.

### FP8.2
**NEVER** implement tone/file/silence logic itself.

### FP8.3
Call `fallback_provider.next_frame()` exactly when:

- No upstream PCM
- Grace period expired

This ensures clean, single-responsibility boundaries.
