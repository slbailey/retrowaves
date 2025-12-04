# Retrowaves Tower — Phase 1 Minimal Contract

**Phase:** 1 (Minimal)  
**Status:** Contract Definition  
**Date:** 2025-01-XX

This document defines the explicit, testable contract for Phase 1 of Retrowaves Tower. Phase 1 implements the minimal viable streaming service with a fallback tone generator and HTTP streaming endpoint.

---

## Scope

Phase 1 implements:
- ✅ 24/7 process lifecycle
- ✅ HTTP server with `/stream` endpoint
- ✅ Continuous MP3 streaming via FFmpeg
- ✅ Fallback PCM tone generator as sole audio source
- ✅ MP3 encoding using canonical FFmpeg command
- ✅ Multi-client broadcast of encoded MP3 bytes
- ✅ Clean client disconnect handling (non-blocking)

Phase 1 does NOT implement:
- ❌ Slow-client handling (timeouts, dropping slow clients)
- ❌ AudioPump–AudioInputRouter architecture
- ❌ Station integration (Unix socket, live PCM input)
- ❌ Encoder restart logic
- ❌ Station code references or imports

---

## Contract Requirements

### 1. Process Lifecycle

**1.1 Startup**
- Tower must start as a long-running, 24/7 process
- Tower must initialize all components before accepting connections
- Tower must not exit after startup unless explicitly stopped
- Tower must be startable via command-line entry point

**1.2 Shutdown**
- Tower must handle shutdown signals (SIGTERM, SIGINT) gracefully
- Tower must close all client connections on shutdown
- Tower must terminate FFmpeg encoder process on shutdown
- Tower must exit cleanly within a reasonable timeout (≤5 seconds)

**1.3 Process Isolation**
- Tower must not depend on Station process being running
- Tower must operate independently of Station lifecycle
- Tower must not import or reference any Station code modules

---

### 2. HTTP Server

**2.1 Server Initialization**
- Tower must launch an HTTP server on a configurable host/port
- Default host: `0.0.0.0` (all interfaces)
- Default port: `8000`
- Server must be accessible immediately after startup

**2.2 `/stream` Endpoint**
- Tower must expose `GET /stream` endpoint
- Endpoint must accept HTTP/1.1 connections
- Endpoint must return HTTP 200 OK status
- Endpoint must set `Content-Type: audio/mpeg` header
- Endpoint must set `Cache-Control: no-cache, no-store, must-revalidate` header
- Endpoint must set `Connection: keep-alive` header
- Endpoint must NOT use `Transfer-Encoding: chunked` (raw streaming only)

**2.3 Connection Acceptance**
- Tower must accept multiple simultaneous connections to `/stream`
- Tower must not reject connections based on client count
- Tower must not block on connection acceptance
- New clients can connect at any time during Tower operation

---

### 3. Audio Source: Fallback Tone Generator

**3.1 Tone Generator**
- Tower must use a fallback PCM tone generator as its sole audio source
- Tone generator must produce continuous audio (no gaps)
- Tone generator must output PCM in canonical format:
  - Format: `s16le` (signed 16-bit little-endian)
  - Sample rate: `48000` Hz
  - Channels: `2` (stereo)
  - Frame size: `1024` samples per frame (~21.3 ms at 48 kHz)

**3.2 Tone Characteristics**
- Tone frequency: `440` Hz (A4 note) or configurable
- Tone must be a sine wave
- Tone must be continuous (no silence between frames)
- Tone must be generated in real-time (not pre-buffered)

**3.3 Frame Generation**
- Tone generator must produce frames at real-time pace (~21.3 ms intervals)
- Each frame must contain exactly `1024 * 2 * 2 = 4096` bytes (1024 samples × 2 channels × 2 bytes per sample)
- Frame generation must not block the main thread
- Frame generation must be thread-safe if accessed from multiple threads

---

### 4. MP3 Encoding via FFmpeg

**4.1 FFmpeg Process**
- Tower must launch FFmpeg as an external subprocess
- FFmpeg must be started at Tower startup
- FFmpeg must run continuously while Tower is running
- FFmpeg process must be managed by Tower (not systemd)

**4.2 Canonical FFmpeg Command**
- Tower must use the following exact FFmpeg command:
  ```bash
  ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 \
         -f mp3 -b:a 128k -acodec libmp3lame \
         pipe:1
  ```
- Input: PCM from stdin (`pipe:0`)
- Output: MP3 to stdout (`pipe:1`)
- Tower must write PCM bytes to FFmpeg stdin
- Tower must read MP3 bytes from FFmpeg stdout

