# Broadcast-Grade Encoding Architecture (v2)

## Core Invariant

**MP3 output must be smooth and continuous regardless of input, timing, or encoder health.**

This document describes the production-quality audio encoding subsystem for Retrowaves Tower. The architecture is designed to eliminate silent failures, ensure frame-aligned MP3 output, and provide jitter-tolerant streaming with smooth encoder restarts.

---

## Architecture Overview

The encoding subsystem uses a **dual-buffer architecture** with independent input and output queues, separated by the FFmpeg encoder process. This design ensures that:

1. **Input timing** (PCM pump) operates independently from **output timing** (HTTP broadcast)
2. **MP3 frames** are packetized correctly (no arbitrary byte boundaries)
3. **Output pacing** is tick-driven and jitter-tolerant
4. **Encoder restarts** do not cause output discontinuities
5. **Buffer depth** provides sufficient headroom for network jitter and encoder delays

---

## API Invariants

### Frame-Based Semantics

**Critical Invariant:** Everything inside the encoder subsystem operates on **complete MP3 frames only** – no partials.

- **MP3Packetizer**: Yields complete frames (fixed-size after first header parse)
- **FrameRingBuffer**: Stores complete frames only (`push_frame()` / `pop_frame()`)
- **EncoderManager.get_frame()**: Returns one complete frame or silence frame
- **Socket-Level Joining**: Multiple frames can be joined only at the very edge (when writing to socket)

This ensures:
- No frame splitting at arbitrary byte boundaries
- Clean semantics throughout the pipeline
- Simpler logic (no partial frame handling)
- Frame boundaries preserved end-to-end

### Output Loop Oblivious to Restart State

**Critical Invariant:** The tick-driven output loop is **completely oblivious** to encoder restart state.

- Output loop just calls `encoder_manager.get_frame()` every tick
- `get_frame()` handles all state internally:
  - If buffer has frames → return real frame
  - If buffer empty → return silence frame
  - No state checks needed in output loop
- Restart state transitions are invisible to output path
- Buffer is **NOT cleared** during restart (only on full failure after max restarts)

This ensures:
- No jitter loops from state transitions
- Smooth transitions (buffer → silence → real)
- Simpler output loop code
- Predictable behavior

---

## Architecture Components

### 1. EncoderManager
**Location:** `tower/encoder_manager.py`

Manages FFmpeg encoder process lifecycle with:
- **Stall Detection**: Monitors encoder output for stalls (0 bytes for N milliseconds)
- **Async Restart**: Restarts encoder in background without interrupting playback
- **State Management**: RUNNING, RESTARTING, FAILED, STOPPED states
- **Exponential Backoff**: Configurable restart delays
- **Smooth Restart Flow**: Keeps streaming buffer content until empty, then silence filler, then smooth blend

**Key Methods:**
- `start()`: Start encoder and monitoring
- `write_pcm(data)`: Fire-and-forget PCM writes (non-blocking, independent clock)
- `get_frame()`: Returns one complete MP3 frame or silence frame if underflow (tick-driven)
- `stop()`: Graceful shutdown

### 2. Dual-Buffer Architecture

#### 2.1 PCM Input Buffer
**Location:** `tower/audio/ring_buffer.py` (PCM-specific instance)

Thread-safe ring buffer for PCM frames:
- **Non-Blocking Write**: Drops newest frame if full (never blocks)
- **Non-Blocking Read**: Returns None if empty (caller handles underflow)
- **Size**: Configurable, typically 50-100 frames (~1-2 seconds)
- **Thread-Safe**: Uses RLock for concurrent access
- **Independent Clock**: Pumped by AudioPump at real-time pace (source clock)

**Key Methods:**
- `push(frame)`: Write PCM frame (non-blocking, drops if full)
- `pop()`: Pop single frame (non-blocking, returns None if empty)
- `clear()`: Clear all frames

#### 2.2 MP3 Output Buffer
**Location:** `tower/audio/ring_buffer.py` (FrameRingBuffer class)

Thread-safe **frame-based** ring buffer for MP3 frames:
- **Frame-Based Semantics**: Stores complete MP3 frames, not raw bytes
- **Non-Blocking Write**: Drops oldest frame if full (never blocks)
- **Non-Blocking Read**: Returns None if empty (caller handles underflow)
- **Capacity**: Measured in frames, derived from target depth (5 seconds)
  - At ~66 frames/second (15ms tick interval): 5s × 66 fps ≈ 330 frames
  - Recommended: 400 frames (with headroom) for network jitter tolerance
  - Typical frame size: ~384-4176 bytes (MPEG-1 Layer III, CBR)
  - Total buffer size: ~150KB-1.7MB depending on frame size
