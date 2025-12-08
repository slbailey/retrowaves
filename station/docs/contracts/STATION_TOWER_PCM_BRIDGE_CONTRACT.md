# Station–Tower PCM Bridge Contract

## A. Purpose

Defines the formal integration boundary between:

- **Station Playout System** (RADIOWAVES)
- **Tower PCM Ingestion Pipeline**

Goals:

- Ensure deterministic, lossless, and real-time interoperability.
- Preserve subsystem autonomy.
- Specify what MUST be true at the Station→Tower boundary (not how either side internally produces/consumes PCM).

---

## B. Scope

- **Applies to:** PCM frames transmitted from Station's `OutputSink` to Tower's PCM Ingestion.
- **Station-internal:** All logic upstream of OutputSink.
- **Tower-internal:** All logic downstream of PCM Ingestion.
- This contract is the single source of truth for:
  - Frame structure and atomicity
  - Timing and cadence
  - Validation requirements
  - Permitted and forbidden behaviors
  - Error-handling at the boundary

---

## C. Two-Clock Architecture

### C0. Architectural Clocks

**Clock A — Station Playback Clock (OWNED BY STATION)**

Responsible for:
- Segment progression
- DJ THINK/DO logic
- Breaks, intros, outros
- Knowing how long a song has "played"
- Maintaining real-time program flow
- **Decode pacing metronome** to ensure songs play at real duration

This is a wall-clock timer, based on `time.monotonic()`, that measures **content time**, NOT PCM output cadence.

**Station MAY use Clock A for decode pacing:**
- Station may use an internal timer to pace consumption of decoded PCM frames
- This pacing must target ≈21.333 ms per 1024-sample frame for real-time MP3 playback
- This metronome is for local playback correctness only — ensuring songs take their real duration (e.g., a 200-second MP3 takes 200 seconds to decode)
- Clock A must be monotonic and maintain wall-clock fidelity
- Clock A must never attempt to observe Tower state
- Clock A must never alter pacing based on socket success/failure

**Playback duration MUST be measured as:**
```python
elapsed = time.monotonic() - segment_start
```

**Station MUST NOT use decoder speed to determine content duration.**

**Clock B — Tower PCM Clock (OWNED BY TOWER)**

Responsible for:
- Actual PCM pacing (strict 21.333ms)
- EncoderManager timing
- Consistent audio output timing
- **Sole authority for broadcast timing**

**Station MUST NOT attempt to match or influence this clock.**

**Station MUST NOT (Tower-synchronized pacing is FORBIDDEN):**
- Attempt to match Tower's AudioPump timing
- Adjust timing based on Tower ingestion behavior
- Slow down or speed up based on socket backpressure
- Attempt cadence alignment or drift correction relative to Tower

Tower is the ONLY owner of PCM timing.

**Clock A (Station decode metronome) and Clock B (Tower AudioPump) are independent:**
- Clock A paces decode consumption for local playback correctness
- Clock B paces broadcast output
- Station-to-Tower interface remains asynchronous, non-blocking, and timing-agnostic

---

## C. Requirements

### C1. Canonical PCM Format

- All frames crossing the boundary **MUST** comply with [NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md].
- **Required PCM properties:**
  - Sample rate: **48,000 Hz**
  - Channels: **2 (stereo)**
  - Bit depth: **16-bit signed integer**
  - Frame size: **1024 samples** (4096 bytes)
  - Frame duration: ≈21.333 ms (derived; not mandated)
- **Prohibited:** Station **MUST NOT** invent or vary format (frame size, sample rate, channel count, bit depth, or byte order). Only Tower’s core timing defines these.

### C2. Frame Atomicity

- **Boundary atomicity:** Station **MUST ONLY** transmit complete, fully-formed 4096-byte PCM frames.
- **Partial frames** **MUST NOT** cross the boundary.
  - If Station internally produces a partial frame (e.g., at EOF), Station **MUST** either:
    - Pad to 4096 bytes with zeros _or_
    - Drop the partial frame.
  - Choice is Station’s implementation detail.
  - Tower **MUST NEVER** receive a non-atomic frame.
