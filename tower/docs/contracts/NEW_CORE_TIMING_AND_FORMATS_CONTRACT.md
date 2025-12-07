# Core Timing and Formats Contract

## Purpose

Define the invariant low-level technical parameters used across the entire Tower system. These values never change at runtime and must be identical across all components.

---

## C1 — Global Metronome Interval

### C1.1
The system's universal timing tick is **24ms**.

### C1.2
This interval corresponds to **1152 samples at 48kHz**.

### C1.3
All Tower subsystems **MUST** operate on this global tick:

- **AudioPump**
- **EncoderManager**
- **FFmpegSupervisor's** input pacing
- **TowerRuntime** (HTTP streaming tick)

No other subsystem may introduce its own timing loop.

---

## C2 — PCM Format Requirements

### C2.1
All PCM audio handled by Tower **MUST** be:

| Parameter | Value |
|-----------|-------|
| Sample rate | 48,000 Hz |
| Channels | 2 (stereo) |
| Bit depth | 16-bit (signed PCM) |
| Frame size per tick | 1152 samples per channel |

### C2.2
Each PCM frame **MUST** be exactly **4608 bytes**:

```
1152 samples × 2 channels × 2 bytes per sample = 4608 bytes
```

---

## C3 — Silence Frame Standard

### C3.1
The silence frame **MUST** be a zero-filled PCM frame of size **4608 bytes**.

### C3.2
Silence **MUST** always match the exact PCM format defined in **C2**.

### C3.3
Silence **MUST** be precomputed and reused (no recomputation each tick).

---

## C4 — Fallback Audio Sources

### C4.1 — Fallback Priority Order
Fallback audio sources **MUST** follow a strict priority order:

1. **File source** (highest priority)
2. **Tone generator**
3. **Silence** (last resort)

The fallback provider selects the source at startup and maintains this priority order throughout operation.

### C4.2 — File Fallback Requirements

#### C4.2.1
File fallback **MUST** provide PCM frames in the format defined in **C2** (48kHz, stereo, 16-bit, 1152 samples per frame).

#### C4.2.2
File content **MUST** be decoded to PCM format at startup or first use.

#### C4.2.3
File fallback **MUST** support seamless looping if the file is shorter than the required duration.

#### C4.2.4
File fallback **MUST** be selected only if:
- A valid file path is configured
- The file exists and is readable
- The file format is supported (e.g., WAV)

### C4.3 — Tone Fallback Properties (Preferred Fallback)

**440Hz tone is the preferred fallback source** when file-based fallback is unavailable.

#### C4.3.1
Tone **MUST** be represented as valid PCM of the same format as **C2**.

#### C4.3.2
Tone **MUST** be continuous across frames when emitted tick-by-tick (no phase discontinuities).

#### C4.3.3
Tone **MUST** use a phase accumulator to ensure waveform continuity between frames.

#### C4.3.4
Tone generator **MUST** generate 440 Hz tone by default and **MAY** be configurable (e.g., frequency).

#### C4.3.5 — Immediate Return Requirement (Zero Latency Concept)
Tone generator **MUST** return frames **immediately without blocking**.

"Zero latency" is a conceptual requirement meaning the operation must be:
- **Non-blocking** — never wait for I/O or external resources
- **Very fast** — typically completes in microseconds to low milliseconds
- **Deterministic** — predictable execution time
- **Real-time capable** — supports continuous audio playout

**MUST**:
- Be precomputed or generated without blocking
- Not perform slow computations
- Support real-time playout requirements
- Be preferred over silence whenever possible

### C4.4 — Silence Fallback (Last Resort Only)

Silence **MUST** be used **only if tone generation is not possible for any reason**.

#### C4.4.1
Silence fallback **MUST** be a zero-filled PCM frame of size **4608 bytes** (as defined in **C3**).

#### C4.4.2
Silence **MUST** always be available as the final fallback option.

#### C4.4.3
Silence **MUST** be used only if:
- File source is unavailable or fails
- **Tone generator is unavailable or fails** (tone is strongly preferred over silence)

#### C4.4.4 — Immediate Return Requirement (Zero Latency Concept)
Silence fallback **MUST** return frames **immediately without blocking**.

"Zero latency" is a conceptual requirement meaning the operation must be:
- **Non-blocking** — never wait for I/O or external resources
- **Very fast** — precomputed frames should return in microseconds
- **Deterministic** — predictable execution time
- **Real-time capable** — supports continuous audio playout

Silence frames **MUST** be precomputed and reused for maximum speed.

The priority order is: **File → 440Hz Tone → Silence**. Tone is strongly preferred over silence whenever possible.

---

## C5 — MP3 Framing

### C5.1
The MP3 encoder operates on the same **24ms** frame interval as PCM.

### C5.2
MP3 packetization **MUST** preserve timing:

```
1 PCM frame → 1 MP3 frame → output at 24ms intervals
```

### C5.3
FFmpeg handles MP3 packetization internally (per F9.1), and **MUST NOT** violate the tick cadence.

---

## C6 — Buffer Capacity & Constraints

### C6.1
PCM input buffers **MUST** be sized in whole multiples of PCM frames.

### C6.2
`FrameRingBuffer` **MUST** never accept partial frames.

### C6.3
When queried, buffers **MUST** return fill level in units of frames or bytes.

### C6.4
`TowerRuntime`'s `/tower/pcm-buffer-status` endpoint **MUST** expose:

- Total capacity
- Current fill amount
- Fill ratio

> **Note:** This supports upstream backpressure.

---

## C-RB — Frame Ring Buffer Requirements

### C-RB1
Buffer operations **MUST** be thread-safe (single producer, single consumer or equivalent).

### C-RB2 — push() Behavior
`push()` **MUST**:

- Reject empty or None frames
- Drop newest on overflow for PCM
- Drop oldest on overflow for MP3

### C-RB3 — pop() Behavior
`pop()` **MUST** never block:

- Return None if underflow

### C-RB4
All operations **MUST** operate in O(1) time.

### C-RB5 — Required Properties
The buffer **MUST** expose:

- `capacity`
- `count`
- `overflow_count`

---

## C7 — Timing Authority

### C7.1
**AudioPump** is the single authoritative time source.

### C7.2
No other component may maintain its own internal timing cycle.

### C7.3
All timing queries **MUST** use `AudioPump`'s tick or wallclock synchronization defined by the runtime (no drifting).

---

## C8 — PCM Buffer Frame Integrity

### C8.1
All PCM buffers feeding the AudioInputRouter **MUST** be sized in exact frame multiples (4608 bytes per frame).

### C8.2
Partial writes to PCM buffers **MUST** be forbidden; only complete 4608-byte frames may be written.