- **Thread-Safe**: Uses RLock for concurrent access
- **Independent Clock**: Consumed by tick-driven broadcast loop (consumer clock)

**Key Methods:**
- `push_frame(frame: bytes)`: Write complete MP3 frame (non-blocking, drops oldest if full)
- `pop_frame() -> Optional[bytes]`: Pop one complete MP3 frame (non-blocking, returns None if empty)
- `clear()`: Clear all frames
- `stats()`: Get buffer statistics (capacity, size, total_writes, total_drops)

**Why Frame-Based?**
- **Invariant**: Everything inside encoder subsystem is "frame, frame, frame" – no partials
- **Clean Semantics**: Frame boundaries are preserved throughout the pipeline
- **Simpler Logic**: No need to accumulate bytes or handle partial frames
- **Socket-Level Joining**: Multiple frames can be joined only at the very edge (when writing to socket)

**Why Large Buffer?**
- Small buffers (<100KB) lead to oscillation during encoder restarts
- 5-second depth provides headroom for:
  - Network jitter (client connection delays)
  - Encoder restart delays (1-10 seconds)
  - FFmpeg processing latency
  - System scheduling delays

### 3. MP3Packetizer
**Location:** `tower/audio/mp3_packetizer.py` (new component)

Frame-aligned MP3 packetizer that yields complete MP3 frames:

**Problem:** Arbitrary byte accumulation (e.g., `read(8192)`) can split MP3 frames at non-frame boundaries, causing:
- Audio warble/distortion
- Decoder sync issues
- Client playback problems

**Solution:** `MP3Packetizer` accumulates raw bytes and yields only complete MP3 frames. For a fixed encoder profile (MPEG-1 Layer III, CBR, known bitrate/sample rate), we can simplify by:
1. Parsing the first frame header to compute frame size
2. Treating every subsequent frame as fixed-size
3. Walking forward through the byte stream

**MP3 Frame Sync Word:**
- Sync word is **0xFF + 3 MSB bits set in next byte** (0xE0 mask)
- Not just 0xFB/0xFA – the sync pattern is: `b1 == 0xFF and (b2 & 0xE0 == 0xE0)`
- This works for all MPEG versions and layers

**Simplified Approach (Fixed Profile):**
Since our FFmpeg command is fixed (MPEG-1 Layer III, CBR, 128kbps, 44.1kHz or 48kHz), we can:
1. Find first sync word (0xFF + 0xE0 mask)
2. Parse header to compute frame size: `frame_size = 144 * bitrate / sample_rate + padding`
3. Treat all frames as fixed-size and slice the buffer

```python
class MP3Packetizer:
    def __init__(self, expected_bitrate_kbps: int = 128, sample_rate: int = 44100):
        self._buffer = bytearray()
        self._frame_size: Optional[int] = None  # Computed from first header
        self._expected_bitrate_kbps = expected_bitrate_kbps
        self._sample_rate = sample_rate
    
    def accumulate(self, data: bytes) -> Iterator[bytes]:
        """
        Feed raw MP3 bytes; yields complete frame-sized chunks.
        
        Assumes constant frame size once first frame is parsed.
        This is valid for CBR encoding with fixed profile.
        """
```

**Key Features:**
- **Sync Word Detection**: `b1 == 0xFF and (b2 & 0xE0 == 0xE0)` (not just FB/FA)
- **Fixed Frame Size**: After parsing first header, all frames are same size (CBR assumption)
- **Accumulation Buffer**: Buffers partial frames until complete
- **Thread-Safe**: Safe for use in drain thread
- **Simplified Logic**: No need for full MPEG header parsing after first frame

**Integration:**
- EncoderOutputDrainThread accumulates raw bytes from FFmpeg stdout
- MP3Packetizer.accumulate() yields complete frames (fixed-size after first header)
- Complete frames are pushed to MP3 frame buffer via `push_frame()`
- Broadcast loop pops complete frames via `pop_frame()` (not arbitrary byte chunks)

### 4. EncoderOutputDrainThread
**Location:** `tower/encoder_manager.py` (class within EncoderManager)