- All 4096 bytes of a frame **MUST** belong to a single PCM frame—**no coalescing, splitting, or re-chunking.**

### C3. Delivery Timing

**Station Responsibilities (Upstream):**
- Decode MP3/AAC → PCM frames, optionally paced by Clock A (decode metronome)
- Write PCM frames to Unix socket with **no timing constraints** (writes fire immediately, non-blocking)
- Maintain real-time content duration using **wall clock** (Clock A)
- Trigger DJ THINK/DO based on **wall clock**
- End segments when **real-time duration expires** (not based on frames decoded/sent)
- Never block on socket writes (drop-oldest semantics)

**Station MAY use Clock A for decode pacing:**
- Station may pace consumption of decoded PCM frames using Clock A
- After decoding a PCM frame, Station may: `next_frame_time += FRAME_DURATION` (~21.333 ms), then `sleep(max(0, next_frame_time - now))`
- Clock A must be monotonic and maintain wall-clock fidelity
- Clock A must never attempt to observe Tower state
- Clock A must never alter pacing based on socket success/failure

**Station MUST NOT (Tower-synchronized pacing is FORBIDDEN):**
- Attempt to match Tower's AudioPump timing
- Adjust timing based on Tower ingestion behavior
- Slow down or speed up based on socket backpressure
- Attempt cadence alignment or drift correction relative to Tower
- Apply adaptive pacing, buffer-based pacing, or rate correction
- Use proportional control, PID loops, or drift feedback from Tower
- Use decoder speed to advance segments
- Use PCM write success/failure to influence segment timing or decode pacing

**Socket write rules:**
- Even if Clock A decode metronome is used, socket writes must remain non-blocking and fire immediately
- Station MUST NOT apply pacing to the socket write

**Tower Responsibilities (Downstream):**
- Pull PCM frames at strict 21.333ms (Clock B - AudioPump)
- Drop, buffer, or insert silence as needed
- Encode MP3 frames as produced
- Maintain broadcast timing

**Tower MUST NOT use segment duration or content logic from Station.**

**Decoder Output Rules:**
- Station MAY use Clock A (decode metronome) to pace consumption of decoded PCM frames
- Decoder produces PCM frames at whatever speed the CPU allows
- Station may pace frame consumption using Clock A to ensure real-time playback
- Station MUST push frames into output sink immediately after decode pacing (if used)
- Station MUST NOT delay socket writes (writes fire immediately, non-blocking)
- Station MUST NOT create Tower-synchronized pacing

**Segment timing invariant:**
- Segment timing = wall clock only
- Station may rely on Clock A + file duration metadata to ensure its internal timeline advances in real time
- DJ THINK/DO cycle must continue to use wall-clock timing, not Tower timing
- Playback duration must reflect actual MP3 duration, independent of Tower ingestion

### C4. Validation

- **Before transmit:** Station **MUST** validate each frame:
  - `len(frame) == 4096`
  - PCM properties match Core Timing
  - **Invalid frames MUST be silently dropped.**
- **Independent validation:** Tower also validates:
  - Rejects non-4096-byte or malformed frames
  - There is no trust boundary—validation on both sides.

### C5. Error Handling at Boundary

- If Station cannot provide a valid PCM frame, it **MUST** supply:
  - A silence frame (4096 bytes) **or**
  - A fallback frame (as per [NEW_FALLBACK_PROVIDER_CONTRACT.md])
- If Tower receives an oversized, undersized, or corrupt frame:
  - **MUST** discard frame, without back-pressuring Station
  - **MUST NOT** block Station threads, request resends, or require synchronous negotiation
  - **Boundary is fire-and-forget**

### C6. Forbidden Behaviors

- **Station MUST NOT:**
  - Send frames smaller or larger than 4096 bytes
  - Send variable-size frames
  - Pace PCM writes or match Tower cadence
  - Use decoder speed to determine segment duration
  - Use PCM write success/failure to influence segment timing
  - Embed metadata in PCM frames
  - Send non-PCM format (e.g., MP3, AAC)
  - Buffer indefinitely or await Tower acknowledgment
