# Retrowaves Tower — Unified System Architecture

A 24/7, process-isolated, HTTP-based audio transmission service that exposes a single continuous stream for downstream clients (OBS, VLC, YouTube, etc.), independent of DJ and station lifecycle.

> **Note:**  
> Retrowaves Tower is the carrier.  
> Retrowaves Station (Appalachia Radio, etc.) is the brain that generates live PCM audio.

This is the canonical architecture document for `retrowaves-tower.service` and supersedes all previous Tower-related designs.

> **Contract Alignment:**  
> This architecture document aligns with the NEW contract specifications:
> - `NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md` (C-series: timing, formats, buffers)
> - `NEW_ENCODER_MANAGER_CONTRACT.md` (M-series: routing, grace period, fallback)
> - `NEW_FALLBACK_PROVIDER_CONTRACT.md` (FP-series: fallback source selection)
> - `NEW_TOWER_RUNTIME_CONTRACT.md` (T-series: HTTP endpoints, integration)

---

## 1. Executive Summary

Retrowaves Tower is a dedicated, always-on streaming service that:

- Accepts optional PCM audio from one Station instance
- Encodes PCM into MP3
- Streams the resulting bytes over HTTP to any number of connected clients
- Provides a continuous fallback signal (tone now, "Please Stand By" audio later) whenever live PCM is not available

### Key Properties

- **24/7 availability:** The Tower process runs continuously and does not restart when Station/DJ restarts
- **Dumb carrier:** Tower makes no programming decisions. It does not know about songs, intros, IDs, or DJIntent
- **Single encoded signal:** One encoder per station instance, many HTTP clients
- **Continuous audio:** Clients always receive valid audio data, even when Station is offline
- **Cold start stability:** Tower must be able to run forever with zero PCM input without restarting, stalling, or requiring operator assistance. Silence→tone fallback must sustain for years. Tower can start cold with zero PCM and remain stable indefinitely.

**Result:** A deterministic, broadcast-style, single-source stream that downstream clients can trust as a stable, never-refusing endpoint.

---

## 2. Core Principles

### 2.1 Tower Is the Transmitter, Not the Brain

**Tower:**

- Does not pick songs, intros, IDs, or talk
- Does not know rotation rules, cooldowns, or legal ID timing
- Does not implement THINK/DO or DJIntent

**Tower only:**

- Receives PCM frames from Station
- Chooses between live PCM or fallback signal
- Encodes and streams audio to clients

All programming decisions remain in the Station.

### 2.2 24/7 Availability & Process Isolation

- `retrowaves-tower.service` runs continuously as its own process
- `retrowaves-station.service` (DJ/Playout) can be started/stopped/restarted independently
- Tower must continue serving audio during Station outages, restarts, crashes, or maintenance

### 2.3 Single Signal, Many Listeners

- One logical audio signal per Tower instance
- One encoder process (FFmpeg) per Tower
- Any number of HTTP clients can connect to `/stream` and receive a copy of the same encoded stream
- No per-client encoders, no per-client timing differences

### 2.4 Live vs Fallback Modes

Tower operates in two modes:

- **Live Mode:** Station is providing PCM audio. Tower encodes and streams it
- **Fallback Mode:** No live PCM is available. Tower streams a fallback signal (tone now; later, a "Please Stand By" asset)

Mode switching is internal to Tower and does not disconnect clients.

### 2.5 Dumb, Non-Blocking Output

**Tower:**

- Does not block on Station or any external services
- Does not make network calls upstream
- Does not wait for metadata or DJ decisions

If live PCM is unavailable, Tower immediately uses fallback without blocking.

### 2.6 Golden Rules of Tower

These are the immutable invariants that govern all Tower behavior:

1. **Tower never stops streaming audio.** Audio output must be continuous regardless of input, timing, or encoder health. Clients always receive valid MP3 data (real or silence).

2. **Client writes never block Tower.** Slow or blocked clients are automatically dropped. Tower maintains real-time performance at all times.

3. **Encoder may die – stream must not.** Encoder failures trigger automatic restarts, but output continues from buffer, then silence, then real audio. The stream never stops.

4. **Output loop never waits on input.** The tick-driven output loop operates independently from the PCM input pump. Two independent clocks ensure no coupling.

5. **Frame-based semantics end-to-end.** Everything inside the encoder subsystem operates on complete MP3 frames only – no partials. Frame boundaries are preserved throughout the pipeline.

These rules ensure Tower maintains broadcast-grade reliability and performance.

---

## 3. Service Boundaries & Responsibilities

### 3.1 retrowaves-tower.service

**Responsibilities:**

- Maintain an HTTP server that always accepts connections
- Maintain a continuous encoded audio stream
- Receive PCM frames from Station via Unix domain socket (`/var/run/retrowaves/pcm.sock`)
- Generate fallback audio when no live PCM is present
- Handle connection management and broadcasting of encoded bytes

**Non-responsibilities:**

- No DJ logic or rotation
- No metadata semantics (titles, artists, IDs) in the audio path
- No THINK/DO or DJIntent execution

### 3.2 retrowaves-station.service (for context)

**Responsibilities** (from Station architecture):

- DJ THINK/DO model and DJIntent
- Rotation, schedule decisions, playout
- Generation of canonical PCM frames for "what the station is playing"

Station sends PCM to Tower but does not control Tower's lifecycle or HTTP layer.

---

## 4. Audio Input Model

### 4.1 Live PCM Input

Tower exposes an internal interface (`AudioInputRouter`) that Station can push PCM frames into.

**Communication Mechanism:**

**Unix Domain Socket (SOCK_STREAM)**

- **Socket path:** `/var/run/retrowaves/pcm.sock`
- Tower listens on this socket; Station connects when available
- Fast, kernel-level communication with low overhead
- Zero-copy in many cases
- Perfect for two processes on the same machine
- Tower accepts connections; Station retries every 1 second if Tower is not ready

**Socket Permissions:**

- **Owner:** `retrowaves`
- **Group:** `retrowaves`
- **Mode:** `660` (rw-rw----)
- Ensures Station running under systemd can write to the socket

**Canonical format:**

- PCM `s16le`
- 48 kHz sample rate
- 2 channels (stereo)
- `frame_size = 1152` samples (24 ms per frame at 48 kHz)
- `frame_bytes = 4608` bytes (1152 samples × 2 channels × 2 bytes per sample)

**Live PCM Delivery Model:**

Station (producer) → unpaced writes → Unix Socket → Tower Ring Buffer → EncoderManager → AudioPump → Encoder

| Component | Timing Responsibility |
|-----------|----------------------|
| Station | no timing — decode & write frames immediately as available |
| AudioPump | sole metronome — drives 24ms tick interval (1152 samples per tick) |
| EncoderManager | routing authority — selects program/grace/fallback PCM per tick |
| Fallback | provides frames only when EncoderManager requests and no program PCM available |

**Important Principles:**

- **AudioPump is the single authoritative time source (C7.1).** All Tower subsystems operate on the global 24ms tick interval (C1.3).
- **Station pushes fast; AudioPump pulls steady.** AudioPump is the rate limiter, consuming frames at exactly 48kHz → 1152-sample frames → 24ms intervals.
- **EncoderManager is the single routing authority (M11, M12).** Only EncoderManager decides between program PCM, grace-period silence, or fallback. No other component implements routing logic.
- **Buffer must be bounded (200–500ms max recommended).** A ring buffer absorbs burstiness; underflow triggers grace silence then fallback.
- **Buffer never grows unbounded — AudioPump consumption rate stabilizes the system.** Overflow drops newest or oldest depending on strategy (C-RB2).
- **Grace period uses monotonic clock (M-GRACE1).** Grace period is 5 seconds default (M8), configurable via `TOWER_PCM_GRACE_SEC`.

**Format Validation:**

- **Trust-based:** Tower trusts Station to provide correctly formatted PCM
- No validation is performed for performance; both processes are under the same architecture control
- If format mismatch bugs appear, validation can be added later

### 4.2 Fallback Signal

When no live PCM is available:

- Tower generates PCM frames representing a fallback signal
- **Initial implementation:** continuous tone (e.g., 440 Hz sine) to confirm behavior
- **Future implementation:** looping "Please Stand By" MP3 or emergency/technical difficulties audio

Fallback is internal to Tower and requires no Station participation.

**Fallback Source Priority Order:**

Per NEW_CORE_TIMING_AND_FORMATS_CONTRACT (C4.1) and NEW_FALLBACK_PROVIDER_CONTRACT (FP3), the fallback provider selects sources using the following strict priority order (highest to lowest):

1. **File Source** (if `TOWER_SILENCE_MP3_PATH` is configured and exists):
   - File fallback MUST provide PCM frames in format C2 (48kHz, stereo, 16-bit, 1152 samples per frame) (C4.2.1)
   - File content MUST be decoded to PCM format at startup or first use (C4.2.2)
   - File fallback MUST support seamless looping if file is shorter than required duration (C4.2.3)
   - File fallback MUST be selected only if valid file path is configured, file exists and is readable, and format is supported (C4.2.4)

