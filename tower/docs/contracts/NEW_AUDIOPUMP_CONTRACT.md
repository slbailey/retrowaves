# AudioPump Contract

## A. Purpose

The purpose of **AudioPump** is to be the single global metronome of the Tower system and to drive the audio processing pipeline at a fixed tick interval.

**AudioPump:**

- Owns the system clock tick
- Calls into `EncoderManager` once per tick
- Pushes the chosen PCM frame into the downstream buffer that ultimately feeds `FFmpegSupervisor`

AudioPump does not decide whether to send program, silence, or tone; it simply executes the tick loop and delegates that decision to `EncoderManager`.

---

## B. Relationship to Core Timing

### A1
AudioPump **MUST** use the tick interval defined in `NEW_CORE_TIMING_AND_FORMATS_CONTRACT` (**24 ms**).

### A2
AudioPump **MUST** assume the PCM frame format defined there (48kHz, stereo, 1152 samples, 4608 bytes).

### A3
AudioPump **MUST NOT** invent or use a different tick interval for any part of the system.

---

## C. Tick Loop Responsibilities

### A4
AudioPump **MUST** run a periodic loop at the global tick interval (**24ms**).

### A5
On each tick, AudioPump **MUST**:

1. **A5.1** — Attempt to obtain at most one PCM frame from the upstream PCM input buffer (may be absent for this tick)
2. **A5.2** — Pass the obtained frame (or `None` if absent) into `EncoderManager`
3. **A5.3** — Receive from `EncoderManager` exactly one PCM frame (program, silence, or tone)
4. **A5.4** — Push that PCM frame into the downstream PCM → FFmpeg pipeline (e.g., ring buffer / queue) consumed by `FFmpegSupervisor`

### A6
AudioPump **MUST** ensure that the call into `EncoderManager` occurs exactly once per tick and that exactly one PCM frame is emitted per tick.

---

## D. No Routing Logic

### A7
AudioPump **MUST NOT**:

- Decide whether to send program, silence, or tone
- Implement grace period timing
- Generate silence or tone frames

### A8
AudioPump **MUST NOT**:

- Call `write_pcm()` / `write_fallback()` on `EncoderManager` or `Supervisor` directly
- Inspect audio content beyond what is necessary to pass PCM through

### A9
All decisions about source selection (program vs silence vs tone) are owned by `EncoderManager` and **MUST NOT** be duplicated inside AudioPump.

---

## E. Interaction with Other Components

### A10
AudioPump **MUST** be constructed with:

- A reference to the upstream PCM input buffer (from the MP3 decoder / upstream feeder)
- A reference to `EncoderManager`
- A reference (directly or indirectly) to the downstream PCM buffer feeding `FFmpegSupervisor`

### A11
AudioPump **MUST NOT** hold references to:

- FFmpeg process objects
- HTTP connection objects
- Any networking primitives

---

## F. Error Handling

### A12
If `EncoderManager` raises unexpected errors, AudioPump **MAY**:

- Log the error
- Replace the emitted frame with silence for that tick
- Continue ticking on subsequent intervals

### A13
AudioPump **MUST** never stop ticking solely because upstream PCM is absent; it **MUST** continue calling `EncoderManager` each tick.