**4.3 Encoding Format**
- Input format: `s16le` (signed 16-bit little-endian PCM)
- Input sample rate: `48000` Hz
- Input channels: `2` (stereo)
- Output format: `mp3`
- Output bitrate: `128k` (128 kbps CBR)
- Output codec: `libmp3lame`

**4.4 Encoder I/O**
- Tower must write PCM frames to FFmpeg stdin continuously
- Tower must read MP3 chunks from FFmpeg stdout continuously
- Tower must handle FFmpeg stdin pipe errors (broken pipe, etc.)
- Tower must handle FFmpeg stdout EOF (encoder crash/exit)
- Tower must not block indefinitely on FFmpeg I/O operations

**4.5 Encoder Restart (Out of Scope)**
- Tower must NOT implement encoder restart logic in Phase 1
- If FFmpeg crashes or exits, Tower may log an error but is not required to restart it
- Tower may exit or continue operating without encoder (behavior is undefined in Phase 1)

---

### 5. MP3 Stream Broadcasting

**5.1 Broadcast Model**
- Tower must maintain a list of all connected HTTP clients
- Tower must read MP3 chunks from FFmpeg stdout
- Tower must write the same MP3 chunk to all connected clients simultaneously
- All clients must receive identical MP3 bytes (true broadcast)

**5.2 Chunk Reading**
- Tower must read MP3 chunks from FFmpeg stdout in a continuous loop
- Read buffer size: `8192` bytes (8 KB) or configurable
- Tower must not block indefinitely on read operations
- Tower must handle EOF from FFmpeg stdout (encoder exit)

**5.3 Chunk Broadcasting**
- Each MP3 chunk read from FFmpeg must be broadcast to all connected clients
- Broadcasting must be synchronous (all clients receive chunk before next chunk is read)
- Broadcasting must not skip clients
- Broadcasting must handle client write failures gracefully (see Section 6)

**5.4 Stream Continuity**
- MP3 stream must be continuous (no gaps between chunks)
- Clients joining mid-stream must receive audio from the current point
- No backfill or buffering for late-joining clients
- MP3 decoder resynchronization is handled by clients (expected behavior)

---

### 6. Client Connection Management

**6.1 Client Tracking**
- Tower must track all active HTTP client connections
- Tower must add clients to tracking list when they connect to `/stream`
- Tower must remove clients from tracking list when they disconnect
- Client tracking must be thread-safe (multiple threads may access client list)

**6.2 Client Disconnect Detection**
- Tower must detect client disconnects (socket errors, closed connections)
- Tower must detect disconnects during write operations
- Tower must detect disconnects during read operations (if applicable)
- Disconnect detection must be immediate (not delayed)

**6.3 Clean Disconnect Handling**
- Tower must remove disconnected clients from the broadcast list immediately
- Tower must close the client socket/file descriptor on disconnect
- Tower must not attempt to write to disconnected clients
- Tower must not log errors for normal client disconnects (only for unexpected errors)

**6.4 Non-Blocking Disconnect**
- Tower must never block when a client disconnects
- Disconnect handling must complete in O(1) time (constant time)
- Disconnect handling must not delay broadcasting to other clients
- Disconnect handling must not cause Tower to miss encoder output

**6.5 Slow Client Handling (Out of Scope)**
- Tower must NOT implement slow-client detection in Phase 1
- Tower must NOT drop clients based on write timeouts in Phase 1
- Tower must NOT implement write buffering or queuing per client in Phase 1
- Slow clients may cause Tower to block on writes (acceptable in Phase 1)

---

### 7. Threading Model

**7.1 Main Thread**
- Main thread must run the HTTP server
- Main thread must handle HTTP connection acceptance
- Main thread must delegate per-connection handling to worker threads or async handlers

**7.2 Encoder Reader Thread**
- Tower must run a dedicated thread for reading MP3 chunks from FFmpeg stdout
- Encoder reader thread must run continuously while Tower is running
- Encoder reader thread must call broadcast function for each MP3 chunk
- Encoder reader thread must handle EOF and errors from FFmpeg

**7.3 PCM Writer Thread**
- Tower must run a dedicated thread for writing PCM frames to FFmpeg stdin
- PCM writer thread must generate tone frames at real-time pace
- PCM writer thread must write frames to FFmpeg stdin continuously
- PCM writer thread must handle pipe errors gracefully

