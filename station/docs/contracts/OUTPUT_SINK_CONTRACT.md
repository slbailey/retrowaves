# OutputSink Contract

## Purpose

Defines how mixed PCM leaves the system. OutputSink is responsible for delivering PCM frames to external systems (Tower, file, Icecast, etc.).

---

## OS1 — Requirements

### OS1.1 — Continuous Input

**MUST** accept PCM frames as fast as PlayoutEngine produces them (after decode pacing, if Clock A is used).

- ARCHITECTURAL INVARIANT: Tower owns ALL broadcast timing (Clock B). Station may use Clock A for decode pacing only.
- Sink accepts frames immediately as provided (no rate matching required).
- Sink must not reject or drop frames under normal conditions (unless socket buffer full).
- **MUST** only output complete 4096-byte atomic frames (per Tower's PCM Ingestion Contract)
- **MUST** handle partial frames by padding to 4096 bytes with zeros or dropping them
- **MUST** validate frame size (4096 bytes) before transmission
- **MUST** use non-blocking socket writes (or short timeout with drop-oldest semantics)
- **MUST** fire socket writes immediately (no pacing on writes, even if decode pacing is used)

**Note:** This contract governs PCM output timing only. Segment timing is governed by Station's playback clock (Clock A - wall clock) and is independent of PCM output rate. Station may use Clock A for decode pacing, but socket writes must remain non-blocking and fire immediately.

### OS1.2 — Non-Blocking Output

**MUST** stream to Tower Unix socket without blocking playout.

- ARCHITECTURAL INVARIANT: Station must NEVER block Tower.
- Socket writes must be non-blocking (or short timeout with drop-oldest semantics).
- If socket buffer is full, frames are dropped silently (drop-oldest semantics).
- Sink must not slow down PlayoutEngine or decoder.
- Under no circumstances may Station stall waiting for Tower.

**Unix Socket Output Rules:**
- Station MUST set socket to non-blocking mode
- Station MUST drop frames on BlockingIOError
- Station MUST NEVER stall decoder for Tower
- Station MUST NEVER wait for Tower
- Unix socket is a pure byte pipe, NOT a timing interface

### OS1.3 — Back-Pressure

**MUST** back-pressure by dropping frames, not slowing decode.

- If output cannot keep up, drop frames (don't block)
- PlayoutEngine continues at real-time rate
- Dropped frames are logged but do not stop playout

### OS1.4 — Frame Atomicity for Tower Integration

OutputSink implementations that transmit PCM into Tower's PCM Ingestion pipeline (e.g., `TowerPCMSink`) **MUST**:

- Only transmit **complete 4096-byte PCM frames** as defined in `NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md`.
- **MUST NOT** transmit partial frames to Tower.
- **MUST** handle any partial frames produced by upstream components (e.g., final short frame at EOF) by either:
  - Padding with zeros up to 4096 bytes, or
  - Dropping the partial frame entirely.

The choice of padding vs. dropping is an implementation decision, but in all cases Tower **MUST** only see atomic 4096-byte frames at its ingest boundary.

---

## OS2 — Prohibitions

### OS2.1 — Content Modification

**MUST NOT** modify audio content.

- Sink receives PCM frames and outputs them as-is
- No gain adjustment, filtering, or effects
- Content modification is Mixer's responsibility

### OS2.2 — Timing Interpretation

**MUST NOT** reinterpret frame timing or apply Tower-synchronized pacing.

- ARCHITECTURAL INVARIANT: Tower owns ALL broadcast timing (Clock B). Station may use Clock A for decode pacing only.
- Sink outputs frames immediately as received (no pacing on writes, no timing adjustment).
- No frame rate conversion or timing adjustment.
- Tower owns all PCM broadcast timing (AudioPump @ 21.333ms - Clock B).

**Two-Clock Model:**
- Clock A (Station decode metronome): May pace decode consumption for local playback correctness
- Clock B (Tower AudioPump): Sole authority for broadcast timing
- Sink writes fire immediately (non-blocking, no pacing on writes)
- Sink does NOT influence Station's playback clock (Clock A) for segment timing
- Sink does NOT attempt Tower-synchronized pacing
- Segment timing is independent of PCM output rate

**FORBIDDEN:**
- Sink MUST NOT attempt to match Tower's AudioPump timing
- Sink MUST NOT adjust timing based on Tower ingestion behavior
- Sink MUST NOT slow down or speed up based on socket backpressure
- Sink MUST NOT attempt cadence alignment or drift correction relative to Tower

---

## Implementation Notes

- OutputSink implementations: TowerPCMSink, FileSink, IcecastSink, etc.
- Sink must handle connection failures gracefully
- Sink must reconnect automatically if connection is lost
- Sink must not block PlayoutEngine thread
- **Frame format**: 1024 samples, 4096 bytes, 21.333ms cadence (matches Tower's PCM format)
- **Frame format reference**: Tower's `NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md`
- **Partial frame handling**: Must pad partial frames to 4096 bytes with zeros, or drop them
- **Atomic delivery**: Only complete 4096-byte frames may be transmitted (per Tower's PCM Ingestion Contract)
- When used as a bridge into Tower (e.g., `TowerPCMSink`), OutputSink **MUST** validate frame size (4096 bytes) before transmission and discard any incorrect sizes.
- The PCM frame format **MUST** match Tower's canonical PCM format as defined in `NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md`.