Dedicated thread that continuously drains encoder stdout:
- **Continuous Draining**: Reads MP3 bytes from FFmpeg stdout as fast as possible
- **Stall Detection**: Detects when encoder is running but not producing data
- **Frame-Aligned Output**: Feeds complete MP3 frames to ring buffer via MP3Packetizer
- **Non-Blocking Output**: Never blocks broadcast loop
- **Select-Based I/O**: Uses `select()` with timeout for efficient polling

**Stall Detection Logic:**
- Tracks last data timestamp
- If 0 bytes received for `stall_threshold_ms` → triggers restart
- Default threshold: 2000ms (configurable via `TOWER_ENCODER_STALL_THRESHOLD_MS`)

**Frame Alignment:**
```python
# Drain thread pseudocode
packetizer = MP3Packetizer(expected_bitrate_kbps=128, sample_rate=44100)
while not shutdown:
    raw_bytes = encoder.stdout.read(1024)  # Read raw bytes
    for complete_frame in packetizer.accumulate(raw_bytes):
        mp3_buffer.push_frame(complete_frame)  # Push complete frames only
```

### 5. Tick-Driven Output Pacing
**Location:** `tower/service.py` (`_encoder_reader_loop`)

Jitter-tolerant output pacing using tick-driven loop:

**Problem:** "Read as fast as possible" causes:
- CPU spinning
- Inconsistent output rate
- Buffer oscillation
- Poor jitter tolerance

**Solution:** Tick-driven loop with fixed interval:

```python
# Tick-driven broadcast loop
tick_interval_ms = 15  # ~66 frames/second at 128kbps
while not shutdown:
    frame = encoder_manager.get_frame()  # Returns frame or silence_frame
    if frame:
        broadcast(frame)  # May optionally batch multiple frames before writing
    
    sleep(tick_interval_ms)  # Fixed interval, not "as fast as possible"
```

**Optional Mini-Batching:**
To reduce syscalls, you can batch 2-3 frames per tick:
```python
# Mini-batching 2-3 frames per write
batch_frames = []
frames_per_tick = 3
for _ in range(frames_per_tick):
    batch_frames.append(encoder_manager.get_frame())
broadcast(b"".join(batch_frames))  # Join frames only at socket edge
```

**Key Features:**
- **Fixed Tick Interval**: 15ms (configurable, ~66 ticks/second)
- **Frame-Based API**: `get_frame()` returns one complete MP3 frame or silence frame
- **Underflow Handling**: Returns pre-built silence frame if buffer empty
- **Jitter Tolerant**: Fixed interval smooths out network/system jitter
- **Non-Blocking**: Never blocks on buffer reads
- **Socket-Level Joining**: Multiple frames can be joined only when writing to socket

**Why Tick-Driven?**
- Consistent output rate (not bursty)
- Better jitter tolerance (smooths network delays)
- Lower CPU usage (no busy loops)
- Predictable behavior (easier to debug)

### 6. PCM Input (AudioPump)
**Location:** `tower/audio_pump.py` (existing)

Continues writing PCM chunks to encoder stdin:
- **Fire-and-Forget**: Non-blocking writes, frames dropped if buffer full
- **Independent Timing**: Does NOT depend on encoder health
- **Real-Time**: Maintains absolute time-based pacing (source clock)
- **Independent Queue**: PCM buffer operates independently from MP3 buffer

---

## Data Flow

```
┌─────────────────┐
│   AudioPump     │ (Source Clock: Real-time paced)
│  (PCM Writer)   │
└────────┬────────┘
         │ PCM frames (non-blocking)
         ↓
┌─────────────────┐
│  PCM RingBuffer │ (Input Buffer)
│   ~50-100 frames│
└────────┬────────┘
         │ PCM frames (non-blocking)
         ↓
┌─────────────────┐
│  FFmpeg Process │
│  (Encoder)      │
└────────┬────────┘
         │ MP3 bytes (raw, variable length)
         ↓
┌─────────────────┐
│EncoderOutput    │ (Drain Thread)
│DrainThread      │
└────────┬────────┘
         │ Complete MP3 frames (frame-aligned)
         ↓
┌─────────────────┐
│  MP3Packetizer  │ (Frame Alignment)
└────────┬────────┘
         │ Complete MP3 frames
         ↓
┌─────────────────┐
│  MP3 RingBuffer │ (Output Buffer: Frame-based, ~400 frames = 5s depth)
│  FrameRingBuffer│
└────────┬────────┘
         │ Complete MP3 frames (tick-driven)
         ↓
┌─────────────────┐
│Tick-Driven Loop │ (Consumer Clock: Fixed interval)
│  (~15ms ticks)  │
└────────┬────────┘
         │ MP3 frames (or silence)
         ↓
┌─────────────────┐
│HTTPConnection   │
│Manager.broadcast│
└────────┬────────┘
         │
         ↓
    HTTP Clients
```

