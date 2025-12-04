# Retrowaves Tower — Phase 3 Unix Socket Contract

**Phase:** 3 (Unix Socket)  
**Status:** Contract Definition  
**Date:** 2025-01-XX

This document defines the explicit, testable contract for Phase 3 of Retrowaves Tower. Phase 3 introduces Unix Domain Socket input for live PCM frames from a writer process, implements AudioInputRouter and AudioPump components, and adds seamless fallback behavior when live PCM is unavailable.

---

## Scope

Phase 3 implements:
- ✅ Unix Domain Socket at `TOWER_SOCKET_PATH` for live PCM input
- ✅ AudioInputRouter component for managing writer connections and frame queue
- ✅ AudioPump component for coordinating between live PCM and fallback sources
- ✅ Bounded queue (size 5) with overflow handling (drop newest frame)
- ✅ Frame size validation (4096-byte boundaries) and safe discard of malformed frames
- ✅ Timeout-based fallback when no writer connected or frames unavailable
- ✅ Seamless switching between live PCM and fallback tone
- ✅ Thread-safe writer connection management (exactly one writer at a time)

**Important:** Phase 3 does NOT require Station to exist. Tower must accept a Unix socket writer, but tests will use a synthetic writer. Tower remains independent of Station code and imports.

Phase 3 does NOT implement:
- ❌ Multiple simultaneous writer connections
- ❌ Writer authentication or authorization
- ❌ Sample-rate or channel-count validation (only 4096-byte frame boundaries are enforced)
- ❌ Encoder restart logic
- ❌ Slow-client handling
- ❌ Station code references or imports (Tower remains independent)

---

## Contract Requirements

### 1. Unix Domain Socket

**1.1 Socket Creation**
- Tower must create a Unix domain socket at `TOWER_SOCKET_PATH` environment variable
- Default socket path: `/var/run/retrowaves/pcm.sock` (if `TOWER_SOCKET_PATH` not set)
- Socket must be created at Tower startup (before accepting connections)
- Socket must use `SOCK_STREAM` type (TCP-like reliable stream)
- Socket must be bound to the filesystem path
- Socket must be created with appropriate permissions (owner/group/mode)

**1.2 Socket Lifecycle**
- Socket must be created before AudioInputRouter starts accepting connections
- Socket must remain open while Tower is running
- Socket must be removed from filesystem on Tower shutdown
- Socket must handle cleanup on abnormal shutdown (signal handlers, etc.)
- Socket must not block Tower startup if socket file already exists (remove and recreate)

**1.3 Socket Listening**
- Tower must listen for incoming connections on the Unix socket
- Tower must accept connections in a non-blocking or dedicated thread manner
- Tower must not block audio threads while waiting for connections
- Tower must handle connection errors gracefully (log, continue listening)

**1.4 Socket Permissions**
- *(Non-testable, informational for deployment only)*
- Socket file should be created with appropriate permissions for writer processes to connect
- Recommended: owner `retrowaves`, group `retrowaves`, mode `660` (rw-rw----)
- Permissions should allow writer processes (running under systemd) to connect
- Note: Socket permissions are typically managed by systemd unit file, not Tower code
- Tests cannot assert owner/group without elevated privileges

---

### 2. AudioInputRouter Component

**2.1 Component Purpose**
- AudioInputRouter must manage the Unix socket connection from writer process
- AudioInputRouter must accept exactly one writer connection at a time
- AudioInputRouter must read canonical 1024-sample PCM frames (4096 bytes)
- AudioInputRouter must maintain a bounded queue of frames
- AudioInputRouter must provide `get_next_frame(timeout_ms)` method to AudioPump

**2.2 Writer Connection Management**
- AudioInputRouter must accept exactly one writer connection at a time
- If a new writer connects while another is connected, AudioInputRouter must:
  - Reject the new connection (close immediately)
  - OR disconnect the existing writer and accept the new one
  - Behavior must be consistent and documented
- AudioInputRouter must track connection state (no writer, writer connected, writer disconnected)
- AudioInputRouter must detect writer disconnection (socket close, read error, etc.)
- AudioInputRouter must handle writer disconnection gracefully (clear queue, reset state)

**2.3 Frame Reading**
- AudioInputRouter must read frames from the connected writer socket
- Each frame must be exactly `4096` bytes (1024 samples × 2 channels × 2 bytes per sample)
- AudioInputRouter must read complete frames only (no partial frame handling in queue)
- AudioInputRouter must handle socket read operations with appropriate timeouts
- AudioInputRouter must not block indefinitely on socket reads

