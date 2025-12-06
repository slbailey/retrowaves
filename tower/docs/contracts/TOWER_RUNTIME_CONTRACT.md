# Contract: TOWER_RUNTIME

This contract defines the externally observable behavior of `retrowaves-tower.service`.

## 1. Always-on Transmitter

- [T1] Tower exposes `GET /stream` and **never refuses** a connection while the service is up.
- [T2] `/stream` **always** returns valid MP3 bytes (either live, fallback, or silence) from the moment headers are sent.
- [T3] Tower continues streaming audio even if Station is down, restarting, or never started.

## 2. Live vs Fallback Behavior

- [T4] When Station is feeding valid PCM, Tower streams live audio.
- [T5] When Station stops feeding PCM, Tower:
  - [T5.1] Detects absence of frames within `TOWER_FRAME_TIMEOUT_MS`.
  - [T5.2] Uses silence frames during the grace period (`TOWER_PCM_GRACE_SEC`).
  - [T5.3] After grace expiry, switches to fallback source (tone/file).
- [T6] Switches between live and fallback **do not disconnect clients**.

## 3. Station Input Model

- [T7] Tower reads PCM frames from a bounded buffer fed by the Unix domain socket.
- [T8] Buffer overflow results in dropped frames, not blocking writes.
- [T9] Tower is the **sole metronome**: it pulls one PCM frame every 21.333 ms.

## 4. Client Handling

- [T10] **Slow clients never block broadcast**: The main broadcast loop MUST NOT block on slow clients. Sending output to all connected clients MUST complete promptly (bounded time, independent of any single slow client). Slow or stalled clients MUST be dropped or handled in a way that keeps the broadcast loop non-blocking.
- [T11] Clients that cannot accept data for `TOWER_CLIENT_TIMEOUT_MS` are dropped.
- [T12] All connected clients receive the same audio bytes (single broadcast signal).

## 5. Lifecycle

- [T13] On shutdown, Tower stops accepting new connections and cleanly closes existing ones within `TOWER_SHUTDOWN_TIMEOUT` seconds.
- [T14] Tower can be started when Station is offline; it will stream fallback until live audio is available.

## Required Tests

- `tests/contracts/test_tower_runtime.py` MUST cover:
  - [T1]–[T3]: service exposes `/stream` and always produces bytes.
  - [T4]–[T6]: live → fallback → live transitions without disconnects.
  - [T7]–[T9]: metronome behavior and bounded PCM buffer semantics.
  - [T10]–[T12]: slow client handling, single-signal behavior.
  - [T13]–[T14]: clean shutdown and startup semantics.
