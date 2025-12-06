# Contract: PCM_GRACE_PERIOD

This contract defines the behavior of the PCM grace period, which prevents fallback tone interruptions during brief Station gaps.

## 1. Core Invariants

- [G1] Grace period is **configurable** via `TOWER_PCM_GRACE_SEC` (default: 5 seconds).
- [G2] Grace period prevents **audible tone interruptions** during track transitions.
- [G3] During grace period, Tower uses **silence frames** (not fallback tone/file).

## 2. Grace Period Semantics

- [G4] Grace period starts when:
  - EncoderManager detects PCM buffer is empty (no frames available from Station)
  - EncoderManager's `next_frame()` determines no valid PCM is available
- [G5] During grace period:
  - EncoderManager routes **silence frames** (PCM zeros) via `write_fallback()`
  - Silence frames are **standardized** (exactly 4608 bytes, s16le, 48kHz, stereo)
  - Silence frames are **cached** (pre-built, not generated on-demand)
  - FallbackGenerator is **not called** during grace period (silence only)
  - Grace timer continues counting inside EncoderManager
- [G6] After grace period expires:
  - EncoderManager (via `next_frame()`) routes to fallback tone/file via `write_fallback()`
  - EncoderManager calls `FallbackGenerator.get_frame()` internally
  - Fallback tone/file begins playing
  - Grace timer is **not reset** (remains expired until new PCM arrives)

## 3. Grace Period Reset

- [G7] Grace period **resets** when:
  - EncoderManager's `next_frame()` detects new PCM frame available (buffer becomes non-empty)
  - EncoderManager determines valid PCM is present via PCM buffer check
- [G8] Reset behavior:
  - EncoderManager resets grace timer to zero internally
  - EncoderManager immediately routes to live PCM via `write_pcm()` (no silence delay)
  - EncoderManager stops calling FallbackGenerator
  - AudioPump continues providing 24ms ticks (timing only, no routing decisions)
- [G9] Reset is **immediate** (no delay or hysteresis).

## 4. Boundary Conditions

- [G10] At exactly `TOWER_PCM_GRACE_SEC`:
  - If grace period just expired: switch to fallback
  - If new PCM arrives at exactly grace expiry: reset grace, use live PCM
- [G11] Grace period is measured in **real time** (wall clock, not frame count).
- [G12] EncoderManager uses `time.monotonic()` for grace period timing (prevents clock adjustment issues). The timer is maintained inside EncoderManager, not AudioPump.

## 5. Integration with EncoderManager and AudioPump

- [G13] EncoderManager implements grace period logic within `next_frame()`:
  1. EncoderManager checks PCM buffer availability internally
  2. If valid PCM frame available: route to `write_pcm()`, reset grace timer
  3. If PCM not available: check internal grace timer
     - If within grace period: route silence frame via `write_fallback()`
     - If grace expired: route fallback tone/file via `write_fallback()` (calls `FallbackGenerator.get_frame()` internally)
  4. AudioPump only provides 24ms timing ticks by calling `next_frame()` each tick
  5. AudioPump does NOT make routing decisions or own grace period timers
- [G14] Grace timer is **maintained by EncoderManager** (not by AudioPump or AudioInputRouter). AudioPump provides timing continuity only.

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