**2.4 Bounded Queue**
- AudioInputRouter must maintain a bounded queue of size 5 frames
- Queue must be thread-safe (multiple threads may access it)
- Queue must store complete frames only (4096 bytes each)
- Queue must support `put(frame)` and `get(timeout)` operations
- Queue must be bounded (maximum 5 frames, ~100 ms of audio at 48 kHz)

**2.5 Queue Overflow Handling**
- When queue is full (5 frames) and a new frame arrives:
  - AudioInputRouter must drop the NEWEST frame (the one just received)
  - AudioInputRouter must NOT drop the oldest frame
  - AudioInputRouter must NOT block the writer thread
  - AudioInputRouter must maintain queue size at exactly 5 frames
- Dropping newest frame preserves real-time feel and keeps Tower synced to current audio
- Queue overflow must not propagate backpressure to writer:
  - Writer must be allowed to write without blocking
  - Router must always read from writer immediately
  - Newest frame must be dropped with O(1) logic
  - This prevents writer deadlocks during rapid input bursts

**2.6 Frame Integrity and Malformed Frame Handling**
- AudioInputRouter must validate frame size only (exactly 4096 bytes)
- AudioInputRouter does NOT validate sample rate, channels, or bit depth (trust-based)
- AudioInputRouter must discard incomplete frames safely
- If writer sends partial frame (< 4096 bytes):
  - AudioInputRouter must discard the partial frame
  - AudioInputRouter must NOT add partial frame to queue
  - AudioInputRouter must NOT attempt to complete the frame
  - AudioInputRouter must continue reading from socket (next frame may be valid)
- If writer sends data not aligned to 4096-byte boundaries:
  - AudioInputRouter must discard misaligned data
  - AudioInputRouter must attempt to resynchronize (skip to next 4096-byte boundary if possible)
  - AudioInputRouter must not crash or hang on misaligned data
- Frame size validation must be minimal (performance-critical path)

**2.7 get_next_frame(timeout_ms) Method**
- AudioInputRouter must provide `get_next_frame(timeout_ms) -> Optional[bytes]` method
- Method must return a complete frame (4096 bytes) if available in queue
- Method must return `None` if:
  - No writer is connected
  - Queue is empty and timeout expires
  - Writer disconnects mid-frame
  - No frame received before timeout
- Method must respect timeout parameter (milliseconds)
- Method must be thread-safe (can be called from AudioPump thread)
- Method must not block indefinitely (must respect timeout)

**2.8 Writer Disconnection Handling**
- AudioInputRouter must detect writer disconnection immediately
- On writer disconnection:
  - AudioInputRouter must clear the queue (discard all queued frames)
  - AudioInputRouter must reset connection state
  - AudioInputRouter must close the socket connection
  - AudioInputRouter must allow a new writer to connect
- Writer disconnection must not cause AudioInputRouter to crash or hang
- Writer disconnection must be detected within reasonable time (≤100 ms)

**2.9 Thread Safety**
- AudioInputRouter must be thread-safe
- Writer connection thread and AudioPump thread may access AudioInputRouter concurrently
- Queue operations must be thread-safe (use appropriate synchronization primitives)
- Connection state must be accessed atomically
- No race conditions between writer thread and AudioPump thread

---

### 3. AudioPump Component

**3.1 Component Purpose**
- AudioPump must coordinate between live PCM (AudioInputRouter) and fallback sources
- AudioPump must generate/forward exactly 1 frame every ~21.3 ms (real-time pace)
- AudioPump must write frames to FFmpeg stdin continuously
- AudioPump must run in its own dedicated thread

**3.2 Frame Acquisition Logic**
- AudioPump must attempt `AudioInputRouter.get_next_frame(timeout_ms)` first
- AudioPump must NOT wait for writer — it must always try router first, then fallback immediately if None
- If `get_next_frame()` returns a frame (not `None`):
  - AudioPump must use the live PCM frame
  - AudioPump must write the frame to FFmpeg stdin immediately
- If `get_next_frame()` returns `None`:
  - AudioPump must fall back to ToneSource (or current SourceManager source) immediately
  - AudioPump must generate a fallback frame
  - AudioPump must write the fallback frame to FFmpeg stdin
- AudioPump must never stall, block longer than timeout, or shift its pacing