- **Tower MUST NOT:**
  - Infer timing or decode Station’s internal logic
  - Modify frame boundaries or negotiate format at runtime
  - Use segment duration or content logic from Station

---

## D. Responsibilities

### D1. Station Guarantees

**PCM Output:**
- Delivers PCM frames matching Tower's format
- Delivers only atomic frames (4096 bytes)
- Handles all partial-frame normalization upstream
- Pushes frames as fast as decoder produces them (no timing constraints)
- Validates size/format for each frame prior to send
- Never blocks Tower (non-blocking socket writes with drop-oldest semantics)
- Tolerates being slower or faster than Tower's cadence (Tower handles fallback)

**Segment Timing:**
- Times segments by real-time wall clock (`time.monotonic()`)
- Ends segments when `elapsed_time >= expected_duration_seconds`
- Does NOT use decoder speed, frame count, or PCM write status to determine segment duration
- Triggers DJ THINK/DO based on wall clock, not PCM timing

### D2. Tower Guarantees

**PCM Timing:**
- Consumes exactly one frame per tick (21.333ms - Clock B)
- Validates every frame
- Rejects malformed frames without blocking upstream
- Resolves frame shape and cadence only from Core Timing definitions
- Maintains cadence regardless of Station irregularities

**Content Independence:**
- Never depends on Station timing for content decisions
- Never uses segment duration or content logic from Station
- Operates independently of Station's playback clock (Clock A)

---

## E. Boundary Invariants (MUST ALWAYS HOLD)

**Frame Format:**
- Every boundary-crossing frame is 4096 bytes.
- Tower **never** receives partial frames.
- Station **never** sends frames inconsistent with Core Timing.

**Timing Independence:**
- Tower **never** blocks Station.
- Station **always** supplies a valid frame (audio or silence/fallback).
- Tower's PCM clock (Clock B) is the only relevant clock for PCM boundary flow.
- Station's playback clock (Clock A) is independent and measures content time only.
- Station segment timing is based on wall clock, NOT decoder speed or PCM write status.
- No implementation details leak in either direction.

---

## F. Two-Clock Model — Contract Language

### F.1 — Playback Clock Invariant

**Station MUST maintain its own wall-clock-based content playback clock.**

This is the ONLY source of truth for:
- Segment start time
- Segment elapsed time
- Segment end time
- DJ THINK/DO cadence

**Decoder output timing MUST NOT be used for segment timing.**

### F.2 — PCM Clock Invariant

**Tower's AudioPump (21.333ms) is the ONLY authoritative PCM timing source for broadcast timing.**

**Station MUST NOT (Tower-synchronized pacing is FORBIDDEN):**
- Attempt to match Tower's AudioPump timing
- Adjust timing based on Tower ingestion behavior
- Slow down or speed up based on socket backpressure
- Attempt cadence alignment or drift correction relative to Tower
- Try to match PCM rate
- Predict PCM rate
- Influence PCM rate
- Derive timing from PCM writes

### F.3 — Correct Behavior Summary

**STATION:**
- Times SEGMENTS by real time (wall clock - Clock A)
- May use Clock A (decode metronome) to pace consumption of decoded PCM frames (~21.333ms per frame)
- Sends PCM frames immediately after decode pacing (socket writes are non-blocking, no pacing on writes)
- Does NOT time PCM socket writes (writes fire immediately)
- Does NOT depend on Tower timing for segment progression or decode pacing
- Does NOT attempt Tower-synchronized pacing

**TOWER:**
- Times PCM playback by AudioPump (21.333ms - Clock B)
- Never depends on Station timing for content decisions
- Owns ALL broadcast timing

---

## G. Out of Scope

This contract **DOES NOT** define or govern:

- How Station decodes audio
- How Tower routes, encodes, or otherwise processes audio downstream
- Mixing, crossfade, gain staging, ducking, intros/outros
- Internal queueing inside Station
- Tick scheduling or PCM ingestion logic inside Tower
- Subsystem-internal file handling or decoder behaviors

(Refer to the appropriate subsystem contract for those aspects.)

---
