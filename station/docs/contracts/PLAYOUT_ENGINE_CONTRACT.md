# PlayoutEngine Contract

## Purpose

Defines the real-time audio engine that executes the DO phase. PlayoutEngine is responsible for decoding and playing audio segments.

---

## PE1 — Segment Lifecycle

### PE1.1 — Single Segment Playback

**MUST** decode and play exactly one segment at a time.

- Only one segment is active at any time
- Next segment starts only after current segment finishes
- No concurrent decoding or playback

### PE1.2 — Segment Start Event

**MUST** emit `on_segment_started` before first frame.

- Event is emitted synchronously before audio begins
- Event triggers THINK phase for next segment
- Event includes the AudioEvent being played

### PE1.3 — Segment Finish Event

**MUST** emit `on_segment_finished` after last frame.

- Event is emitted synchronously after audio ends
- Event triggers DO phase (queue execution)
- Event includes the AudioEvent that finished

---

## PE2 — Decision Prohibitions

### PE2.1 — Prohibited Operations

**PlayoutEngine** **MUST NOT**:

- Pick songs (song selection is DJEngine's responsibility)
- Insert IDs (ID insertion is DO phase's responsibility)
- Modify scheduling (scheduling is queue's responsibility)
- Generate any audio content (content comes from files only)

---

## PE3 — Two-Clock Architecture

### PE3.1 — Station Playback Clock (Clock A)

**Station MUST maintain its own wall-clock-based content playback clock.**

This clock is based on `time.monotonic()` and measures **content time**, NOT PCM output cadence.

**Station Playback Clock is responsible for:**
- Segment progression
- DJ THINK/DO logic timing
- Breaks, intros, outros timing
- Knowing how long a song has "played"
- Maintaining real-time program flow
- **Decode pacing metronome** (Clock A) to ensure songs play at real duration

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

**Station MUST NOT:**
- Use decoder speed to determine content duration
- Use number of frames decoded to advance segments
- Use number of frames sent to determine segment timing
- Use PCM buffer depth to influence segment timing
- Use Tower consumption rate to determine segment timing

**Segment duration rules:**
- Segments MUST be tied ONLY to real-time wall clock
- Segment ends when: `elapsed_time >= expected_duration_seconds`
- NOT based on: frames decoded, frames sent, decoder speed, PCM buffer depth, Tower consumption rate

### PE3.2 — Tower PCM Clock (Clock B)

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
- Use PCM write success/failure to influence segment timing or decode pacing

**Tower PCM Clock is responsible for:**
- Actual PCM pacing (strict 21.333ms)
- EncoderManager timing
- Consistent audio output timing
- **Sole authority for broadcast timing**

**Clock A (Station decode metronome) and Clock B (Tower AudioPump) are independent:**
- Clock A paces decode consumption for local playback correctness
- Clock B paces broadcast output
- Station-to-Tower interface remains asynchronous, non-blocking, and timing-agnostic

### PE3.3 — Decoder Output Rules

**Station MAY use Clock A (decode pacing metronome) to pace frame consumption.**

**Decode pacing rules (Clock A):**
- Station may pace consumption of decoded PCM frames using Clock A
- After decoding a PCM frame, Station should:
  - `next_frame_time += FRAME_DURATION`  # ~21.333 ms
  - `sleep(max(0, next_frame_time - now))`  # allow drift correction
- Clock A must be monotonic and maintain wall-clock fidelity
- Clock A must never attempt to observe Tower state
- Clock A must never alter pacing based on socket success/failure

**Socket write rules (MUST remain non-blocking):**
- Even if Clock A decode metronome is used, `write()` must remain non-blocking and fire immediately
- Station MUST NOT apply pacing to the socket write
- Socket writes must fire as soon as frames are available (after decode pacing, if used)

**FORBIDDEN pacing approaches:**
- Station MUST NOT apply adaptive pacing, buffer-based pacing, or rate correction
- No proportional control, no PID loops, no drift feedback from Tower
- No Tower-synchronized pacing (see PE3.2)

**Segment timing invariant:**
- Segment timing = wall clock only
- Station may rely on Clock A + file duration metadata to ensure its internal timeline advances in real time
- DJ THINK/DO cycle must continue to use wall-clock timing, not Tower timing
- Playback duration must reflect actual MP3 duration, independent of Tower ingestion

### PE3.4 — No Prefetching

**MUST NOT** prefetch or concurrently decode beyond the current segment.

- Only current segment is decoded
- Next segment decoding begins only after current finishes
- No background decoding or buffering beyond current segment

### PE3.5 — Error Propagation

**MUST** propagate decoder errors upward as segment termination only.

- Decoder errors cause segment to end (not station crash)
- Errors are logged but do not stop playout
- Next segment begins normally after error

---

## Implementation Notes

- PlayoutEngine reads from playout queue (DO phase enqueues)
- Decoding uses FFmpegDecoder (per FFmpegDecoder Contract)
- Output uses OutputSink (per OutputSink Contract)
- Mixing uses Mixer (per Mixer Contract)
- All operations must be real-time and non-blocking
- **Segment timing:** Uses wall clock (`time.monotonic()`) to measure elapsed time
- **Decode pacing:** Station may use Clock A (decode metronome) to pace frame consumption at ~21.333ms per frame
- **PCM output:** Socket writes remain non-blocking and fire immediately (no pacing on writes)
- **Two clocks:** Clock A (Station decode metronome) for local playback correctness; Clock B (Tower AudioPump) for broadcast timing