**3.3 Real-Time Pacing**
- AudioPump must generate/forward exactly 1 frame every ~21.3 ms
- Frame period: `1024 samples / 48000 Hz ≈ 21.333 ms`
- AudioPump must maintain real-time pace (not faster, not slower)
- AudioPump must use appropriate timing mechanism (sleep, timer, etc.)
- AudioPump must not accumulate latency over time (drift compensation if needed)

**3.4 Fallback Behavior**
- AudioPump must fall back to ToneSource (or SourceManager current source) when:
  - No writer connected to AudioInputRouter
  - Writer disconnects mid-frame
  - Writer sends partial frames (AudioInputRouter returns None)
  - No frame received before timeout (AudioInputRouter returns None)
- Fallback must be seamless (no gaps in PCM stream to encoder)
- Fallback must occur immediately when `get_next_frame()` returns `None`
- Fallback must not interrupt Tower operation or disconnect clients

**3.5 FFmpeg stdin Writing**
- AudioPump must write frames to FFmpeg stdin continuously
- AudioPump must handle FFmpeg stdin pipe errors (broken pipe, etc.)
- AudioPump must handle FFmpeg process termination gracefully
- AudioPump must not block indefinitely on FFmpeg stdin writes
- AudioPump must maintain frame continuity (no skipped frames)

**3.6 Thread Safety**
- AudioPump must coordinate with AudioInputRouter (thread-safe queue access)
- AudioPump must coordinate with SourceManager (thread-safe source access)
- AudioPump must handle FFmpeg process lifecycle (process may be restarted by another thread)
- AudioPump must not deadlock with other threads

---

### 4. Fallback Conditions

**4.1 No Writer Connected**
- When no writer is connected to AudioInputRouter:
  - `AudioInputRouter.get_next_frame()` must return `None` immediately (or after short timeout)
  - AudioPump must use fallback source (ToneSource or SourceManager source)
  - Tower must continue streaming fallback audio seamlessly

**4.2 Writer Disconnects Mid-Frame**
- When writer disconnects while AudioInputRouter is reading a frame:
  - AudioInputRouter must detect disconnection
  - AudioInputRouter must discard the incomplete frame
  - AudioInputRouter must return `None` from `get_next_frame()`
  - AudioPump must use fallback source immediately
  - Tower must continue streaming without interruption

**4.3 Writer Sends Partial Frames**
- When writer sends a frame with < 4096 bytes:
  - AudioInputRouter must discard the partial frame
  - AudioInputRouter must return `None` from `get_next_frame()` (queue empty)
  - AudioPump must use fallback source for that frame
  - Tower must continue streaming (fallback frame fills the gap)

**4.4 No Frame Received Before Timeout**
- When `AudioInputRouter.get_next_frame(timeout_ms)` times out:
  - AudioInputRouter must return `None`
  - AudioPump must use fallback source immediately
  - Tower must continue streaming without gaps
- Timeout must be short enough to detect writer issues quickly (≤50 ms recommended)
- Timeout must be long enough to absorb timing jitter (~2-3 frame periods)

---

### 5. Seamless Switching

**5.1 Live PCM to Fallback**
- When live PCM becomes unavailable (writer disconnects, timeout, etc.):
  - Tower must switch to fallback source immediately
  - Tower must not interrupt MP3 stream output
  - Tower must not disconnect `/stream` clients
  - Tower must not cause encoder to restart
  - MP3 stream must remain continuous (no gaps)

**5.2 Fallback to Live PCM**
- When writer connects and starts sending frames:
  - AudioInputRouter must begin queuing frames
  - AudioPump must begin using live frames instead of fallback
  - Tower must transition seamlessly (no audio glitches)
  - Tower must not interrupt MP3 stream output
  - Tower must not disconnect `/stream` clients

**5.3 Transition Behavior**
- Transitions between live PCM and fallback must be seamless
- Minimal audio glitches are acceptable (MP3 decoder resynchronization)
- Tower must never produce gaps in PCM stream to encoder
- Tower must maintain continuous MP3 output at all times

---

### 6. External Behavior Compatibility

**6.1 HTTP Server Compatibility**
- `/stream` endpoint must behave identically to Phase 1 and Phase 2
- HTTP headers must remain unchanged
- MP3 stream format must remain unchanged
- Connection handling must remain unchanged
- Client disconnect behavior must remain unchanged

**6.2 Control API Compatibility**
- `/status` endpoint must continue to work (may add Unix socket status fields in future)
- `/control/source` endpoint must continue to work
- Source switching must continue to work (ToneSource, SilenceSource, FileSource)
- SourceManager must continue to function as in Phase 2