**Key Points:**
- **Two Independent Clocks**: PCM pump (source) and MP3 broadcast (consumer)
- **Two Independent Buffers**: PCM buffer and MP3 buffer (separate queues)
- **Frame Alignment**: MP3Packetizer ensures complete frames only
- **Tick-Driven Output**: Fixed interval, not "as fast as possible"

---

## Stall Detection

The system detects encoder stalls when:
1. Encoder process is still running (`is_running() == True`)
2. No data received from stdout for `stall_threshold_ms` milliseconds
3. Drain thread detects stall and calls `_handle_stall()`
4. EncoderManager triggers async restart

**Configuration:**
- Environment variable: `TOWER_ENCODER_STALL_THRESHOLD_MS`
- Default: 2000ms (2 seconds)
- Recommended: 1000-5000ms depending on bitrate and buffer size

---

## Restart Flow

When encoder fails or stalls:

### Phase 1: Detection
1. **Detection**: Monitor thread or drain thread detects failure/stall
2. **State Transition**: `RUNNING` → `RESTARTING`
3. **Drain Thread Stop**: Stop draining old encoder stdout
4. **Critical**: Do NOT clear `_mp3_buffer` during restart

### Phase 2: Smooth Transition (Critical)
5. **Continue Streaming Buffer**: Keep streaming MP3 buffer content until empty
   - Output loop is **completely oblivious** to restart state
   - Output loop just keeps calling `get_frame()` (which pops from buffer)
   - Buffer acts as bridge between old and new encoder
   - Output continues smoothly from buffer

6. **Silence Filler**: When buffer empties, `get_frame()` returns silence frame
   - Only after buffer is completely drained
   - Maintains continuous output (no gaps)
   - No state checks needed in output loop

### Phase 3: Recovery
7. **Async Restart**: Restart thread waits for backoff delay
8. **Encoder Restart**: New encoder process started
9. **Drain Thread Start**: New drain thread starts for new encoder
10. **Buffer Refill**: New MP3 data fills ring buffer (via MP3Packetizer)
11. **Smooth Blend**: When buffer refills, `get_frame()` automatically returns real frames
    - No bounce-back jitter loop
    - Smooth transition from silence → real audio
    - Output loop doesn't need to know about state changes

**Key Points:**
- Restart never blocks output path
- **Buffer is NOT cleared** during restart (only on full failure after max restarts)
- Output loop is oblivious to restart state (just calls `get_frame()`)
- Playback continues during restart (from buffer, then silence)
- Buffer acts as bridge between old and new encoder
- Silence MP3 used only after buffer empties (via `get_frame()` fallback)
- Smooth blend when encoder resumes (no instant flip, no jitter loop)

**Why This Matters:**
- **Instant flip** causes audible glitches and jitter loops
- **Smooth transition** maintains continuous output
- **Buffer-first** approach minimizes silence duration

---

## Configuration

### Environment Variables

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

### Default Values

- **Stall Threshold**: 2000ms
- **Backoff Schedule**: [1000, 2000, 4000, 8000, 10000]ms
- **Max Restarts**: 5
- **MP3 Buffer Capacity**: 400 frames (~5 seconds @ ~66 fps, with headroom)
- **PCM Buffer Size**: 100 frames (~2 seconds)
- **Output Tick Interval**: 15ms (~66 ticks/second)

---

## Verification

### Manual Testing

1. **Normal Operation:**
   ```bash
   # Start Tower
   ./start.sh
   
   # Check logs for encoder startup
   journalctl -u retrowaves-tower -f | grep -i encoder
   ```

2. **Stall Detection Test:**
   ```bash
   # Suspend FFmpeg process (simulates stall)
   pkill -STOP ffmpeg
   
   # Wait 2+ seconds
   # Check logs for stall detection and restart
   journalctl -u retrowaves-tower -f | grep -i stall
   ```

3. **Encoder Crash Test:**
   ```bash
   # Kill FFmpeg process (simulates crash)
   pkill -9 ffmpeg
   
   # Check logs for crash detection and restart
   journalctl -u retrowaves-tower -f | grep -i "encoder.*exit"
   ```

