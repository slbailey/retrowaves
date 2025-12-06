# Contract: FALLBACK_GENERATOR

This contract defines the behavior of FallbackGenerator, which provides PCM frames when live Station input is unavailable.

## 1. Core Invariants

- [F1] FallbackGenerator **always** returns valid PCM frames (never None, never raises).
- [F2] FallbackGenerator **guarantees** correctly-formatted PCM frames:
  - Format: s16le (signed 16-bit little-endian)
  - Sample rate: 48000 Hz
  - Channels: 2 (stereo)
  - Frame size: 1152 samples × 2 channels × 2 bytes = 4608 bytes
- [F3] Tower **always has a fallback source** (graceful degradation: file → tone → silence).

## 2. Source Selection Priority

- [F4] Source selection follows **strict priority order** at Tower startup:
  1. **File Source** (if `TOWER_SILENCE_MP3_PATH` is set and points to valid WAV file)
  2. **Tone Generator** (default, or if file unavailable/invalid)
  3. **Silence Source** (last resort, only if tone generation fails)
- [F5] Priority order is **deterministic** and **testable** (no random selection).

## 3. File Source Behavior

- [F6] File source is selected if:
  - `TOWER_SILENCE_MP3_PATH` environment variable is set
  - File exists and is readable
  - File has `.wav` extension (FileSource only handles WAV files)
- [F7] If file source initialization fails:
  - Logs warning
  - Falls through to tone generator (does not crash)
- [F8] If file is MP3 (not WAV):
  - Falls through to tone generator (FileSource cannot handle MP3)
  - Logs informational message
- [F9] File source must provide continuous PCM frames (looped if file is shorter than needed).

## 4. Tone Generator Behavior

- [F10] Tone generator produces **440 Hz sine wave** by default.
- [F11] Tone generator uses **phase accumulator** to ensure continuous waveform without pops.
- [F12] Tone generator is selected if:
  - No file is configured, OR
  - File source initialization fails, OR
  - File is not WAV format
- [F13] If tone generation fails:
  - Logs warning
  - Falls through to silence source (does not crash)

## 5. Silence Source Behavior

- [F14] Silence source produces **continuous PCM zeros** (all bytes = 0x00).
- [F15] Silence source is **always available** (never fails to initialize).
- [F16] Silence source is selected only if:
  - Tone generator initialization fails, OR
  - Tone generation encounters runtime errors
- [F17] Silence source ensures Tower **never fails** to provide fallback audio.

## 6. Interface Contract

- [F18] Constructor takes no parameters (reads environment variables internally).
- [F19] Provides:
  - `get_frame() -> bytes` → always returns valid PCM frame (never None)
- [F20] `get_frame()` is **idempotent** (can be called repeatedly, returns consistent frames).

## 7. Format Guarantees

- [F21] All fallback sources return frames of **exactly 4608 bytes**.
- [F22] Frame format matches canonical Tower format:
  - s16le encoding
  - 48000 Hz sample rate
  - 2 channels (stereo)
  - 1152 samples per frame
- [F23] Frame boundaries are **preserved** (no partial frames).

## 8. Future Extensions

- [F24] **MP3 fallback file support** (optional future enhancement):
  - Current implementation only supports WAV files (FileSource limitation)
  - Future enhancement: Support MP3 files by pre-decoding to PCM at startup
  - Pre-decoded PCM would be cached in memory and looped during fallback
  - This would allow MP3 files to be used as fallback source without runtime decoding overhead
  - Implementation would follow same priority: file (WAV or MP3) → tone → silence

## Required Tests

- `tests/contracts/test_tower_fallback_generator.py` MUST cover:
  - [F1]–[F3]: Core invariants (always valid, format guarantees, always available)
  - [F4]–[F5]: Source selection priority order
  - [F6]–[F9]: File source behavior and failure modes
  - [F10]–[F13]: Tone generator behavior and failure modes
  - [F14]–[F17]: Silence source behavior (always available)
  - [F18]–[F20]: Interface contract
  - [F21]–[F23]: Format guarantees