2. **440Hz Tone Generator** (preferred fallback):
   - **440Hz tone is the preferred fallback source** when file-based fallback is unavailable (C4.3, FP3.2)
   - Tone MUST be represented as valid PCM of the same format as C2 (C4.3.1)
   - Tone MUST be continuous across frames when emitted tick-by-tick (no phase discontinuities) (C4.3.2)
   - Tone MUST use a phase accumulator to ensure waveform continuity between frames (C4.3.3)
   - Tone generator MUST return frames immediately without blocking (zero latency concept) (C4.3.5, FP2.2)
   - Tone is strongly preferred over silence whenever possible (FP3.2, FP5.2)

3. **Silence** (last resort only):
   - Silence MUST be used **only if tone generation is not possible for any reason** (C4.4, FP3.3)
   - Silence MUST be a zero-filled PCM frame of size 4608 bytes (as defined in C3) (C4.4.1)
   - Silence MUST always be available as the final fallback option (C4.4.2)
   - Silence frames MUST be precomputed and reused for maximum speed (C3.3, C4.4.4)

The priority order is: **File → 440Hz Tone → Silence**. Tone is strongly preferred over silence whenever possible.

### 4.3 Input Selection Logic (EncoderManager Routing Authority)

Per NEW_ENCODER_MANAGER_CONTRACT (M11, M12), **EncoderManager is the single, authoritative decision-maker** for which audio source is used each tick. No other component implements routing logic.