4. **Buffer Underflow Test:**
   ```bash
   # Stop encoder for extended period
   # Verify smooth transition: buffer → silence → real audio
   # Check logs for smooth blend messages
   ```

5. **Frame Alignment Test:**
   ```bash
   # Capture MP3 stream and verify frame boundaries
   # Use MP3 frame parser to check for split frames
   # Should see no warble/distortion
   ```

### Expected Behavior

✅ **Audio never goes permanently silent**
- Buffer provides continuous output during restarts
- Silence MP3 used only after buffer empties
- Encoder restarts automatically

✅ **Temporary dropouts handled gracefully**
- Buffer plays through during encoder restart
- Silence MP3 fills gaps if buffer empties
- Smooth return when encoder recovers (no instant flip)

✅ **Stream clients see uninterrupted output**
- HTTP broadcast loop never blocks
- MP3 frames always available (real or silent)
- No connection drops during encoder restarts

✅ **Encoder can be killed and recovers**
- Manual kill triggers restart
- System recovers automatically
- Playback continues during recovery (buffer → silence → real)

✅ **Frame-aligned output**
- No warble/distortion from split frames
- Complete MP3 frames only
- Smooth decoder sync

✅ **Jitter-tolerant output**
- Fixed tick interval (not bursty)
- Smooths network/system jitter
- Consistent output rate

---

## Performance Characteristics

- **Latency**: ~5 seconds (MP3 buffer depth)
- **CPU Usage**: Minimal (select-based I/O, tick-driven pacing, no busy loops)
- **Memory Usage**: ~150KB-1.7MB (MP3 buffer, depends on frame size) + ~100KB (PCM buffer)
- **Restart Time**: ~1-10 seconds (depending on backoff schedule)
- **Stall Detection**: <2 seconds (configurable)
- **Output Rate**: ~66 frames/second (15ms tick interval)

---

## Troubleshooting

### Encoder Keeps Restarting

**Symptoms:** Logs show repeated restart attempts

**Possible Causes:**
1. FFmpeg not installed or not in PATH
2. FFmpeg command incorrect
3. System resource limits (file descriptors, memory)
4. Stall threshold too low

**Solutions:**
- Check FFmpeg installation: `which ffmpeg`
- Check system logs: `journalctl -u retrowaves-tower`
- Increase stall threshold: `TOWER_ENCODER_STALL_THRESHOLD_MS=5000`
- Check system limits: `ulimit -a`

### Audio Goes Silent

**Symptoms:** No audio output, buffer empty

**Possible Causes:**
1. Encoder in FAILED state (max restarts exceeded)
2. Buffer underflow (encoder not producing data)
3. Drain thread not running
4. MP3Packetizer stuck (partial frame accumulation)

**Solutions:**
- Check encoder state: Look for "FAILED" in logs
- Check buffer stats: Monitor ring buffer utilization
- Check drain thread: Verify thread is running
- Check packetizer: Verify frame alignment
- Restart Tower service: `systemctl restart retrowaves-tower`

### Audio Warble/Distortion

**Symptoms:** Audio sounds distorted, warble, or choppy

**Possible Causes:**
1. MP3 frames split at non-frame boundaries
2. MP3Packetizer not working correctly (sync word detection failed)
3. Buffer contains partial frames (should never happen with frame-based buffer)
4. Frame size computation incorrect (wrong bitrate/sample rate)

**Solutions:**
- Verify MP3Packetizer is enabled and sync word detection works
- Check frame alignment in logs (should see fixed frame size after first header)
- Verify complete frames in buffer (frame-based buffer ensures no partials)
- Verify encoder profile matches packetizer assumptions (MPEG-1 Layer III, CBR)
- Test with frame parser tool

### High CPU Usage

**Symptoms:** High CPU usage, system slow