**7.4 Thread Coordination**
- Threads must coordinate access to shared resources (client list, etc.)
- Thread synchronization must use appropriate primitives (locks, queues, etc.)
- Threads must not deadlock
- Threads must be joinable on shutdown

---

### 8. Error Handling

**8.1 FFmpeg Errors**
- Tower must handle FFmpeg startup failures (log error, may exit or continue)
- Tower must handle FFmpeg stdin write errors (broken pipe, etc.)
- Tower must handle FFmpeg stdout read errors (EOF, etc.)
- Tower must not crash on FFmpeg errors

**8.2 HTTP Server Errors**
- Tower must handle HTTP server startup failures (log error, exit)
- Tower must handle client connection errors (log, continue)
- Tower must handle socket errors during client writes (log, remove client)
- Tower must not crash on HTTP errors

**8.3 Tone Generator Errors**
- Tower must handle tone generator initialization failures (log error, exit)
- Tower must handle frame generation errors (log error, may use silence or exit)
- Tower must not crash on tone generator errors

**8.4 General Error Policy**
- Tower must log all errors at appropriate log levels
- Tower must continue operating when possible (graceful degradation)
- Tower must exit cleanly on fatal errors (cannot continue)

---

### 9. Configuration

**9.1 Environment Variables**
- Tower must support configuration via environment variables:
  - `TOWER_HOST` (default: `0.0.0.0`)
  - `TOWER_PORT` (default: `8000`)
  - `TOWER_BITRATE` (default: `128k`)
  - `TOWER_TONE_FREQUENCY` (default: `440`)
  - `TOWER_READ_CHUNK_SIZE` (default: `8192`)

**9.2 Configuration Validation**
- Tower must validate configuration values at startup
- Tower must reject invalid configuration (invalid port, invalid bitrate, etc.)
- Tower must exit with error code on invalid configuration
- Tower must log configuration values at startup (at INFO or DEBUG level)

---

### 10. Logging

**10.1 Log Levels**
- Tower must support standard log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Tower must log startup events (INFO level)
- Tower must log client connections/disconnections (DEBUG level)
- Tower must log errors (ERROR level)
- Tower must log fatal errors (CRITICAL level)

**10.2 Log Format**
- Logs must include timestamps
- Logs must include log level
- Logs must include component/module name
- Logs must be human-readable

---

## Test Mapping

Each contract requirement above maps directly to one or more test cases:

- **Section 1 (Process Lifecycle)** → Process lifecycle tests
- **Section 2 (HTTP Server)** → HTTP server tests, endpoint tests
- **Section 3 (Tone Generator)** → Tone generator tests, PCM format tests
- **Section 4 (FFmpeg Encoding)** → FFmpeg process tests, encoding tests
- **Section 5 (Broadcasting)** → Broadcast tests, multi-client tests
- **Section 6 (Client Management)** → Disconnect tests, non-blocking tests
- **Section 7 (Threading)** → Threading tests, concurrency tests
- **Section 8 (Error Handling)** → Error handling tests, failure mode tests
- **Section 9 (Configuration)** → Configuration tests, validation tests
- **Section 10 (Logging)** → Logging tests

---

## Out of Scope (Explicitly Excluded)

The following features are explicitly excluded from Phase 1:

- ❌ Slow-client handling (timeouts, dropping slow clients)
- ❌ AudioPump component
- ❌ AudioInputRouter component
- ❌ Unix domain socket (`/var/run/retrowaves/pcm.sock`)
- ❌ Station integration (receiving live PCM from Station)
- ❌ Encoder restart logic (exponential backoff, retry limits)
- ❌ Station code imports or references
- ❌ Fallback asset loading (MP3 files, "Please Stand By" audio)
- ❌ Health check endpoints
- ❌ Status endpoints
- ❌ Metadata/event side-channels

---

## Success Criteria

Phase 1 is complete when:

1. ✅ Tower starts as a 24/7 process and runs continuously
2. ✅ HTTP server accepts connections on `/stream` endpoint
3. ✅ Tone generator produces continuous PCM audio
4. ✅ FFmpeg encodes PCM to MP3 using canonical command
5. ✅ MP3 stream is broadcast to all connected clients
6. ✅ Clients can connect and receive continuous MP3 audio
7. ✅ Client disconnects are handled cleanly and non-blocking
8. ✅ All contract requirements have passing tests
9. ✅ No Station code is imported or referenced

---

**Document:** Tower Phase 1 Minimal Contract  
**Version:** 1.0  
**Last Updated:** 2025-01-XX

