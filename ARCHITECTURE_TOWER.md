# Retrowaves Tower — Unified System Architecture

A 24/7, process-isolated, HTTP-based audio transmission service that exposes a single continuous stream for downstream clients (OBS, VLC, YouTube, etc.), independent of DJ and station lifecycle.

> **Note:**  
> Retrowaves Tower is the carrier.  
> Retrowaves Station (Appalachia Radio, etc.) is the brain that generates live PCM audio.

This is the canonical architecture document for `retrowaves-tower.service` and supersedes all previous Tower-related designs.

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
- `frame_size = 1024` samples (~21.3 ms per frame at 48 kHz)

**Live PCM Delivery Model:**

Station (producer) → unpaced writes → Unix Socket → Tower Ring Buffer → paced consumption → Encoder

| Component | Timing Responsibility |
|-----------|----------------------|
| Station | no timing — decode & write frames immediately as available |
| Tower | sole metronome — pulls one 1024-sample frame every 21.333ms |
| Fallback | provides frames only when Tower pulls and none are available |

**Important Principles:**

- **Tower is the only clock in the system.** Station writes frames into the socket with no timing, pushing decoded PCM bursts.
- **Station pushes fast; Tower pulls steady.** Tower is the rate limiter, consuming frames at exactly 48kHz → 1024-sample frames → 21.333ms.
- **Buffer must be bounded (200–500ms max recommended).** A ring buffer absorbs burstiness; underflow triggers fallback tone.
- **Buffer never grows unbounded — Tower consumption rate stabilizes the system.** Overflow drops newest or oldest depending on strategy.
- **Underflow triggers silence → tone after grace window.** If Station falls behind or stops writing, Tower must detect this and use fallback.

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

Tower selects the fallback source using the following priority order (highest to lowest):

1. **MP3/WAV File** (if `TOWER_SILENCE_MP3_PATH` is configured and exists):
   - If the file is a WAV file (`.wav` extension), Tower uses it as a file source
   - If the file is an MP3 or other format, Tower falls through to tone generator (FileSource only handles WAV files)
   - Note: To use MP3 files as fallback, they must be converted to WAV first, or MP3 support must be added to FileSource

2. **Tone Generator** (default):
   - Generates continuous PCM tone (e.g., 440 Hz sine wave)
   - Used when no file is configured, or when file source initialization fails
   - Configured via `TOWER_DEFAULT_SOURCE=tone` (default)

3. **Silence** (fallback if tone generation fails):
   - Produces continuous PCM zeros (silence)
   - Used only if tone generator initialization fails
   - Ensures Tower always has a valid source, even if tone generation encounters errors

### 4.3 Input Selection Logic