**Possible Causes:**
1. Busy loop in drain thread (shouldn't happen with select)
2. Encoder restart loop
3. Ring buffer contention
4. Tick interval too short (busy loop)

**Solutions:**
- Check logs for restart loops
- Monitor thread activity: `top -H -p <tower_pid>`
- Check buffer stats for excessive drops
- Increase tick interval: `TOWER_OUTPUT_TICK_INTERVAL_MS=20`

### Buffer Oscillation

**Symptoms:** Buffer fills and empties repeatedly

**Possible Causes:**
1. Buffer capacity too small (<300 frames)
2. Output rate too fast (tick interval too short)
3. Encoder restart loop

**Solutions:**
- Increase MP3 buffer capacity: `TOWER_MP3_BUFFER_CAPACITY_FRAMES=500`
- Increase tick interval: `TOWER_OUTPUT_TICK_INTERVAL_MS=20`
- Check encoder stability (no restart loops)

---

## Integration Notes

### Existing Code Compatibility

The new architecture maintains backward compatibility:
- `EncoderManager.write_pcm()`: Same interface, still non-blocking
- `EncoderManager.get_frame()`: **New API** - returns one complete MP3 frame or silence frame (replaces `get_chunk(size)`)
- `EncoderManager` state API: Unchanged
- HTTP broadcast loop: Uses tick-driven pacing with `get_frame()` (replaces "read as fast as possible")

### Migration

**Required Changes:**
1. Implement `MP3Packetizer` class (simplified for fixed CBR profile)
2. Implement `FrameRingBuffer` class (frame-based, not byte-based)
3. Integrate packetizer in `EncoderOutputDrainThread` (yields frames to `push_frame()`)
4. Replace `get_chunk(size)` with `get_frame()` (returns one frame or silence)
5. Update broadcast loop to use tick-driven pacing with `get_frame()`
6. Set MP3 buffer capacity to ~400 frames (5-second depth)
7. Update restart flow: **Do NOT clear buffer** during restart (only on full failure)

**Backward Compatibility:**
- Existing HTTP clients: No changes required
- Existing configuration: Defaults work, but recommend buffer size increase
- Existing monitoring: Metrics unchanged

---

## Design Rationale

### Why Split Buffers?

**Problem:** Single buffer couples input and output timing, causing:
- Input delays affect output
- Output backpressure affects input
- Timing dependencies create jitter

**Solution:** Separate PCM and MP3 buffers with independent clocks:
- PCM pump operates at source clock (real-time)
- MP3 broadcast operates at consumer clock (tick-driven)
- No coupling between input and output

### Why Frame Alignment?

**Problem:** Arbitrary byte accumulation splits MP3 frames:
- Audio warble/distortion
- Decoder sync issues
- Client playback problems

**Solution:** MP3Packetizer ensures complete frames only:
- Detects sync word: `0xFF + (next_byte & 0xE0 == 0xE0)` (not just FB/FA)
- Parses first frame header to compute fixed frame size (CBR assumption)
- Yields only complete frames (fixed-size after first header)
- Frame-based buffer (`FrameRingBuffer`) ensures no partials in pipeline
- Eliminates warble/distortion

### Why Tick-Driven Pacing?

**Problem:** "Read as fast as possible" causes:
- CPU spinning
- Inconsistent output rate
- Buffer oscillation
- Poor jitter tolerance

**Solution:** Fixed tick interval:
- Consistent output rate
- Better jitter tolerance
- Lower CPU usage
- Predictable behavior

### Why Large Buffer?

**Problem:** Small buffers (<100KB) cause:
- Oscillation during restarts
- Frequent underflows
- Poor jitter tolerance

**Solution:** 5-second depth (~400 frames):
- Headroom for network jitter
- Headroom for encoder restarts
- Smooth transitions
- No oscillation
- Frame-based capacity (not byte-based) makes sizing predictable

### Why Smooth Restart?

**Problem:** Instant flip on restart causes:
- Audible glitches
- Jitter loops
- Poor user experience

**Solution:** Smooth transition:
- **Do NOT clear buffer** during restart (only on full failure)
- Output loop oblivious to restart state (just calls `get_frame()`)
- Keep streaming buffer until empty (via `pop_frame()`)
- Then silence filler (via `get_frame()` fallback)
- Then smooth blend when encoder resumes (buffer refills automatically)
- No instant flip, no jitter loop, no state checks in output path

---

## References

- **Icecast**: Similar architecture for streaming audio
- **Liquidsoap**: Uses similar drain thread pattern
- **TV/Radio Automation**: Professional playout systems use similar patterns
- **MP3 Frame Format**: ISO/IEC 11172-3 (MPEG-1 Audio Layer III)
- **Jitter Buffers**: VoIP systems use similar tick-driven pacing

---

## Version History

- **v2.0** (Current): Dual-buffer architecture, frame alignment, tick-driven pacing, smooth restarts
- **v1.0** (Previous): Single buffer, arbitrary byte accumulation, "read as fast as possible", instant restart flip