**6.3 MP3 Streaming Compatibility**
- MP3 encoding must remain identical (same FFmpeg command, same format)
- MP3 broadcasting must remain identical (same chunk size, same broadcast model)
- MP3 stream output must be continuous regardless of live PCM availability

---

### 7. Test Compatibility

**7.1 Phase 1 Test Compatibility**
- All Phase 1 tests must continue to pass
- Phase 1 behavior must remain unchanged when no writer is connected
- Phase 1 fallback tone behavior must remain unchanged

**7.2 Phase 2 Test Compatibility**
- All Phase 2 tests must continue to pass
- Phase 2 source switching must continue to work
- Phase 2 control API must continue to work
- Phase 2 SourceManager must continue to function

**7.3 Phase 3 Test Scope**
- Phase 3 tests must focus on:
  - Unix socket creation and lifecycle
  - AudioInputRouter queue behavior
  - AudioInputRouter writer connection management
  - AudioInputRouter frame integrity handling
  - AudioPump fallback behavior
  - Seamless switching between live PCM and fallback
- Phase 3 tests must NOT require Station code or imports
- Phase 3 tests must use mock writers or test fixtures

---

## Explicit Invariants

### Unix Socket Lifecycle Invariants

**I1: Socket Existence**
- Unix socket must exist at `TOWER_SOCKET_PATH` while Tower is running
- Socket must be created before AudioInputRouter accepts connections
- Socket must be removed on Tower shutdown (cleanup)

**I2: Socket Permissions**
- *(Non-testable, informational for deployment only)*
- Socket should have permissions that allow writer processes to connect
- Socket permissions are typically managed by systemd unit file, not Tower code
- Tests cannot assert owner/group without elevated privileges

**I3: Socket Listening**
- Tower must listen for connections on the Unix socket continuously
- Socket listening must not block audio threads
- Socket must accept connections in a dedicated thread or non-blocking manner

### AudioInputRouter Queue Behavior Invariants

**I4: Queue Bounds**
- Queue must never exceed 5 frames
- Queue must drop newest frame on overflow (not oldest)
- Queue must maintain size ≤ 5 at all times

**I4b: Queue Overflow Backpressure Prevention**
- Queue overflow must not propagate backpressure to writer
- Writer must be allowed to write without blocking
- Router must always read from writer immediately
- Newest frame must be dropped with O(1) logic
- This prevents writer deadlocks during rapid input bursts

**I5: Queue Thread Safety**
- Queue operations must be thread-safe
- No race conditions between writer thread and AudioPump thread
- Queue state must be consistent at all times

**I6: Frame Completeness**
- Queue must contain only complete frames (exactly 4096 bytes each)
- Partial frames must never be added to queue
- Malformed frames must be discarded before queue insertion

**I7: Queue Empty Handling**
- When queue is empty and no writer connected, `get_next_frame()` must return `None`
- When queue is empty and writer connected but timeout expires, `get_next_frame()` must return `None`
- Queue empty state must not cause AudioPump to block or crash

### Frame Integrity Rules Invariants

**I8: Frame Size Validation**
- Tower validates frame size only (exactly 4096 bytes)
- Tower does NOT validate sample rate, channels, or bit depth (trust-based)
- All frames read from writer must be exactly 4096 bytes
- Frames < 4096 bytes must be discarded (not queued)
- Frames > 4096 bytes must be handled (discard excess, or split into multiple frames)

**I9: Misaligned Frame Handling**
- Frames not aligned to 4096-byte boundaries must be discarded safely
- Misaligned frames must not cause AudioInputRouter to crash
- Misaligned frames must not corrupt queue state
- AudioInputRouter must attempt to recover from misaligned data (resynchronize to next 4096-byte boundary)

**I10: Writer Disconnection Frame Handling**
- Incomplete frames during writer disconnection must be discarded
- Queue must be cleared on writer disconnection
- Writer disconnection must not leave partial frames in queue

### Hand-off Behavior to AudioPump Invariants

**I11: get_next_frame() Return Value**
- `get_next_frame()` must return `bytes` (4096 bytes) or `None` (never partial frame)
- `get_next_frame()` must respect timeout parameter
- `get_next_frame()` must not block indefinitely

**I12: Fallback Trigger**
- AudioPump must use fallback when `get_next_frame()` returns `None`
- Fallback must occur immediately (no delay)
- Fallback must not interrupt PCM stream to encoder

