# Contract: PCM_GRACE_PERIOD

This contract defines the behavior of the PCM grace period, which prevents fallback tone interruptions during brief Station gaps.

## 1. Core Invariants

- [G1] Grace period is **configurable** via `TOWER_PCM_GRACE_SEC` (default: 5 seconds).
- [G2] Grace period prevents **audible tone interruptions** during track transitions.
- [G3] During grace period, Tower uses **silence frames** (not fallback tone/file).

## 2. Grace Period Semantics

- [G4] Grace period starts when:
  - PCM buffer becomes empty (no frames available from Station)
  - `pop_frame(timeout)` returns `None` after timeout
- [G5] During grace period:
  - AudioPump uses **silence frames** (PCM zeros)
  - Silence frames are **standardized** (exactly 4608 bytes, s16le, 48kHz, stereo)
  - Silence frames are **cached** (pre-built, not generated on-demand)
  - FallbackGenerator is **not called**
  - Grace timer continues counting
- [G6] After grace period expires:
  - AudioPump calls `FallbackGenerator.get_frame()`
  - Fallback tone/file begins playing
  - Grace timer is **not reset** (remains expired until new PCM arrives)

## 3. Grace Period Reset

- [G7] Grace period **resets** when:
  - New PCM frame arrives from Station (buffer becomes non-empty)
  - `pop_frame()` returns a valid frame (not None)
- [G8] Reset behavior:
  - Grace timer resets to zero
  - AudioPump immediately switches to live PCM (no silence delay)
  - FallbackGenerator stops being called
- [G9] Reset is **immediate** (no delay or hysteresis).

## 4. Boundary Conditions

- [G10] At exactly `TOWER_PCM_GRACE_SEC`:
  - If grace period just expired: switch to fallback
  - If new PCM arrives at exactly grace expiry: reset grace, use live PCM
- [G11] Grace period is measured in **real time** (wall clock, not frame count).
- [G12] Grace period uses `time.monotonic()` for timing (prevents clock adjustment issues).

## 5. Integration with AudioPump

- [G13] AudioPump implements grace period logic:
  1. Try `pcm_buffer.pop_frame(timeout=0.005)` (5ms timeout)
  2. If frame available: use live frame, reset grace timer
  3. If frame not available: check grace timer
     - If within grace: use silence frame
     - If grace expired: use `fallback_generator.get_frame()`
- [G14] Grace timer is **maintained by AudioPump** (not by AudioInputRouter or EncoderManager).

## 6. Configuration

- [G15] Default grace period: **5 seconds** (`TOWER_PCM_GRACE_SEC=5`).
- [G16] Grace period can be configured via environment variable.
- [G17] Grace period must be **> 0** (zero or negative grace disables grace period, immediately uses fallback).

## 7. Silence Frame Requirements

- [G18] Silence frames used during grace period must be:
  - **Standardized**: Exactly 4608 bytes (1152 samples × 2 channels × 2 bytes)
  - **Format**: s16le, 48kHz, stereo (matches canonical Tower format)
  - **Cached**: Pre-built at startup, not generated on-demand
  - **Consistent**: Same frame bytes every time (all zeros: `b'\x00' * 4608`)
- [G19] Silence frame caching ensures:
  - No allocation overhead during grace period
  - Consistent frame boundaries
  - Broadcast-grade performance

## 8. Future Extensions

- [G20] **Smoothing hysteresis** (optional future enhancement):
  - Current implementation uses instant reset on new PCM arrival
  - Future enhancement: Add configurable hysteresis window (e.g., 100-500ms)
  - Hysteresis would prevent rapid toggling between live/fallback during marginal signal conditions
  - Would provide additional broadcast polish for edge cases (intermittent Station connectivity)
  - Implementation would delay grace reset until PCM frames are consistently available for hysteresis duration

## Required Tests

- `tests/contracts/test_tower_pcm_grace_period.py` MUST cover:
  - [G1]–[G3]: Core invariants (configurable, prevents interruptions, uses silence)
  - [G4]–[G6]: Grace period semantics (start, during, expiry)
  - [G7]–[G9]: Grace period reset behavior
  - [G10]–[G12]: Boundary conditions and timing
  - [G13]–[G14]: Integration with AudioPump
  - [G15]–[G17]: Configuration
  - [G18]–[G19]: Silence frame requirements (standardized, cached)