At each audio tick (exactly 21.333 ms intervals, driven by Tower's metronome):

1. Tower pulls one frame from the Station input buffer (non-blocking, short timeout ~5ms)
2. If available → use live frame
3. If not available (queue empty or timeout) → check grace period:
   - **5 second grace period before fallback**: When Station switches between MP3 tracks, there may be brief gaps in PCM data. Tower must wait 5 seconds (configurable via `TOWER_PCM_GRACE_SEC`) before switching to fallback tone. During the grace period, Tower uses silence frames to maintain continuous MP3 stream. This prevents audible tone interruptions during track transitions.
   - If within grace period (default 5 seconds): use silence frame
   - If grace period expired: generate or fetch fallback frame (tone/file)
4. Send the chosen PCM to the encoder

**Key Points:**

- Tower's consumption rate (21.333ms per frame) is the sole timing reference
- Station writes are unpaced bursts; Tower's steady pull rate stabilizes the buffer
- Grace period prevents tone blips during short gaps between tracks
- This logic ensures there is never a gap in the PCM stream feeding the encoder

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

#### 5.2.1 Dual-Buffer Architecture

The encoding subsystem uses a **dual-buffer architecture** with independent input and output queues, separated by the FFmpeg encoder process:

- **PCM Input Buffer**: Thread-safe ring buffer for PCM frames (~50-100 frames, ~1-2 seconds)
  - Pumped by AudioPump at real-time pace (source clock)
  - Non-blocking writes (drops newest if full)
  - Non-blocking reads (returns None if empty)

- **MP3 Output Buffer**: Frame-based ring buffer for MP3 frames (~400 frames, ~5 seconds depth)
  - Consumed by tick-driven broadcast loop (consumer clock)
  - Stores complete MP3 frames only (no partials)
  - Non-blocking writes (drops oldest if full)
  - Non-blocking reads (returns None if empty)

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

**Solution:** Tick-driven loop with fixed interval (15ms default, ~66 ticks/second):
- Consistent output rate (not bursty)
- Better jitter tolerance (smooths network/system delays)
- Lower CPU usage (no busy loops)
- Predictable behavior

**Output Loop:**
```python
# Tick-driven broadcast loop
tick_interval_ms = 15  # ~66 frames/second
while not shutdown:
    frame = encoder_manager.get_frame()  # Returns frame or silence_frame
    broadcast(frame)
    sleep(tick_interval_ms)  # Fixed interval, not "as fast as possible"
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

# MP3 output buffer capacity (frames) - 5 seconds @ ~66 fps = 330 frames
# Recommended: 400 frames (with headroom) for jitter tolerance
TOWER_MP3_BUFFER_CAPACITY_FRAMES=400

# PCM input buffer size (frames) - ~1-2 seconds
TOWER_PCM_BUFFER_SIZE=100

# Tick-driven output interval (milliseconds)
TOWER_OUTPUT_TICK_INTERVAL_MS=15  # ~66 ticks/second
```

**Default Values:**
- Stall Threshold: 2000ms
- Backoff Schedule: [1000, 2000, 4000, 8000, 10000]ms
- Max Restarts: 5
- MP3 Buffer Capacity: 400 frames (~5 seconds @ ~66 fps)
- PCM Buffer Size: 100 frames (~2 seconds)
- Output Tick Interval: 15ms (~66 ticks/second)

**Performance Characteristics:**
- Latency: ~5 seconds (MP3 buffer depth)
- CPU Usage: Minimal (select-based I/O, tick-driven pacing, no busy loops)
- Memory Usage: ~150KB-1.7MB (MP3 buffer, depends on frame size) + ~100KB (PCM buffer)
- Restart Time: ~1-10 seconds (depending on backoff schedule)
- Output Rate: ~66 frames/second (15ms tick interval)

For detailed troubleshooting, design rationale, and verification procedures, see the full encoding architecture documentation in `tower/docs/BROADCAST_ENCODER_ARCHITECTURE.md`.

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

### 7.1 AudioInputRouter

- Receives PCM frames from Station via Unix domain socket (`/var/run/retrowaves/pcm.sock`)
- Buffers frames in a thread-safe bounded queue (ring buffer)
- **Queue size:** 10 frames (~213 ms of audio at 48kHz)
  - Bounded size prevents unbounded growth
  - Tower's steady consumption rate (21.333ms per frame) stabilizes the buffer
  - Absorbs burstiness from Station's unpaced writes
- Provides a `get_next_frame(timeout)` method to the Tower audio pump
- Tower pulls frames at exactly 21.333ms intervals (sole metronome)
- If no frames arrive within timeout, Tower assumes Station is offline or paused and uses fallback

**Buffer Overflow Handling:**

- If the queue is full when Station tries to write:
  - **Strategy:** Drop incoming frame (newest frame is discarded)
  - Station writes are unpaced bursts; Tower's steady pull rate prevents sustained overflow
  - Station stays non-blocking; Tower maintains continuous audio flow
  - Buffer never grows unbounded — Tower consumption rate stabilizes the system

**Buffer Underflow Handling:**

- If the queue is empty when Tower tries to read:
  - Tower uses fallback frame (already specified in 4.3)
  - Underflow triggers silence → tone after grace window (default 5 seconds)

**Partial Frame Handling:**

- If Station crashes mid-write, Tower may read an incomplete PCM frame
- Tower discards any partial frames and falls back to fallback audio for that tick
- This ensures continuous audio output even during Station failures

### 7.2 FallbackGenerator

- Generates PCM frames in the canonical audio format
- **Current implementation:** tone generator (e.g., 440 Hz sine wave)
- **Future implementation:** looped PCM from a pre-decoded standby asset
  - **Loading strategy:** Load standby assets at Tower startup
  - **Pre-processing:** Pre-decode MP3 → PCM at startup and cache in memory
  - **Looping:** Loop cached PCM frames during fallback mode
  - **Fallback:** If asset is missing or fails to load, use tone generator

**Source Selection Priority:**

The fallback source is selected at Tower startup using the following priority order:

1. **File Source** (if `TOWER_SILENCE_MP3_PATH` is set and points to a valid WAV file):
   - Tower attempts to use the file as a file source
   - If the file is not a WAV file or initialization fails, falls through to tone generator

2. **Tone Generator** (default):
   - Generates continuous PCM tone (440 Hz sine wave by default)
   - Used when no file is configured or file source initialization fails
   - Configured via `TOWER_DEFAULT_SOURCE=tone`

3. **Silence Source** (last resort):
   - Produces continuous PCM zeros
   - Used only if tone generator initialization fails
   - Ensures Tower always has a valid source, even in error conditions

This priority order ensures Tower always has a valid fallback source, with graceful degradation from file → tone → silence.

### 7.3 AudioPump

Runs in its own thread. **Tower's sole metronome — the only clock in the system.**

**Loop (exactly 21.333ms per iteration, using absolute clock timing):**

1. Pull live PCM from `AudioInputRouter` with short timeout (~5ms, non-blocking)
2. If none available:
   - Check grace period: if within grace window, use silence frame
   - If grace period expired, get fallback frame from `FallbackGenerator`
3. Write PCM bytes into FFmpeg stdin
4. Handle FFmpeg stdin errors (broken pipe, etc.) and trigger encoder restart if needed
5. **Sleep for remaining time in 21.333ms period** (absolute clock timing prevents drift)

**Timing Model:**

- Uses absolute clock timing (`next_frame_time += FRAME_DURATION`) to prevent cumulative drift
- If loop falls behind schedule, resyncs clock instead of accumulating delay
- Tower is the rate limiter: consumes frames at exactly 48kHz → 1024-sample frames → 21.333ms
- Station pushes fast (unpaced bursts); Tower pulls steady (metronome)

**Thread Safety:**

- Must coordinate with `AudioInputRouter` (thread-safe queue)
- Must handle FFmpeg process lifecycle (process may be restarted by another thread)

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

---

## 8. Tower Lifecycle

### 8.1 on_tower_start

On service start:

1. Load configuration (host, port, bitrate, fallback mode, etc.)
2. Initialize fallback source using priority order (see Section 4.2):
   - Try MP3/WAV file if `TOWER_SILENCE_MP3_PATH` is configured
   - Fall back to tone generator if file unavailable or invalid
   - Fall back to silence if tone generator fails
3. Initialize `AudioInputRouter`, `FallbackGenerator`, and `HTTPConnectionManager`
4. Start FFmpeg encoder process
5. Start:
   - AudioPump thread
   - EncoderReader thread
   - HTTP server thread
6. Begin continuous streaming

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

- `AudioInputRouter` begins returning live frames
- Tower naturally transitions from fallback frames to live frames without disconnecting clients
- No explicit mode switch is required; mode is implied by presence/absence of live frames

**Transition Behavior:**

- Transition should be seamless (no audio glitches)
- Station writes frames in unpaced bursts; Tower's steady pull rate (21.333ms) absorbs burstiness
- Buffer (ring buffer, bounded) absorbs temporary bursts without unbounded growth
- If Station provides frames slower than expected, Tower uses grace period (silence) then fallback frames
- Tower's consumption rate stabilizes the system regardless of Station's write pattern

### 8.3 on_live_audio_lost

When Station stops feeding PCM (e.g., crash, restart, intentional stop):

- `AudioInputRouter` times out retrieving frames
- `AudioPump` falls back to `FallbackGenerator` frames
- Tower continues streaming fallback audio seamlessly

**Detection Time:**

- Audio loss is detected within 50 ms (as specified in Section 4.3)
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
- **Canonical audio format alignment:** Must match Tower expectations
  - PCM s16le, 48 kHz, 2 channels, 1024 samples per frame
- **Connection behavior:**
  - Station attempts connection at startup
  - If connection fails, Station retries every 1 second
  - Once connected, Station writes frames with **no timing** (unpaced, immediate writes as decoded)
  - Station writes are non-blocking; if buffer is full, frames may be dropped
  - **Tower is the rate limiter:** Tower pulls frames at exactly 21.333ms intervals (sole metronome)
  - Tower's steady consumption rate stabilizes the buffer and prevents unbounded growth

---

## 10. Non-Goals & Future Extensions

### 10.1 Non-Goals in this Architecture

- No THINK/DO decision-making
- No DJIntent, ticklers, or rotation logic
- No per-client stream customization (all clients get the same signal)
- No metadata/event side-channel (handled by a separate Events service in the future)
- No health check or status endpoints (may be added in future)
- No logging/monitoring integration (may be added in future)

### 10.2 Future Extensions (Wishlist-Backed)

These are to be captured in the Wishlist, not here:

- Standby playlist instead of a single tone/file
- HLS output, Icecast/Shoutcast compatibility, multi-format outputs
- Dedicated metadata/event side-channel (WebSocket/SSE) for OBS scene switching and "Now Playing"
- Multi-station Tower instances (one Tower handling multiple Station inputs with separate endpoints)
- Advanced health reporting and monitoring dashboards
- Health check endpoint (`GET /health`)
- Status endpoint (`GET /status`) showing current mode, client count, encoder status

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
**Last Updated:** 2025-12-03  
**Authority:** This document supersedes prior Tower-related architecture documents.
