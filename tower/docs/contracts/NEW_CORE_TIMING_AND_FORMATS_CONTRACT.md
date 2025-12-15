# Core Timing and Formats Contract

## Purpose

Define the invariant low-level technical parameters used across the entire Tower system. These values never change at runtime and must be identical across all components.

---

## C1 — Global PCM Timing Cadence

### C1.1
The canonical PCM frame size across all Tower components is:

**1024 samples × 2 channels × 2 bytes = 4096 bytes**

### C1.2
The PCM cadence interval is derived from sample rate and frame size:

**1024 samples / 48000 = 0.021333333 seconds (≈21.333ms)**

### C1.3
This PCM cadence is the ONLY timing loop used by:

- **AudioPump**
- **EncoderManager** next_frame()
- **PCMIngestor** delivery into upstream PCM buffer
- **Downstream PCM routing**
- **Fallback generator** frame stepping

### C1.4
MP3 encoding and HTTP streaming operate in their own timing domain and **MUST NOT** influence PCM cadence.

---

## C2 — PCM Format Requirements

### C2.1
All system PCM **MUST** be:

| Parameter | Value |
|-----------|-------|
| Sample rate | 48,000 Hz |
| Channels | 2 (stereo) |
| Bit depth | 16-bit signed integer |
| Frame size | 1024 samples per channel |
| Bytes per frame | 4096 bytes |

### C2.2
PCM frames **MUST** be delivered atomically at **4096 bytes**.

---

## C3 — Silence Frame Standard

### C3.1
The silence frame **MUST** be a zero-filled PCM frame of size **4096 bytes**.

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
File fallback **MUST** provide PCM frames in the format defined in **C2** (48kHz, stereo, 16-bit, 1024 samples per frame, 4096 bytes).

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
Silence fallback **MUST** be a zero-filled PCM frame of size **4096 bytes** (as defined in **C3**).

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

## C5 — MP3 Framing (Encoder Domain Only)

### C5.1
MP3 encoders operate in their own timing domain (typically ~24ms per MP3 frame).

### C5.2
There is no 1:1 mapping between PCM frames and MP3 frames.

### C5.3
FFmpeg **MUST** accept PCM at 1024-sample increments, and MP3 timing **MUST NOT** constrain PCM timing.

---

## C6 — Buffer Capacity & Constraints

### C6.1
PCM input buffers **MUST** be sized in whole multiples of PCM frames.

### C6.2
`FrameRingBuffer` **MUST** never accept partial frames.

### C6.3
When queried, buffers **MUST** return fill level in units of frames or bytes.

### C6.4
`TowerRuntime`'s `/tower/buffer` endpoint **MUST** expose:

- Total capacity
- Current fill amount
- Fill ratio

> **Note:** This supports upstream backpressure. The endpoint path `/tower/buffer` is canonical per T-BUF1 in `NEW_TOWER_RUNTIME_CONTRACT.md`.

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

## C7 — Global Timing Authority

### C7.1
**AudioPump** is the system timing authority, operating at PCM cadence (1024 samples / 21.333ms).

### C7.2
No other subsystem may introduce its own cadence or override PCM timing.

### C7.3
MP3 broadcasting uses a separate pacing mechanism and **MUST NOT** influence PCM timing.

---

## C8 — PCM Buffer Frame Integrity

### C8.1
All PCM buffers feeding the AudioInputRouter **MUST** be sized in exact frame multiples (4096 bytes per frame).

### C8.2
Partial writes to PCM buffers **MUST** be forbidden; only complete 4096-byte frames may be written.