**At each audio tick (exactly 24ms intervals, driven by AudioPump's metronome):**

1. **AudioPump** calls `EncoderManager.next_frame()` with no arguments (M1)
2. **EncoderManager** reads PCM from internal buffer (populated via `write_pcm()` from upstream) or determines absence
3. **EncoderManager** applies source selection rules (M6, M7):
   - **If PCM present and valid (M6):** EncoderManager updates `last_pcm_seen_at` to `now()` and returns program PCM frame (**PROGRAM**)
   - **If PCM absent (M7):** EncoderManager calculates `since = now() - last_pcm_seen_at`:
     - **If `since <= GRACE_SEC` (M7.1):** Returns canonical precomputed silence frame (**GRACE_SILENCE**)
     - **If `since > GRACE_SEC` (M7.2):** Calls `fallback_provider.next_frame()` and returns fallback frame (**FALLBACK**)
4. **AudioPump** receives the selected PCM frame and writes it to encoder via `EncoderManager.write_pcm()`

**Grace Period Requirements (M-GRACE):**

- **Grace timers MUST use monotonic clock (M-GRACE1)**
- **Silence frame MUST be precomputed and reused (M-GRACE2)**
- **At exactly `t == GRACE_SEC`, silence still applies; tone applies only at `t > GRACE_SEC` (M-GRACE3)**
- **Grace resets immediately when program PCM returns (M-GRACE4)**
- **GRACE_SEC MUST be configurable (default 5 seconds) (M8)**

**Key Points:**

- **AudioPump is the single authoritative time source (C7.1)** — drives 24ms tick interval
- **EncoderManager is the single routing authority (M11, M12)** — only component that decides program/grace/fallback
- **Station writes are unpaced bursts; AudioPump's steady pull rate stabilizes the buffer**
- **Grace period prevents tone blips during short gaps between tracks**
- **This logic ensures there is never a gap in the PCM stream feeding the encoder (S7.0A, S7.0D)**

This architecture aligns with broadcast automation, SDR, VoIP jitter buffers, ALSA/JACK, Icecast source clients, radio encoders, and MPEG TS playout systems.

---

## 5. Encoding & Streaming

### 5.1 Encoder Process

Tower uses FFmpeg as an external encoder:

**Complete FFmpeg Command:**

```bash
ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 \
       -f mp3 -b:a 128k -acodec libmp3lame \
       pipe:1
```

**Input:**

- `-f s16le` - Input format: signed 16-bit little-endian PCM
- `-ar 48000` - Sample rate: 48 kHz
- `-ac 2` - Channels: stereo
- `-i pipe:0` - Read from stdin

**Output:**

- `-f mp3` - Output format: MP3
- `-b:a 128k` - Audio bitrate: 128 kbps (or configurable)
- `-acodec libmp3lame` - MP3 encoder: LAME
- `pipe:1` - Write to stdout

Tower writes PCM to FFmpeg stdin and reads encoded MP3 chunks from FFmpeg stdout.

**Error Handling:**

- If FFmpeg fails to start, Tower should log the error and continue with fallback audio
- If FFmpeg writes invalid data or crashes, Tower should detect and restart the encoder

### 5.2 Broadcast-Grade Encoding Architecture

Tower implements a production-quality encoding subsystem designed to eliminate silent failures, ensure frame-aligned MP3 output, and provide jitter-tolerant streaming with smooth encoder restarts.

**Core Invariant:** MP3 output must be smooth and continuous regardless of input, timing, or encoder health.

**Global Timing Contract (C1):**
- **Universal timing tick: 24ms (C1.1)** — all Tower subsystems operate on this global tick
- **24ms = 1152 samples at 48kHz (C1.2)**
- **All subsystems MUST operate on this global tick (C1.3):** AudioPump, EncoderManager, FFmpegSupervisor input pacing, TowerRuntime HTTP streaming tick
- **No other subsystem may introduce its own timing loop (C1.3)**

#### 5.2.1 Dual-Buffer Architecture

The encoding subsystem uses a **dual-buffer architecture** with independent input and output queues, separated by the FFmpeg encoder process:

- **PCM Input Buffer**: Thread-safe ring buffer for PCM frames (~50-100 frames, ~1-2 seconds)
  - Populated via `EncoderManager.write_pcm()` from upstream (Station or test injection)
  - Consumed by AudioPump at 24ms tick intervals (C1.1, C7.1)
  - Non-blocking writes (drops newest if full per C-RB2)
  - Non-blocking reads (returns None if empty per C-RB3)

- **MP3 Output Buffer**: Frame-based ring buffer for MP3 frames (~400 frames, ~5 seconds depth)
  - Consumed by tick-driven broadcast loop (consumer clock)
  - Stores complete MP3 frames only (no partials)
  - Non-blocking writes (drops oldest if full per C-RB2)
  - Non-blocking reads (returns None if empty per C-RB3)

**Why Split Buffers?**
- Input timing (PCM pump) operates independently from output timing (HTTP broadcast)
- No coupling between input and output clocks
- Prevents jitter and timing dependencies

#### 5.2.2 Frame-Aligned MP3 Output

**Problem:** Arbitrary byte accumulation (e.g., `read(8192)`) can split MP3 frames at non-frame boundaries, causing audio warble/distortion and decoder sync issues.

**Solution:** `MP3Packetizer` ensures complete MP3 frames only:
- Detects sync word: `0xFF + (next_byte & 0xE0 == 0xE0)`
- Parses first frame header to compute fixed frame size (CBR assumption)
- Yields only complete frames (fixed-size after first header)
- Frame-based buffer ensures no partials in pipeline

**Frame-Based Semantics:**
- Everything inside encoder subsystem operates on complete MP3 frames only
- Frame boundaries preserved end-to-end
- Multiple frames can be joined only at socket edge (when writing to clients)

#### 5.2.3 Tick-Driven Output Pacing

**Problem:** "Read as fast as possible" causes CPU spinning, inconsistent output rate, buffer oscillation, and poor jitter tolerance.

**Solution:** Tick-driven loop with fixed interval aligned to global 24ms tick (C1.1):
- Consistent output rate (not bursty)
- Better jitter tolerance (smooths network/system delays)
- Lower CPU usage (no busy loops)
- Predictable behavior
- All subsystems operate on same 24ms global tick (C1.3)

**Output Loop:**
```python
# Tick-driven broadcast loop (24ms intervals per C1.1)
tick_interval_ms = 24  # Global metronome interval (C1.1)
while not shutdown:
    frame = encoder_manager.get_frame()  # Returns frame or silence_frame
    broadcast(frame)
    sleep(tick_interval_ms)  # Fixed interval, aligned to global tick
```

#### 5.2.4 Encoder Lifecycle & Restart Flow

**Stall Detection:**
- Monitors encoder output for stalls (0 bytes for N milliseconds)
- Default threshold: 2000ms (configurable via `TOWER_ENCODER_STALL_THRESHOLD_MS`)
- Triggers automatic restart when stall detected

**Restart Flow (Smooth Transition):**

1. **Detection**: Monitor thread or drain thread detects failure/stall
2. **State Transition**: `RUNNING` → `RESTARTING`
3. **Continue Streaming Buffer**: Keep streaming MP3 buffer content until empty
   - Output loop is **completely oblivious** to restart state
   - Buffer acts as bridge between old and new encoder
4. **Silence Filler**: When buffer empties, `get_frame()` returns silence frame
5. **Async Restart**: Restart thread waits for backoff delay, then starts new encoder
6. **Buffer Refill**: New MP3 data fills ring buffer (via MP3Packetizer)
7. **Smooth Blend**: When buffer refills, `get_frame()` automatically returns real frames

**Key Points:**
- **Buffer is NOT cleared** during restart (only on full failure after max restarts)
- Restart never blocks output path
- Playback continues during restart (from buffer, then silence, then real)
- No instant flip, no jitter loop, no state checks in output path

**Backoff Strategy:**
- **Max restart attempts:** 5
- **Backoff schedule:** [1000, 2000, 4000, 8000, 10000]ms (exponential, capped at 10s)
- After 5 failures: Tower enters FAILED state but keeps HTTP server running

#### 5.2.5 EncoderManager Components

**EncoderManager** (`tower/encoder_manager.py`):
- Manages FFmpeg encoder process lifecycle
- Stall detection and async restart
- State management: RUNNING, RESTARTING, FAILED, STOPPED
- Key methods:
  - `write_pcm(data)`: Fire-and-forget PCM writes (non-blocking, independent clock)
  - `get_frame()`: Returns one complete MP3 frame or silence frame (tick-driven)

**EncoderOutputDrainThread**:
- Dedicated thread that continuously drains encoder stdout
- Reads MP3 bytes from FFmpeg stdout as fast as possible
- Feeds complete MP3 frames to ring buffer via MP3Packetizer
- Detects stalls and triggers restart
- Uses `select()` with timeout for efficient polling

**MP3Packetizer** (`tower/audio/mp3_packetizer.py`):
- Accumulates raw MP3 bytes and yields complete frames
- Simplified for fixed CBR profile (MPEG-1 Layer III, 128kbps)
- Computes frame size from first header, then treats all frames as fixed-size

**FrameRingBuffer** (`tower/audio/ring_buffer.py`):
- Frame-based ring buffer (not byte-based)
- Capacity: ~400 frames (5-second depth)
- Methods: `push_frame()`, `pop_frame()`, `stats()`

#### 5.2.6 Configuration

```bash
# Encoder stall detection threshold (milliseconds)
TOWER_ENCODER_STALL_THRESHOLD_MS=2000

# Encoder restart backoff schedule (comma-separated milliseconds)
TOWER_ENCODER_BACKOFF_MS=1000,2000,4000,8000,10000

# Maximum encoder restart attempts
TOWER_ENCODER_MAX_RESTARTS=5

# MP3 output buffer capacity (frames) - 5 seconds @ ~42 fps (24ms intervals) = ~208 frames
# Recommended: 400 frames (with headroom) for jitter tolerance
TOWER_MP3_BUFFER_CAPACITY_FRAMES=400

# PCM input buffer size (frames) - ~1-2 seconds
TOWER_PCM_BUFFER_SIZE=100

# Tick-driven output interval (milliseconds) - MUST match global 24ms metronome (C1.1, C1.3)
TOWER_OUTPUT_TICK_INTERVAL_MS=24  # Global metronome interval per C1.1
```

**Default Values:**
- Stall Threshold: 2000ms
- Backoff Schedule: [1000, 2000, 4000, 8000, 10000]ms
- Max Restarts: 5
- MP3 Buffer Capacity: 400 frames (~5 seconds @ ~42 fps, 24ms intervals)
- PCM Buffer Size: 100 frames (~2.4 seconds at 24ms intervals)
- Output Tick Interval: 24ms (global metronome interval per C1.1, C1.3)
- Grace Period: 5.0 seconds (default per M8)

**Performance Characteristics:**
- Latency: ~5 seconds (MP3 buffer depth)
- CPU Usage: Minimal (select-based I/O, tick-driven pacing, no busy loops)
- Memory Usage: ~150KB-1.7MB (MP3 buffer, depends on frame size) + ~100KB (PCM buffer)
- Restart Time: ~1-10 seconds (depending on backoff schedule)
- Output Rate: ~42 frames/second (24ms tick interval per C1.1)

For detailed troubleshooting, design rationale, and verification procedures, see the full encoding architecture documentation in `tower/docs/BROADCAST_ENCODER_ARCHITECTURE.md`.

#### 5.2.7 Broadcast-Grade Behavior Specification

This section defines the end-to-end behavior of the Tower encoding path: PCM input (or lack thereof), fallback generator, EncoderManager, FFmpegSupervisor, and MP3 output. The encoder subsystem MUST be able to start and idle for years with no external PCM, produce valid MP3 at all times, survive encoder failures and restarts without audible glitches, and switch cleanly between fallback tone and real PCM.

##### Core Broadcast Invariants

**[BG1] No Dead Air (MP3 Layer)**

Once `TowerService.start()` returns "Encoder started", every call to `EncoderManager.get_frame()` MUST return a valid MP3 frame (silence/tone/program). None is not allowed in production.

**[BG2] No Hard Dependence on PCM**

The system MUST NEVER require external PCM to be present to:
- Keep FFmpeg alive
- Avoid restarts
- Satisfy timing/watchdog constraints

The encoder MUST be able to run forever on fallback alone.

**[BG3] Predictable Audio State Machine**

At any instant, the encoder is in exactly one of:
- **SILENCE_GRACE** – startup / recent loss of PCM: silence only
- **FALLBACK_TONE** – stable absence of PCM: tone (or configured fallback)
- **PROGRAM** – real PCM only
- **DEGRADED** – failure mode (silence only but still valid MP3)

All state transitions MUST be deterministic and logged.

##### Timeline: Startup & Idle Behavior

**2.1 Startup with No PCM Present**

**[BG4] Initial Conditions**

When `TowerService.start()` is called with no external PCM arriving (PCM buffer empty) and EncoderManager enabled:

- FFmpegSupervisor starts FFmpeg and immediately writes at least one PCM frame (silence)
- Within 1 frame interval (≈24ms), EncoderManager MUST start continuous PCM fallback injection into FFmpeg (silence first)
- Fallback injection MUST continue indefinitely at real-time pace (≈24ms per frame) until real PCM is detected and stable

**2.2 Grace → Tone**

Let `GRACE_PERIOD_MS` (default 1500ms).

**[BG5] Silence Grace Period**

From the moment fallback starts, the encoder MUST inject silence PCM only for at least `GRACE_PERIOD_MS` (e.g. 1500ms). During this period, FFmpeg produces valid MP3 frames (silence audio).

**[BG6] Tone Lock-In**

After `GRACE_PERIOD_MS` has elapsed and there have still been no valid external PCM frames detected, system MUST transition to FALLBACK_TONE:
- PCM injection switches from silence to tone frames (from FallbackGenerator) if tone is enabled
- If tone is disabled by config, it remains in pure silence but is still considered FALLBACK_TONE state internally (different from SILENCE_GRACE)

**[BG7] Long-Term Idle Stability**

The encoder MUST be able to remain in FALLBACK_TONE state for arbitrarily long durations (hours/days/years) with:
- No FFmpeg restarts caused by input absence
- No MP3 underflow
- No watchdog "no first frame" or "stall" events as long as FFmpeg is producing output

##### Detecting Real PCM & Transitioning to Program

**3.1 PCM Detection**

**[BG8] PCM Validity Threshold**

A "real PCM stream present" condition is met when:
- A continuous run of N frames (e.g. 10–20) have been read from the PCM buffer (by AudioPump → write_pcm)
- AND these frames are not all zeros (if zero-only can't be distinguished, treat "frames present" as the condition)

This prevents toggling due to single stray frames.

**3.2 Tone → Program Transition**

**[BG9] Transition Trigger**

When PCM_PRESENT becomes true while encoder is in FALLBACK_TONE state:
- EncoderManager MUST stop fallback injection immediately or within 1 frame
- Thereafter, only real PCM is fed to FFmpeg via write_pcm (LIVE_INPUT mode)

**[BG10] Click/Pop Minimization**

EncoderManager/AudioPump MUST ensure there is no large discontinuity at the moment of switch:
- If you have a compressor/limiter: rely on it but avoid sudden zero → full-scale jumps
- At minimum, do NOT change sample rate/format/bit depth
- Optional enhancement (recommended): Crossfade 1–2 frames between tone and PCM in PCM domain before handing to FFmpeg, or start PCM at a low gain and ramp to full over a small number of frames
- But even without crossfade, maintain same RMS ballpark to avoid obvious blast

**3.3 Program → Tone (Loss of PCM)**

**[BG11] Loss Detection**

Once in PROGRAM state, if no valid PCM frames are available for `LOSS_WINDOW_MS` (e.g. 250–500ms), system MUST treat this as "loss of program audio".

**[BG12] Program Loss Transition**

On program loss:
- Enter SILENCE_GRACE again (silence injection, reset grace timer)
- After another `GRACE_PERIOD_MS` without PCM, move back to FALLBACK_TONE
- Hysteresis prevents rapid flipping if PCM flickers

##### Encoder Liveness & Watchdogs

**4.1 First Frame Watchdog**

**[BG13] First Frame Source-Agnostic**

The "first MP3 frame received" condition MUST be satisfied by any valid MP3 output (from silence, tone, or real program), not just real inputs. As soon as stdout yields one valid frame, "BOOTING" timeout is satisfied. No additional requirement that PCM be present.

**4.2 Stall Detection While Idle**

**[BG14] Stall Semantics**

A "stall" is defined as no MP3 bytes from FFmpeg for `STALL_THRESHOLD_MS`. This MUST fire whether we're on program or fallback.

**[BG15] Stall Recovery**

On stall:
- Supervisor transitions to RESTARTING and executes restart backoff
- EncoderManager MUST continue fallback injection once FFmpeg is up again, returning to SILENCE_GRACE → FALLBACK_TONE sequence as needed
- Crucially: stall due to input absence should never happen if fallback injection is working; a stall indicates real FFmpeg failure, which justifies restart

##### Restart Behavior & State Preservation

**5.1 MP3 Buffer Continuity**

**[BG16] Buffer Preservation Across Restart**

When FFmpeg restarts:
- The MP3 ring buffer MUST NOT be forcibly cleared by EncoderManager or Supervisor
- Any frames already queued MUST be allowed to drain (they'll disappear naturally as consumed)
- This avoids abrupt artifacts on the listener side at the moment of restart if the player is slightly ahead

**5.2 Fallback Re-Entry After Restart**

**[BG17] Automatic Fallback Resumption**

After a restart completes:
- Fallback injection MUST resume automatically until conditions for PROGRAM are again satisfied
- There MUST be no window after restart where FFmpeg is running but receiving no PCM from either program or fallback

##### Production vs Test Behavior

**6.1 OFFLINE_TEST_MODE**

**[BG18] OFFLINE_TEST_MODE as Local Simulation Only**

When `TOWER_ENCODER_ENABLED=0` or `encoder_enabled=False`, EncoderManager MUST NOT start FFmpeg at all. `get_frame()` MUST return synthetic MP3 silence frames (created locally), following the same timing expectations. Fallback injection and watchdog logic can be bypassed. This ensures you can unit-test the upper stack without invoking FFmpeg.

**6.2 Test-Safe Defaults**

**[BG19] No Tone in Tests by Default**

For unit/contract tests:
- Default `TOWER_PCM_FALLBACK_TONE=0` to avoid requiring audio inspections
- Ensure fallback silence is enough to satisfy watchdogs
- Production configs re-enable tone as needed

##### Logging & Monitoring Requirements

**[BG20] Mode Logging**

Whenever encoder state changes: SILENCE_GRACE ↔ FALLBACK_TONE ↔ PROGRAM ↔ DEGRADED, Tower MUST log:
- Old state → new state
- Reason (startup, PCM detected, PCM lost, encoder restart, fatal error)
- Relevant counters (grace ms elapsed, restarts count, etc.)

**[BG21] Alarms**

At minimum, the following events should generate operational alarms (or at least WARN/ERROR):
- Repeated FFmpeg restarts exceeding max_restarts
- Persistent operation in FALLBACK_TONE for longer than some configurable threshold (e.g. 10 minutes) – this can be a "no program audio" alarm
- Switches to DEGRADED (FFmpeg completely dead or disabled)

##### Automatic Self-Healing & Recovery

**[BG22] Self-Healing After Max Restarts**

If FFmpeg reaches `max_restarts`, state becomes DEGRADED but streaming continues. System shall retry full encoder recovery every `RECOVERY_RETRY_MINUTES` (default 10 minutes). Must run FOREVER without operator intervention. This prevents a 3AM outage from requiring manual intervention.

**Implementation:**
- After max restarts, enter DEGRADED state but continue streaming fallback audio
- Start background recovery timer that attempts full encoder restart every `RECOVERY_RETRY_MINUTES`
- Each recovery attempt follows normal startup sequence (BOOTING → RUNNING)
- If recovery succeeds, transition back to PROGRAM or FALLBACK_TONE as appropriate
- If recovery fails, continue streaming fallback and schedule next retry
- System must never give up permanently; retries continue indefinitely

##### Audio Transition Smoothing

**[BG23] Optional Crossfade for Fallback → Program Transitions**

Fallback → Program transitions must support optional crossfade (default off but architecture prepared to support it). Real broadcast stations use crossfading to eliminate clicks, pops, and level jumps during source transitions.

**Implementation:**
- Crossfade is optional and disabled by default (`TOWER_CROSSFADE_ENABLED=0`)
- When enabled, perform 1-2 frame crossfade in PCM domain before handing to FFmpeg
- Architecture must support crossfade without blocking or timing disruption
- Crossfade parameters: duration (frames), curve (linear/logarithmic), and gain normalization
- Even without crossfade, maintain same RMS ballpark to avoid obvious level jumps

##### File Fallback Looping

**[BG24] Sample-Accurate Gapless File Fallback**

When fallback MP3/WAV is used, decoding MUST occur into PCM at startup. Loop must be sample-accurate, gapless, and stable indefinitely. This ensures professional "Please Stand By" or emergency audio loops seamlessly without audible gaps or clicks.

**Implementation:**
- Pre-decode fallback file to PCM at Tower startup (not on-demand)
- Cache decoded PCM frames in memory for low-latency access
- Loop detection: identify loop points (start/end samples) for seamless wrapping
- Sample-accurate looping: no frame boundary misalignment, no partial samples
- Gapless playback: zero samples of silence between loop iterations
- Stable indefinitely: loop must run for hours/days without drift or accumulation errors
- Fallback: If file decoding fails, fall through to tone generator

##### Silence Detection on Program PCM

**[BG25] Amplitude-Aware Silence Detection**

Real PCM may contain silence (songs with silence, mixers idle). Silence ≠ no-input. Silence detection must be amplitude-aware not just "frame present". This stops tone falsely firing during quiet songs or natural program silence.

**Implementation:**
- PCM presence detection must distinguish between:
  - **No input**: No frames arriving from source (triggers fallback)
  - **Silent input**: Frames arriving but containing silence/very low amplitude (remains in PROGRAM)
- Amplitude threshold: Configure RMS or peak threshold below which PCM is considered "silent" but still "present"
- Default threshold: -60dB or configurable via `TOWER_PCM_SILENCE_THRESHOLD_DB`
- Hysteresis: Require sustained silence for `SILENCE_DURATION_MS` before treating as "no input"
- This prevents false fallback triggers during:
  - Quiet passages in music
  - Mixer fader-down moments
  - Natural program silence between tracks

##### Observability & Monitoring API

**[BG26] HTTP Status Endpoint for DevOps**

HTTP `/status` endpoint must expose:
- Current source (program/tone/silence)
- PCM buffer fullness (frames available / capacity)
- MP3 buffer fullness (frames available / capacity)
- Restarts count (total encoder restarts since startup)
- Uptime (seconds since TowerService.start())
- Optional: JSON stats for dashboards

**Implementation:**
- Endpoint: `GET /status` returns JSON with current system state
- Response format:
  ```json
  {
    "source": "program|tone|silence",
    "encoder_state": "RUNNING|RESTARTING|DEGRADED|STOPPED",
    "pcm_buffer": {
      "available": 45,
      "capacity": 100,
      "percent_full": 45
    },
    "mp3_buffer": {
      "available": 320,
      "capacity": 400,
      "percent_full": 80
    },
    "restarts": 2,
    "uptime_seconds": 86400,
    "recovery_retries": 0
  }
  ```
- Non-blocking: Status endpoint must never block or affect audio streaming
- Thread-safe: All status queries must be safe to call from any thread
- Optional dashboard integration: Consider Prometheus metrics or similar for long-term monitoring

**Note:** This endpoint doesn't need to be implemented immediately, but once Tower runs months continuously, operational visibility becomes critical for diagnosing issues and monitoring health.

##### Summary: What This Guarantees

With this spec in place, you can start Tower with zero PCM and walk away for hours. The encoder will:
- Start FFmpeg immediately
- Begin streaming silence as valid MP3
- After grace, smoothly switch to tone (if enabled)
- Maintain that tone forever with no restarts
- When real PCM appears and is stable, stop tone immediately and feed real program audio
- If program disappears, grace → silence → tone resumes automatically
- Any FFmpeg crash triggers a restart without ever requiring PCM to be present
- After max restarts, system continues streaming fallback and automatically retries recovery every 10 minutes forever
- Optional crossfade eliminates clicks/pops during source transitions
- File fallback loops seamlessly without gaps
- Silence detection prevents false fallback during quiet program content
- Status endpoint provides operational visibility for long-running deployments

That's the broadcast-grade behavior: no dead air, no requirement that the studio "talks" immediately, deterministic logged transitions between known audio states, automatic self-healing, and operational observability.

### 5.3 Encoded Stream Characteristics

- **Format:** MP3 (initially; may be configurable later)
- **Bitrate:** 128 kbps CBR or similar, configurable
- **Continuous, uninterrupted byte stream** suitable for:
  - VLC
  - OBS's "Media Source" or "Network Source"
  - `ffplay` / `curl` testing
  - Relaying to YouTube, etc.

---

## 6. HTTP Server & Connection Management

### 6.1 HTTP Server

Tower runs a dedicated HTTP server (threaded or async, but process-local) that:

- Listens on a configured host/port (e.g., `0.0.0.0:8000`)
- Exposes a primary endpoint:
  - `GET /stream` → continuous audio stream
- Uses raw streaming (no chunked encoding) - VLC and OBS prefer raw streaming without chunk framing overhead
- Continuously writes MP3 bytes to the socket as they become available

**HTTP Response Headers:**

```
HTTP/1.1 200 OK
Content-Type: audio/mpeg
Cache-Control: no-cache, no-store, must-revalidate
Connection: keep-alive
```

**Note:** Do NOT use `Transfer-Encoding: chunked` - clients prefer raw streaming.

### 6.2 HTTPConnectionManager

**Responsibilities:**

- Track all currently connected clients
- Write MP3 chunks to each client as they arrive
- Handle client disconnects gracefully (remove from tracking, close socket)
- Ensure that slow or blocked clients do not stall the encoder reader loop

**Slow Client Handling:**

- **Cardinal rule:** Never block Tower
- Use non-blocking writes to all clients
- If a client cannot accept data for >250 ms, drop the client
- Slow clients are automatically removed from the broadcast list
- This ensures Tower always maintains real-time performance

**Thread Safety:**

- All operations must be thread-safe (multiple threads may call `broadcast()` concurrently)
- Client list modifications must be protected by locks or use thread-safe data structures

### 6.3 Broadcast Model

- Tower runs a central loop reading encoded MP3 chunks from FFmpeg stdout
- Each chunk is passed to `HTTPConnectionManager.broadcast(mp3_data)`
- Each connected client receives the same data, preserving a true broadcast model
- Slow clients (>250 ms timeout) are automatically dropped (see Section 6.2)

### 6.4 Connection Behavior

- New clients can connect at any time
- Clients always receive valid MP3 audio:
  - Live station content when available
  - Fallback audio otherwise
- Tower never rejects connections due to Station status
- Clients joining mid-stream will receive audio from the current point (no backfill)

**Multi-Client Startup Offset Behavior:**

- Tower starts streaming bytes the moment a client connects
- Clients joining mid-stream start receiving MP3 frames at arbitrary alignment
- MP3 decoders naturally resync without issue (this is expected behavior)
- OBS and other clients handle this seamlessly - no special handling required

---

## 7. Internal Components

### 7.1 PCM Input Buffer (FrameRingBuffer)

Per NEW contracts, AudioInputRouter has been removed. PCM input is handled via a FrameRingBuffer that EncoderManager reads from.

**PCM Input Flow:**

- Station writes PCM frames to Unix domain socket (`/var/run/retrowaves/pcm.sock`)
- Frames are written to a FrameRingBuffer via `EncoderManager.write_pcm(frame)`
- **Buffer capacity:** Configurable (typically 50-100 frames, ~1-2 seconds at 24ms intervals)
  - Bounded size prevents unbounded growth
  - AudioPump's steady consumption rate (24ms per frame) stabilizes the buffer
  - Absorbs burstiness from Station's unpaced writes

**FrameRingBuffer Requirements (C-RB):**

- **Thread-safe operations (C-RB1):** Buffer operations MUST be thread-safe
- **push() behavior (C-RB2):** Reject empty/None frames, drop newest on overflow for PCM
- **pop() behavior (C-RB3):** MUST never block, return None if underflow
- **O(1) time (C-RB4):** All operations MUST operate in O(1) time
- **Required properties (C-RB5):** Buffer MUST expose capacity, count, overflow_count

**Buffer Overflow Handling:**

- If the buffer is full when Station tries to write:
  - **Strategy:** Drop incoming frame (newest frame is discarded per C-RB2)
  - Station writes are unpaced bursts; AudioPump's steady pull rate prevents sustained overflow
  - Station stays non-blocking; Tower maintains continuous audio flow
  - Buffer never grows unbounded — AudioPump consumption rate stabilizes the system

**Buffer Underflow Handling:**

- If the buffer is empty when EncoderManager reads:
  - EncoderManager applies source selection rules (M6, M7)
  - If within grace period: returns grace silence (M7.1)
  - If grace period expired: calls fallback provider (M7.2)
  - This ensures continuous PCM output per S7.0A, S7.0D

**Frame Integrity (C8):**

- All PCM buffers MUST be sized in exact frame multiples (4608 bytes per frame) (C8.1)
- Partial writes to PCM buffers MUST be forbidden; only complete 4608-byte frames may be written (C8.2)
- Frame size must remain stable (4608 bytes) even under concurrent operations (C8.3)

### 7.2 FallbackProvider (FallbackGenerator)

Per NEW_FALLBACK_PROVIDER_CONTRACT, the FallbackProvider is the exclusive source of non-program audio used when upstream PCM is unavailable beyond the grace period.

**Responsibilities (FP2):**
- Produce exactly one **4608-byte PCM frame** on every call to `next_frame()` (FP2.1)
- Guarantee that `next_frame()` returns **immediately without blocking** (zero latency concept) (FP2.2)
- Provide audio in the PCM format defined by the Core Timing Contract: 48kHz, stereo, 1152 samples, 4608 bytes (FP2.3)
- Guarantee that it always returns a valid frame — **no exceptions** (FP2.4)

**Source Selection Priority (FP3, C4.1):**

The fallback provider selects sources using the following strict priority order:

1. **File Source** (if `TOWER_SILENCE_MP3_PATH` is configured and exists):
   - File fallback MUST provide PCM frames in format C2 (48kHz, stereo, 16-bit, 1152 samples per frame) (C4.2.1)
   - File content MUST be decoded to PCM format at startup or first use (C4.2.2)
   - File fallback MUST support seamless looping if file is shorter than required duration (C4.2.3)

2. **440Hz Tone Generator** (preferred fallback):
   - **440Hz tone is the preferred fallback source** when file-based fallback is unavailable (C4.3, FP3.2)
   - Tone MUST be continuous across frames when emitted tick-by-tick (no phase discontinuities) (C4.3.2)
   - Tone MUST use a phase accumulator to ensure waveform continuity between frames (C4.3.3)
   - Tone generator MUST return frames immediately without blocking (zero latency concept) (C4.3.5, FP2.2)

3. **Silence** (last resort only):
   - Silence MUST be used **only if tone generation is not possible for any reason** (C4.4, FP3.3)
   - Silence MUST be a zero-filled PCM frame of size 4608 bytes (as defined in C3) (C4.4.1)
   - Silence frames MUST be precomputed and reused for maximum speed (C3.3, C4.4.4)

The priority order is: **File → 440Hz Tone → Silence**. Tone is strongly preferred over silence whenever possible.

### 7.3 AudioPump

Runs in its own thread. **AudioPump is the single authoritative time source (C7.1).** All Tower subsystems operate on the global 24ms tick interval (C1.1, C1.3).

**Loop (exactly 24ms per iteration, using absolute clock timing per C1.1):**

1. Call `EncoderManager.next_frame()` with no arguments (M1)
   - EncoderManager is the single routing authority (M11, M12)
   - EncoderManager reads PCM from internal buffer (populated via `write_pcm()` from upstream)
   - EncoderManager applies source selection rules: program PCM, grace silence, or fallback (M6, M7)
2. Receive selected PCM frame from EncoderManager (guaranteed to be valid per S7.0A, S7.0D)
3. Write PCM frame to encoder via `EncoderManager.write_pcm(frame)` (non-blocking)
4. Handle encoder errors (broken pipe, etc.) — EncoderManager handles restart logic
5. **Sleep for remaining time in 24ms period** (absolute clock timing prevents drift)

**Timing Model (C1, C7):**

- **Global metronome interval: 24ms (C1.1)** — all Tower subsystems operate on this tick
- **24ms = 1152 samples at 48kHz (C1.2)**
- Uses absolute clock timing (`next_frame_time += FRAME_DURATION`) to prevent cumulative drift
- If loop falls behind schedule, resyncs clock instead of accumulating delay
- **AudioPump is the rate limiter:** consumes frames at exactly 48kHz → 1152-sample frames → 24ms intervals
- Station pushes fast (unpaced bursts); AudioPump pulls steady (metronome)
- **No other component may maintain its own internal timing cycle (C7.2)**

**Thread Safety:**

- Must coordinate with EncoderManager (thread-safe buffer operations)
- Must handle encoder process lifecycle (process may be restarted by EncoderManager)

### 7.4 Encoder Output & Broadcast Loop

The encoder output path is implemented as a tick-driven loop (see Section 5.2.3 for details).

**Architecture:**

1. **EncoderOutputDrainThread**: Dedicated thread drains FFmpeg stdout, packetizes MP3 frames via MP3Packetizer, and pushes complete frames to MP3 ring buffer
2. **Tick-Driven Broadcast Loop**: Fixed-interval loop (15ms default) that:
   - Calls `encoder_manager.get_frame()` to get one complete MP3 frame or silence frame
   - Broadcasts frame to all connected clients via `HTTPConnectionManager.broadcast()`
   - Sleeps for fixed interval (not "as fast as possible")

**Key Properties:**

- **Frame-Based**: Operates on complete MP3 frames only (no partials)
- **Non-Blocking**: Never blocks on buffer reads or client writes
- **Jitter Tolerant**: Fixed tick interval smooths network/system jitter
- **Oblivious to Restart State**: Output loop doesn't know about encoder restarts; `get_frame()` handles all state internally

**Integration:**

- Replaces the old "read as fast as possible" pattern
- Ensures consistent output rate and better jitter tolerance
- See Section 5.2 for complete architecture details

### 7.5 HTTP Server Thread

- Runs `serve_forever()` (or async equivalent)
- Delegates per-connection writes to `HTTPConnectionManager`
- Handles new connections and delegates to connection manager

### 7.6 Component Integration Contracts (Implementation Binding)

This section defines the **public interface of each internal component** and the **exact function calls connecting them**, so that the implementation follows directly from architecture with no guessing.

#### Explicit Class Interface Signatures

**EncoderManager**

Per NEW_ENCODER_MANAGER_CONTRACT, EncoderManager is the single, authoritative decision-maker for which audio source is used each tick (M11, M12).

```python
class EncoderManager:
    def __init__(
        self,
        pcm_buffer: FrameRingBuffer,
        mp3_buffer: Optional[FrameRingBuffer] = None,
        fallback_provider: Optional[FallbackProvider] = None,
        grace_sec: float = 5.0,  # Default 5 seconds per M8
        stall_threshold_ms: Optional[int] = None,
        backoff_schedule_ms: Optional[List[int]] = None,
        max_restarts: Optional[int] = None,
        ffmpeg_cmd: Optional[List[str]] = None,
    ) -> None: ...
    """Initialize EncoderManager with PCM buffer, MP3 buffer, and fallback provider.
    
    EncoderManager is the ONLY owner of FFmpegSupervisor (M1).
    Supervisor is never exposed to external components (M2).
    """
    
    def write_pcm(self, frame: bytes) -> None: ...
    """Write PCM frame to internal buffer. Non-blocking, validates frame size (4608 bytes)."""
    
    def next_frame(self) -> bytes: ...
    """Get next PCM frame for encoding. NEVER returns None (S7.0A, S7.0D).
    
    Per M1-M3, M6-M7: Returns exactly one PCM frame per tick:
    - Program PCM if available (M6)
    - Grace silence if within grace period (M7.1)
    - Fallback frame if grace expired (M7.2)
    
    AudioPump calls this with no arguments - EncoderManager reads from internal buffer.
    """
    
    def get_frame(self) -> Optional[bytes]: ...
    """Get next MP3 frame or silence. Returns None only at startup before first frame."""
    
    def start(self) -> None: ...
    """Start encoder process and supervisor. Initializes FFmpegSupervisor internally."""
    
    def stop(self, timeout: float = 5.0) -> None: ...
    """Stop encoder process and supervisor. Cleans up all resources."""
    
    @property
    def mp3_buffer(self) -> FrameRingBuffer: ...
    """Get MP3 output buffer (read-only access for monitoring)."""
    
    def get_state(self) -> EncoderState: ...
    """Get current encoder state (RUNNING, RESTARTING, FAILED, STOPPED)."""
    
    def get_operational_mode(self) -> str: ...
    """Get current operational mode (M30). Computed independently, not just mapping Supervisor state."""
```

**AudioPump**

Per NEW_CORE_TIMING_AND_FORMATS_CONTRACT, AudioPump is the single authoritative time source (C7.1).

```python
class AudioPump:
    def __init__(
        self,
        encoder_manager: EncoderManager,
    ) -> None: ...
    """Initialize AudioPump with encoder manager.
    
    AudioPump is the single authoritative time source (C7.1).
    All Tower subsystems operate on the global 24ms tick interval (C1.1, C1.3).
    
    AudioPump calls encoder_manager.next_frame() with no arguments.
    EncoderManager is the single routing authority (M11, M12).
    """
    
    def start(self) -> None: ...
    """Start AudioPump thread. Begins real-time PCM pumping at 24ms intervals (C1.1)."""
    
    def stop(self) -> None: ...
    """Stop AudioPump thread gracefully. Waits for thread completion."""
```

**FFmpegSupervisor**

```python
class FFmpegSupervisor:
    def __init__(
        self,
        mp3_buffer: FrameRingBuffer,
        ffmpeg_cmd: List[str],
        stall_threshold_ms: int = 2000,
        backoff_schedule_ms: Optional[List[int]] = None,
        max_restarts: int = 5,
        on_state_change: Optional[Callable[[SupervisorState], None]] = None,
    ) -> None: ...
    """Initialize FFmpeg supervisor with MP3 output buffer and configuration."""
    
    def start(self) -> None: ...
    """Start FFmpeg process and drain threads. Begins liveness monitoring."""
    
    def stop(self, timeout: float = 5.0) -> None: ...
    """Stop FFmpeg process and all threads. Cleans up resources."""
    
    def write_pcm(self, frame: bytes) -> None: ...
    """Write PCM frame to FFmpeg stdin. Non-blocking, handles broken pipe errors."""
    
    def get_stdin(self) -> Optional[BinaryIO]: ...
    """Get FFmpeg stdin pipe for direct writing (INTERNAL ONLY - used by EncoderManager.write_pcm())."""
    
    def get_state(self) -> SupervisorState: ...
    """Get current supervisor state (STARTING, RUNNING, RESTARTING, FAILED, STOPPED)."""
```

**HTTPConnectionManager**

```python
class HTTPConnectionManager:
    def __init__(self) -> None: ...
    """Initialize connection manager with empty client list."""
    
    def add_client(self, client_socket: socket.socket, client_id: str) -> None: ...
    """Add new client to broadcast list. Thread-safe."""
    
    def remove_client(self, client_id: str) -> None: ...
    """Remove client from broadcast list. Thread-safe."""
    
    def broadcast(self, data: bytes) -> None: ...
    """Broadcast data to all connected clients. Non-blocking, drops slow clients."""
```

**TowerService**

```python
class TowerService:
    def __init__(self) -> None: ...
    """Initialize Tower service. Creates all components and buffers."""
    
    def start(self) -> None: ...
    """Start Tower service. Initializes and starts all threads and processes."""
    
    def stop(self) -> None: ...
    """Stop Tower service. Gracefully shuts down all components."""
    
    def main_loop(self) -> None: ...
    """Main broadcast loop. Tick-driven MP3 frame broadcasting to HTTP clients."""
```

#### AudioPump → EncoderManager Contract

Per NEW contracts:
- **AudioPump is the single authoritative time source (C7.1)** — drives 24ms tick interval (C1.1)
- **EncoderManager is the single routing authority (M11, M12)** — decides program/grace/fallback
- AudioPump calls `encoder_manager.next_frame()` with **no arguments** (M1)
- EncoderManager reads PCM from internal buffer (populated via `write_pcm()` from upstream)
- EncoderManager applies source selection rules and returns selected PCM frame (M6, M7)
- AudioPump receives selected PCM frame and writes to encoder via `encoder_manager.write_pcm(frame)`
- Timing loop: 24ms stable metronome (C1.1)

**PCM Flow:**
1. Station writes PCM → Unix socket → `EncoderManager.write_pcm(frame)` → internal PCM buffer
2. AudioPump tick (24ms) → `EncoderManager.next_frame()` → EncoderManager reads from internal buffer
3. EncoderManager applies routing logic (M6, M7) → returns selected PCM frame
4. AudioPump receives frame → `EncoderManager.write_pcm(frame)` → forwards to supervisor

#### EncoderManager → FFmpegSupervisor Contract

- EncoderManager is the ONLY owner of FFmpegSupervisor.
- Public surface:
  - `write_pcm(frame: bytes)` → forwards PCM to supervisor input ring
  - `get_frame() -> bytes` → returns next encoded MP3 frame or silence
- Internally maintains:
  - MP3 ring buffer output (owned by EncoderManager)
  - PCM buffer is NOT owned by EncoderManager (owned by TowerService, passed to AudioPump)
- Calls supervisor.start(), supervisor.restart(), supervisor.stop()

#### FFmpegSupervisor Internal Contract

- Owns ffmpeg subprocess and drain threads
- Provides:
  - `write_pcm(frame: bytes)` → writes directly to FFmpeg stdin
  - Pushes MP3 frames into mp3_buffer (not callback-based)
- Handles liveness, restart, stderr logging

#### HTTPBroadcast Loop

- Calls `encoder_manager.get_frame()` every tick interval.
- Never checks state, never blocks, no restart awareness.

#### Final Required Wiring Summary

At startup TowerService must:

1. Create PCM ring buffer
2. Create MP3 ring buffer
3. Construct EncoderManager(pcm_buffer, mp3_buffer, supervisor_config)
4. Construct AudioPump(fallback_source, encoder_manager)
5. Construct FFmpegSupervisor inside EncoderManager
6. Start:
   - supervisor
   - audio pump thread
   - encoder drain thread
   - HTTP output tick thread

#### Acceptance Criteria

- No component references another by attribute that isn't defined in contract.
- AudioPump → EncoderManager interface is explicit.
- Supervisor lifecycle does not leak outside EncoderManager.
- Implementation must be derivable directly from the document.
- All public methods must match the interface signatures defined above.

### 7.7 Logging & Observability

All Tower components implement standardized logging per contract requirements (LOG1-LOG4).

**Log File Locations:**
- `/var/log/retrowaves/tower.log` - TowerRuntime, AudioPump, EncoderManager, PCM Ingestion, Fallback Provider
- `/var/log/retrowaves/ffmpeg.log` - FFmpegSupervisor (special case)

**Logging Properties:**
- **Non-blocking (LOG2):** Logging never blocks audio paths, tick loops, or real-time processing
- **Rotation tolerant (LOG3):** Uses `WatchedFileHandler` to automatically detect and handle external log rotation (e.g., logrotate)
- **Failure tolerant (LOG4):** Logging failures degrade silently; component operation continues even if logging fails
- **No elevated privileges:** Components do not require elevated privileges at runtime

**Implementation:**
- Each component configures its own logger with `WatchedFileHandler`
- Handler creation wrapped in exception handling for graceful degradation
- Duplicate handler prevention for module reloads
- Standard formatter: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`

See component contracts for detailed logging requirements.

### 7.8 Event System (Station → Tower WebSocket Events)

Tower implements a real-time event streaming system that receives heartbeat events from Station and broadcasts them to connected WebSocket clients.

**Event Ingestion:**
- Station sends events via HTTP POST to `/tower/events/ingest`
- Events are one-way (Station→Tower), purely observational
- Tower validates and stores events in a bounded, thread-safe buffer (1000 event capacity)
- Events are immediately broadcast to all connected WebSocket clients

**Event Types:**
- `segment_started` - New audio segment (song/intro/outro/ID) has started
- `segment_progress` - Segment playback progress updates
- `segment_finished` - Segment has finished playing
- `dj_think_started` - DJ has entered THINK phase
- `dj_think_completed` - DJ has completed THINK phase
- `station_underflow` - Station buffer underflow detected
- `station_overflow` - Station buffer overflow detected
- `station_starting_up` - Station is starting up
- `station_shutting_down` - Station is shutting down
- `now_playing` - Authoritative segment state (includes metadata: segment_type, title, artist, duration_sec, etc.)
- `dj_talking` - DJ has started talking

**WebSocket Streaming:**
- Endpoint: `/tower/events` (WebSocket upgrade)
- Real-time event delivery to all connected clients
- Non-blocking, thread-safe event fanout
- Events are not stored for historical retrieval; they are delivered immediately or dropped

**Contract Compliance:**
- Tower: T-EVENTS (reception, storage, validation)
- Tower: T-EXPOSE (WebSocket endpoints, fanout, immediate flush)
- Station: PE4 (PlayoutEngine heartbeat events)
- Station: DJ4 (DJEngine THINK lifecycle events)
- Station: OS3 (OutputSink buffer health events)

**Architectural Note:**
This maintains separation between:
- **Pure audio stream** → radio's core
- **Stateless metadata/event feed** → everything else

This aligns with professional broadcast systems (Zetta, ENCO, WideOrbit) when interfacing with companion systems.

---

## 8. Tower Lifecycle

### 8.1 on_tower_start

On service start:

1. Load configuration (host, port, bitrate, fallback mode, etc.)
2. Initialize fallback source using priority order (see Section 4.2):
   - Try MP3/WAV file if `TOWER_SILENCE_MP3_PATH` is configured
   - Fall back to tone generator if file unavailable or invalid
   - Fall back to silence if tone generator fails
3. Initialize buffers:
   - Create PCM ring buffer (FrameRingBuffer per C-RB)
   - Create MP3 ring buffer (FrameRingBuffer per C-RB)
4. Initialize components (per T-ORDER1):
   - Construct FallbackProvider (must be constructed before EncoderManager per FP7.1)
   - Construct `EncoderManager` with PCM buffer, MP3 buffer, and fallback provider (which internally creates `FFmpegSupervisor`)
   - Construct `AudioPump` with encoder_manager (AudioPump is single timing authority per C7.1)
   - Initialize `HTTPConnectionManager`
5. Start components in order (critical sequence per T-ORDER1):
   - Start Supervisor (via `encoder_manager.start()` - initializes FFmpeg process)
   - Start EncoderOutputDrain thread (via supervisor - drains FFmpeg stdout)
   - Start AudioPump thread (begins 24ms tick loop per C1.1, C7.1)
   - Start HTTP server thread (accepts client connections)
   - Start HTTP tick/broadcast thread (begins streaming MP3 frames at 24ms intervals per C1.3)
6. Begin continuous streaming

**Critical Startup Order Rationale:**

This sequence ensures:
- Buffers exist before any component tries to use them
- FFmpeg process and stdin pipe exist before AudioPump begins writing
- EncoderOutputDrain thread is ready to receive MP3 frames before encoding begins
- HTTP server is ready to accept connections before broadcast loop starts
- Eliminates edge conditions where AudioPump writes before FFmpeg stdin exists

Station may be offline at this point; Tower still streams fallback audio.

**Startup Ordering:**

- Tower can start before Station
- Tower starts independently and accepts connections immediately
- If Station starts first and tries to connect to Tower's Unix socket:
  - Station retries connection every 1 second until Tower's socket becomes available
  - Tower does NOT queue frames before Station connects
  - Once connected, frames flow immediately

### 8.2 on_live_audio_available

When Station starts feeding PCM:

- Station writes PCM frames to Unix socket → `EncoderManager.write_pcm(frame)` → internal PCM buffer
- EncoderManager detects PCM availability and transitions from grace/fallback to program (M6)
- Tower naturally transitions from fallback frames to live frames without disconnecting clients
- No explicit mode switch is required; EncoderManager handles routing automatically (M11, M12)

**Transition Behavior:**

- Transition should be seamless (no audio glitches)
- Station writes frames in unpaced bursts; AudioPump's steady pull rate (24ms per C1.1) absorbs burstiness
- Buffer (ring buffer, bounded) absorbs temporary bursts without unbounded growth
- If Station provides frames slower than expected, EncoderManager uses grace period (silence) then fallback frames (M7)
- AudioPump's consumption rate stabilizes the system regardless of Station's write pattern
- Grace resets immediately when program PCM returns (M-GRACE4)

### 8.3 on_live_audio_lost

When Station stops feeding PCM (e.g., crash, restart, intentional stop):

- PCM buffer becomes empty (no more `write_pcm()` calls from upstream)
- EncoderManager detects PCM absence within one tick (M7)
- EncoderManager applies grace period logic (M7.1): returns grace silence if `since <= GRACE_SEC`
- After grace period expires (M7.2): EncoderManager calls `fallback_provider.next_frame()` and returns fallback frame
- Tower continues streaming fallback audio seamlessly

**Detection Time:**

- Audio loss is detected within one tick (24ms per C1.1) by EncoderManager (M7)
- Grace period uses monotonic clock (M-GRACE1) for accurate timing
- This provides fast, graceful switching while absorbing timing jitter

### 8.4 on_tower_stop

When `retrowaves-tower.service` is stopped:

1. Mark Tower as stopping and prevent new HTTP connections
2. Shut down HTTP server cleanly (stop accepting new connections)
3. Close all HTTP client connections gracefully (send remaining data if possible)
4. Close FFmpeg stdin; terminate and wait for encoder process (with timeout)
5. Stop AudioPump and EncoderReader threads (set shutdown flag, wait for threads)
6. Release resources (close sockets, free buffers, etc.)

Tower is expected to be stopped rarely; it is designed for long-running operation.

**Shutdown Timeout:**

- **Maximum shutdown time:** 5 seconds
- If shutdown exceeds 5 seconds, force-kill remaining processes/threads
- Ensures clean shutdown without hanging

---

## 9. Environment & Configuration

### 9.1 Suggested Environment Variables

```bash
TOWER_HOST=0.0.0.0
TOWER_PORT=8000
TOWER_SAMPLE_RATE=48000
TOWER_CHANNELS=2
TOWER_BITRATE=128k
TOWER_DEFAULT_SOURCE=tone   # "tone", "silence", or "file"
TOWER_DEFAULT_FILE_PATH=/path/to/fallback.wav  # required if TOWER_DEFAULT_SOURCE=file
TOWER_SILENCE_MP3_PATH=/path/to/silence.wav     # optional: used as fallback source if present (WAV only)
TOWER_SOCKET_PATH=/var/run/retrowaves/pcm.sock
TOWER_BUFFER_SIZE=5        # frames in AudioInputRouter queue (~100 ms)
TOWER_FRAME_TIMEOUT_MS=50  # timeout for frame retrieval
TOWER_ENCODER_STALL_THRESHOLD_MS=2000  # encoder stall detection threshold
TOWER_ENCODER_BACKOFF_MS=1000,2000,4000,8000,10000  # encoder restart backoff schedule
TOWER_ENCODER_MAX_RESTARTS=5  # max encoder restart attempts
TOWER_MP3_BUFFER_CAPACITY_FRAMES=400  # MP3 output buffer capacity (frames, ~5 seconds)
TOWER_PCM_BUFFER_SIZE=100  # PCM input buffer size (frames, ~2 seconds)
TOWER_OUTPUT_TICK_INTERVAL_MS=15  # tick-driven output interval (~66 ticks/second)
TOWER_CLIENT_TIMEOUT_MS=250  # timeout before dropping slow clients
TOWER_SHUTDOWN_TIMEOUT=5    # seconds for graceful shutdown
TOWER_PCM_GRACE_SEC=5.0  # grace period before switching from silence to fallback (default 5 seconds per M8)
# Note: Grace period uses monotonic clock (M-GRACE1). At exactly t == GRACE_SEC, silence still applies;
# fallback applies only at t > GRACE_SEC (M-GRACE3).
TOWER_RECOVERY_RETRY_MINUTES=10  # retry encoder recovery after max restarts (default 10 minutes)
TOWER_CROSSFADE_ENABLED=0  # enable crossfade for fallback→program transitions (default 0=disabled)
TOWER_PCM_SILENCE_THRESHOLD_DB=-60  # RMS threshold for detecting silent but present PCM (default -60dB)
```

**Fallback Source Priority:**

The fallback source is selected at startup using this priority order:

1. **File** (if `TOWER_SILENCE_MP3_PATH` is set and points to a valid WAV file)
2. **Tone generator** (default, or if file unavailable/invalid)
3. **Silence** (if tone generator initialization fails)

Note: `TOWER_SILENCE_MP3_PATH` must point to a WAV file for file source to work. MP3 files are not supported by FileSource and will cause fallback to tone generator.

### 9.2 Station-to-Tower Integration

Station configuration must include:

- **Unix domain socket path:** `/var/run/retrowaves/pcm.sock`
  - Station connects to this socket to send PCM frames
  - Station retries connection every 1 second if Tower is not available at startup
- **Canonical audio format alignment:** Must match Tower expectations (C2)
  - PCM s16le, 48 kHz, 2 channels, 1152 samples per frame (24ms per C1.1, C1.2)
  - Frame size: exactly 4608 bytes (1152 samples × 2 channels × 2 bytes per sample) (C2.2)
- **Connection behavior:**
  - Station attempts connection at startup
  - If connection fails, Station retries every 1 second
  - Once connected, Station writes frames with **no timing** (unpaced, immediate writes as decoded)
  - Station writes are non-blocking; if buffer is full, frames may be dropped (per C-RB2)
  - **AudioPump is the rate limiter (C7.1):** AudioPump drives 24ms tick intervals (C1.1, C1.3)
  - AudioPump's steady consumption rate stabilizes the buffer and prevents unbounded growth
  - **EncoderManager is the routing authority (M11, M12):** Only EncoderManager decides program/grace/fallback

---

## 10. Non-Goals & Future Extensions

### 10.1 Non-Goals in this Architecture

- No THINK/DO decision-making
- No DJIntent, ticklers, or rotation logic
- No per-client stream customization (all clients get the same signal)
- No health check or status endpoints (may be added in future - see FUTURE_ENHANCEMENTS_SYSTEM.md)

### 10.2 Future Extensions (Wishlist-Backed)

These are to be captured in the Wishlist, not here:

- Standby playlist instead of a single tone/file
- HLS output, Icecast/Shoutcast compatibility, multi-format outputs
- Multi-station Tower instances (one Tower handling multiple Station inputs with separate endpoints)
- Advanced health reporting and monitoring dashboards
- Health check endpoint (`GET /health`) - See FUTURE_ENHANCEMENTS_SYSTEM.md
- Status endpoint (`GET /status`) showing current mode, client count, encoder status - See FUTURE_ENHANCEMENTS_SYSTEM.md

**Note:** Event system (WebSocket/SSE) for OBS scene switching and "Now Playing" has been implemented. See Section 7.7 for details.

---

## 11. Summary

Retrowaves Tower is the always-on transmitter for the Retrowaves ecosystem:

- It is process-isolated from Station and DJ logic
- It maintains a continuous, always-available HTTP audio stream
- It cleanly separates content decisions (Station) from transport and availability (Tower)
- It guarantees that clients (OBS, VLC, YouTube) always receive valid audio, regardless of Station state

This document defines the canonical behavior, responsibilities, and constraints for `retrowaves-tower.service`.

---

**Document:** Tower Unified Architecture (canonical)  
**Last Updated:** 2025-12-12  
**Authority:** This document supersedes prior Tower-related architecture documents.  
**Broadcast-Grade Behavior:** See Section 5.2.7 for complete broadcast-grade encoding behavior specification.

---

## IMPLEMENTATION TODO CHECKLIST

This checklist provides concrete implementation tasks derived from the architecture contracts defined in Section 7.6.

### AudioPump Implementation

- [ ] Ensure AudioPump only calls `encoder_manager.write_pcm(frame: bytes)`
- [ ] Remove any direct references to FFmpegSupervisor from AudioPump
- [ ] Verify AudioPump timing loop uses 21.333ms stable metronome
- [ ] Confirm AudioPump pulls PCM frames from ring buffer or fallback generator

### EncoderManager Implementation

- [ ] Add `write_pcm(frame: bytes)` method that forwards to supervisor
- [ ] Ensure `get_frame() -> bytes` returns next MP3 frame or silence
- [ ] Verify EncoderManager is the ONLY owner of FFmpegSupervisor
- [ ] Confirm EncoderManager maintains PCM and MP3 ring buffers internally
- [ ] Ensure supervisor lifecycle methods (start, restart, stop) are called only by EncoderManager

### FFmpegSupervisor Implementation

- [ ] Verify supervisor owns ffmpeg subprocess and drain threads
- [ ] Ensure supervisor provides `write_pcm(frame)` method (or equivalent)
- [ ] Confirm supervisor pushes MP3 frames into mp3_buffer (not callback-based)
- [ ] Verify supervisor handles liveness detection, restart logic, and stderr logging

### HTTPBroadcast Loop Implementation

- [ ] Ensure broadcast loop calls `encoder_manager.get_frame()` every tick interval
- [ ] Remove any state checks or restart awareness from broadcast loop
- [ ] Verify broadcast loop never blocks on frame retrieval
- [ ] Confirm broadcast loop operates independently of encoder state

### TowerService Wiring

- [ ] Verify TowerService creates PCM ring buffer at startup
- [ ] Verify TowerService creates MP3 ring buffer at startup
- [ ] Ensure EncoderManager is constructed with pcm_buffer, mp3_buffer, and supervisor_config
- [ ] Ensure AudioPump is constructed with fallback_source and encoder_manager (not supervisor)
- [ ] Verify FFmpegSupervisor is constructed inside EncoderManager (not in TowerService)
- [ ] Confirm startup sequence:
  - [ ] supervisor.start()
  - [ ] audio pump thread.start()
  - [ ] encoder drain thread.start()
  - [ ] HTTP output tick thread.start()

### Contract Compliance Verification

- [ ] Audit all component references to ensure no attribute access outside defined contracts
- [ ] Verify AudioPump → EncoderManager interface is explicit and documented
- [ ] Confirm supervisor lifecycle is completely encapsulated within EncoderManager
- [ ] Ensure implementation can be derived directly from architecture document without guessing