**I13: Real-Time Pacing**
- AudioPump must generate/forward exactly 1 frame every ~21.3 ms
- AudioPump must maintain real-time pace (no accumulation of latency)
- AudioPump must not skip frames or produce gaps

**I14: Seamless Switching**
- Switching between live PCM and fallback must be seamless
- No gaps in PCM stream to encoder during transitions
- MP3 stream must remain continuous during transitions

**I15: AudioPump Pacing Independence**
- AudioPump runs strictly at 1024/48000 Hz period (~21.3 ms per frame)
- Timing must not depend on router, network, writer, or filesystem
- Router latency must NEVER influence AudioPump's frame cadence
- AudioPump must NOT depend on wallclock to determine source
- AudioPump must NOT wait for writer — it must always:
  - Try `router.get_next_frame(timeout)`
  - If timeout → fallback immediately
- AudioPump must NEVER:
  - Stall
  - Block longer than timeout
  - Shift its pacing
- This keeps Tower rock-solid and prevents FFmpeg from falling behind or crashing

### Writer Connection Invariants

**I16: Single Writer**
- AudioInputRouter must accept exactly one writer connection at a time
- If new writer connects while another is connected, behavior must be defined and consistent
- Writer connection state must be tracked accurately

**I17: Writer Disconnection Detection**
- Writer disconnection must be detected within reasonable time (≤100 ms)
- Writer disconnection must trigger queue clearing and state reset
- Writer disconnection must allow new writer to connect

---

## Test Mapping

Each contract requirement above maps directly to one or more test cases:

- **Section 1 (Unix Socket)** → Socket creation tests, socket lifecycle tests (permissions are non-testable, informational only)
- **Section 2 (AudioInputRouter)** → Queue behavior tests, writer connection tests, frame integrity tests, thread-safety tests
- **Section 3 (AudioPump)** → Frame acquisition tests, fallback behavior tests, real-time pacing tests, FFmpeg integration tests
- **Section 4 (Fallback Conditions)** → Fallback trigger tests, disconnection tests, timeout tests
- **Section 5 (Seamless Switching)** → Transition tests, continuity tests
- **Section 6 (Compatibility)** → Phase 1/2 compatibility tests, HTTP server tests, control API tests
- **Section 7 (Test Compatibility)** → Regression tests, integration tests
- **Invariants** → Invariant verification tests, edge case tests, stress tests

---

## Out of Scope (Explicitly Excluded)

The following features are explicitly excluded from Phase 3:

- ❌ Multiple simultaneous writer connections (only one writer at a time)
- ❌ Writer authentication or authorization
- ❌ Sample-rate or channel-count validation (only 4096-byte frame boundaries are enforced)
- ❌ Station code imports or references (Tower remains independent)
- ❌ Encoder restart logic
- ❌ Slow-client handling
- ❌ Frame resampling or format conversion (canonical format only)
- ❌ Queue size configuration (fixed at 5 frames)
- ❌ Historical frame logging or debugging endpoints
- ❌ Writer connection retry logic (writer handles retries)

---

## Success Criteria

Phase 3 is complete when:

1. ✅ Unix domain socket is created at `TOWER_SOCKET_PATH` at Tower startup
2. ✅ AudioInputRouter accepts exactly one writer connection at a time
3. ✅ AudioInputRouter reads canonical 1024-sample PCM frames (4096 bytes)
4. ✅ AudioInputRouter maintains bounded queue of size 5
5. ✅ AudioInputRouter drops newest frame on overflow
6. ✅ AudioInputRouter discards incomplete or malformed frames safely
7. ✅ AudioInputRouter returns `None` on read timeout or missing writer
8. ✅ AudioPump attempts `AudioInputRouter.get_next_frame(timeout_ms)`
9. ✅ AudioPump falls back to ToneSource (or SourceManager source) when `None` is returned
10. ✅ AudioPump generates/forwards 1 frame every ~21.3 ms
11. ✅ Fallback occurs when no writer connected, writer disconnects, partial frames, or timeout
12. ✅ Tower seamlessly switches between live PCM and fallback tone
13. ✅ External behavior (HTTP server + MP3 streaming) remains identical to Phase 1
14. ✅ All Phase 1 + Phase 2 tests still pass
15. ✅ Phase 3 tests verify Unix socket + router logic
16. ✅ All contract requirements have passing tests
17. ✅ All invariants are verified by tests

---

**Document:** Tower Phase 3 Unix Socket Contract  
**Version:** 1.0  
**Last Updated:** 2025-01-XX

