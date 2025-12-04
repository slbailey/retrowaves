# Retrowaves Tower — Phase 2 Sources and Control Contract

**Phase:** 2 (Sources and Control)  
**Status:** Contract Definition  
**Date:** 2025-01-XX

This document defines the explicit, testable contract for Phase 2 of Retrowaves Tower. Phase 2 introduces multiple audio source modes (tone, silence, file) with thread-safe switching, and adds HTTP control endpoints for source management and status monitoring.

---

## Scope

Phase 2 implements:
- ✅ SourceMode enum (tone, silence, file)
- ✅ SourceManager for thread-safe source switching
- ✅ ToneSource (existing Phase 1 behavior)
- ✅ SilenceSource (PCM zeros)
- ✅ FileSource (WAV file playback with looping)
- ✅ HTTP GET /status endpoint
- ✅ HTTP POST /control/source endpoint
- ✅ TOWER_DEFAULT_SOURCE configuration
- ✅ Backwards compatibility with Phase 1

Phase 2 does NOT implement:
- ❌ Station integration (Unix socket, live PCM input)
- ❌ Scheduling logic (automatic source switching)
- ❌ Source transitions (fade-in/fade-out)
- ❌ Multiple file sources or playlists
- ❌ Source history or logging
- ❌ Encoder restart logic
- ❌ Slow-client handling

---

## Contract Requirements

### 1. Source System Architecture

**1.1 SourceMode Enum**
- Tower must define a `SourceMode` enum with exactly three values:
  - `"tone"` — generate PCM tone (Phase 1 behavior)
  - `"silence"` — generate PCM zeros
  - `"file"` — read PCM from WAV file
- SourceMode must be a string-based enum (for JSON serialization)
- SourceMode values must be case-sensitive and exact matches

**1.2 SourceManager Component**
- Tower must implement a `SourceManager` class
- SourceManager must hold the current source mode (SourceMode enum value)
- SourceManager must hold the current Source instance (ToneSource, SilenceSource, or FileSource)
- SourceManager must provide thread-safe source switching
- SourceManager must ensure no audio interruption during source switches
- SourceManager must guarantee that only one Source instance is active at a time
- SourceManager must initialize with a default source based on configuration

**1.3 Source Interface**
- All Source classes must implement a common interface/protocol
- All Source classes must provide a `generate_frame() -> bytes` method
- All Source classes must provide a `frames() -> Iterator[bytes]` method
- All Source classes must produce frames in canonical PCM format:
  - Format: `s16le` (signed 16-bit little-endian)
  - Sample rate: `48000` Hz
  - Channels: `2` (stereo)
  - Frame size: `1024` samples per frame (~21.3 ms at 48 kHz)
  - Frame bytes: exactly `4096` bytes per frame (1024 × 2 × 2)
- Source.generate_frame() should not be required to sleep or manage timing — AudioPump handles real-time pacing

**1.4 ToneSource**
- ToneSource must generate continuous PCM tone frames
- ToneSource must produce sine wave audio at configured frequency (default: 440 Hz)
- ToneSource frame generation must not break MP3 streaming
- Phase continuity across frames is optional but preferred (no strict requirement)
- ToneSource must be thread-safe for concurrent access
- ToneSource behavior must be identical to Phase 1 ToneGenerator

**1.5 SilenceSource**
- SilenceSource must generate continuous PCM frames containing all zeros
- SilenceSource must produce frames in canonical format (4096 bytes per frame)
- SilenceSource must be thread-safe for concurrent access
- SilenceSource must never produce non-zero samples

**1.6 FileSource**
- FileSource must read PCM data from a WAV file
- FileSource must support WAV files with format matching canonical format:
  - Format: `s16le` (signed 16-bit little-endian)
  - Sample rate: `48000` Hz
  - Channels: `2` (stereo)
- FileSource must loop at end-of-file (EOF) automatically
- FileSource must produce frames of exactly 4096 bytes (1024 samples × 2 channels × 2 bytes)
- FileSource must reject WAV files that do not match canonical format (rebuffering/resampling deferred to later phase)
- FileSource must be thread-safe for file access
- FileSource must handle file I/O errors gracefully (log error, may fall back to silence)
- Minimal audio glitches at loop boundaries are acceptable

**1.7 Thread-Safe Source Switching**
- SourceManager must use appropriate synchronization primitives (locks, atomic operations)
- Source switching must be atomic (no partial state visible to audio threads)
- Source switching must not interrupt Tower's audio pipeline
- Source switching should not interrupt the PCM loop nor crash Tower; minimal audio glitches acceptable
- Source switching should complete promptly (within a small number of milliseconds)
- Source switching must not block the HTTP control API thread
- Source switching must not block the PCM writer thread
- Source switching must not block the encoder reader thread

**1.8 Source Lifecycle**
- SourceManager must create Source instances on demand
- SourceManager must clean up old Source instances after switching
- SourceManager must handle Source initialization errors (log error, may keep previous source)
- FileSource must open file handles and close them on cleanup
- Source instances must not leak resources (file handles, memory)

---

### 2. Control API

**2.1 GET /status Endpoint**
- Tower must expose `GET /status` endpoint
- Endpoint must accept HTTP/1.1 connections
- Endpoint must return HTTP 200 OK status
- Endpoint must return JSON response with `Content-Type: application/json`
- Endpoint must return the following JSON structure:
  ```json
  {
    "source_mode": "tone" | "silence" | "file",
    "file_path": "string" | null,
    "num_clients": integer,
    "encoder_running": boolean,
    "uptime_seconds": number
  }
  ```
- `source_mode` must be the current SourceMode enum value (string)
- `file_path` must be the current file path if mode is "file", otherwise `null`
- `num_clients` must be the current number of connected HTTP clients to `/stream`
- `encoder_running` must be `true` if FFmpeg encoder process is running, `false` otherwise
- `uptime_seconds` must be the number of seconds since Tower started (float or integer)
- Endpoint must return promptly (≤100 ms response time)
- Endpoint must never block audio threads
- Endpoint must be thread-safe (can be called concurrently)

**2.2 POST /control/source Endpoint**
- Tower must expose `POST /control/source` endpoint
- Endpoint must accept HTTP/1.1 connections
- Endpoint must accept JSON request body with `Content-Type: application/json`
- Endpoint must parse JSON request body
- Endpoint must validate request parameters based on mode
- Endpoint must return HTTP 200 OK on successful source switch
- Endpoint must return HTTP 400 Bad Request on invalid input
- Endpoint must return JSON response with `Content-Type: application/json`

**2.3 POST /control/source Request Format**
- Request body must be JSON object
- For `"tone"` mode:
  ```json
  {
    "mode": "tone"
  }
  ```
  - `file_path` must not be required or accepted
- For `"silence"` mode:
  ```json
  {
    "mode": "silence"
  }
  ```
  - `file_path` must not be required or accepted
- For `"file"` mode:
  ```json
  {
    "mode": "file",
    "file_path": "/path/to/file.wav"
  }
  ```
  - `file_path` must be required and must be a non-empty string
  - `file_path` must point to an existing file
  - `file_path` must point to a valid WAV file matching canonical format

**2.4 POST /control/source Validation**
- Tower must validate that `mode` is one of: `"tone"`, `"silence"`, `"file"`
- Tower must return 400 if `mode` is missing, invalid, or not a string
- Tower must return 400 if `mode` is `"file"` and `file_path` is missing
- Tower must return 400 if `mode` is `"file"` and `file_path` is not a string
- Tower must return 400 if `mode` is `"file"` and `file_path` is empty string
- Tower must return 400 if `mode` is `"file"` and file does not exist
- Tower must return 400 if `mode` is `"file"` and file is not a valid WAV file
- Tower must return 400 if `mode` is `"file"` and WAV file format does not match canonical format
- Tower must return 400 if `mode` is `"tone"` or `"silence"` and `file_path` is provided
- Tower must return 400 if request body is not valid JSON
- Tower must return 400 if request body is missing

**2.5 POST /control/source Response Format**
- On success (200 OK):
  ```json
  {
    "status": "ok",
    "source_mode": "tone" | "silence" | "file",
    "file_path": "string" | null
  }
  ```
- On error (400 Bad Request):
  ```json
  {
    "status": "error",
    "error": "error message string"
  }
  ```
- Error messages must be human-readable strings
- Error messages must describe the validation failure

**2.6 POST /control/source Behavior**
- Endpoint must switch source mode atomically
- Endpoint must return promptly (≤100 ms response time)
- Endpoint must never block audio threads
- Endpoint must be thread-safe (can be called concurrently)
- Endpoint must not interrupt active audio streaming
- Endpoint must not disconnect existing `/stream` clients
- Endpoint must handle source switching errors gracefully (log error, return 500 on unexpected errors)

---

### 3. Startup Behavior

**3.1 TOWER_DEFAULT_SOURCE Configuration**
- Tower must support `TOWER_DEFAULT_SOURCE` environment variable
- `TOWER_DEFAULT_SOURCE` must accept values: `"tone"`, `"silence"`, or `"file"`
- `TOWER_DEFAULT_SOURCE` must be case-sensitive
- If `TOWER_DEFAULT_SOURCE` is not set, default must be `"tone"` (Phase 1 behavior)
- If `TOWER_DEFAULT_SOURCE` is set to invalid value, Tower must exit with error at startup

**3.2 Default Source: "tone"**
- If `TOWER_DEFAULT_SOURCE` is `"tone"` or unset, Tower must initialize ToneSource
- ToneSource must use configured tone frequency (default: 440 Hz)
- Startup behavior must be identical to Phase 1

**3.3 Default Source: "silence"**
- If `TOWER_DEFAULT_SOURCE` is `"silence"`, Tower must initialize SilenceSource
- SilenceSource must produce continuous PCM zeros
- Startup must proceed normally (no file validation required)

**3.4 Default Source: "file"**
- If `TOWER_DEFAULT_SOURCE` is `"file"`, Tower must also read `TOWER_DEFAULT_FILE_PATH` environment variable
- `TOWER_DEFAULT_FILE_PATH` must be required when `TOWER_DEFAULT_SOURCE` is `"file"`
- Tower must validate that `TOWER_DEFAULT_FILE_PATH` points to an existing file at startup
- Tower must validate that `TOWER_DEFAULT_FILE_PATH` points to a valid WAV file at startup
- Tower must validate that WAV file format matches canonical format at startup
- If `TOWER_DEFAULT_FILE_PATH` is missing, Tower must exit with error at startup
- If `TOWER_DEFAULT_FILE_PATH` points to non-existent file, Tower must exit with error at startup
- If `TOWER_DEFAULT_FILE_PATH` points to invalid WAV file, Tower must exit with error at startup
- If WAV file format does not match canonical format, Tower must exit with error at startup
- Tower must fail fast on file validation errors (before starting HTTP server or encoder)

**3.5 Startup Sequence**
- Tower must validate `TOWER_DEFAULT_SOURCE` and `TOWER_DEFAULT_FILE_PATH` (if required) before initializing components
- Tower must initialize SourceManager with default source before starting encoder
- Tower must initialize SourceManager before starting HTTP server
- Tower must start encoder with default source
- Tower must start HTTP server after encoder is running
- If default source initialization fails, Tower must exit with error (fail fast)

---

### 4. Compatibility Requirements

**4.1 Phase 1 Backwards Compatibility**
- All Phase 1 behavior must remain unchanged when:
  - `TOWER_DEFAULT_SOURCE` is not set (defaults to `"tone"`)
  - No calls to `/control/source` are made
- `/stream` endpoint must behave exactly as Phase 1 externally:
  - Same HTTP headers
  - Same MP3 stream format
  - Same connection handling
  - Same client disconnect behavior
- MP3 stream output must be identical to Phase 1 when using `"tone"` mode
- All Phase 1 configuration options must continue to work:
  - `TOWER_HOST`, `TOWER_PORT`, `TOWER_BITRATE`, `TOWER_TONE_FREQUENCY`, `TOWER_READ_CHUNK_SIZE`

**4.2 Source Switching and Stream Continuity**
- Switching sources must not disconnect existing `/stream` clients
- Switching sources must not interrupt MP3 stream output
- Switching sources must not cause MP3 stream to stop
- Switching sources must not cause encoder to restart
- Switching sources must transition seamlessly (no gaps in MP3 stream)
- MP3 decoder resynchronization after source switch is handled by clients (expected behavior)

**4.3 Thread Safety and Non-Blocking**
- HTTP control API endpoints must never block audio threads
- Source switching must never block PCM writer thread
- Source switching must never block encoder reader thread
- HTTP control API must be accessible even when audio threads are busy
- HTTP control API must return promptly even during high audio load

---

### 5. Testability Requirements

**5.1 SourceManager Tests**
- Tests must verify that SourceManager exists
- Tests must verify that SourceManager holds current source mode
- Tests must verify that SourceManager holds current Source instance
- Tests must verify that SourceManager can switch between modes
- Tests must verify that SourceManager switching is thread-safe
- Tests must verify that SourceManager does not leak resources

**5.2 Source Mode Switching Tests**
- Tests must verify that modes can be switched via `/control/source`
- Tests must verify that switching to `"tone"` mode works
- Tests must verify that switching to `"silence"` mode works
- Tests must verify that switching to `"file"` mode works
- Tests must verify that switching does not interrupt Tower operation
- Tests must verify that switching does not disconnect stream clients

**5.3 /status Endpoint Tests**
- Tests must verify that `/status` returns correct JSON structure
- Tests must verify that `source_mode` field is correct
- Tests must verify that `file_path` field is correct (null or string)
- Tests must verify that `num_clients` field is correct
- Tests must verify that `encoder_running` field is correct
- Tests must verify that `uptime_seconds` field is present and increasing
- Tests must verify that `/status` returns promptly

**5.4 /control/source Validation Tests**
- Tests must verify that `/control/source` validates `mode` parameter
- Tests must verify that `/control/source` returns 400 for invalid `mode`
- Tests must verify that `/control/source` validates `file_path` for `"file"` mode
- Tests must verify that `/control/source` returns 400 for missing `file_path` in `"file"` mode
- Tests must verify that `/control/source` returns 400 for invalid `file_path` in `"file"` mode
- Tests must verify that `/control/source` returns 400 for non-existent file
- Tests must verify that `/control/source` returns 400 for invalid WAV file
- Tests must verify that `/control/source` returns 200 on success

**5.5 Source Output Tests**
- Tests must verify that ToneSource produces MP3 output (structural verification)
- Tests must verify that SilenceSource produces MP3 output (structural verification)
- Tests must verify that FileSource produces MP3 output (structural verification)
- Tests do not require audio correctness evaluation (no audio quality checks)
- Tests only need to verify that MP3 stream is produced and continuous

**5.6 Test Scope Limitations**
- Tests do not require Station integration
- Tests do not require scheduling logic
- Tests do not require audio correctness evaluation
- Tests focus on structural behavior and API correctness

---

## Explicit Invariants

### SourceManager Invariants

**I1: Single Active Source**
- At any point in time, SourceManager must have exactly one active Source instance
- SourceManager must never have zero active sources
- SourceManager must never have multiple active sources simultaneously

**I2: Thread-Safe State**
- SourceManager's current source mode must be readable atomically
- SourceManager's current Source instance must be readable atomically
- Source switching must be atomic (no intermediate states visible to audio threads)

**I3: No Audio Interruption**
- Source switching should not interrupt the PCM loop nor crash Tower; minimal audio glitches acceptable
- Source switching must not cause encoder to miss input frames
- PCM writer thread must always have a valid Source to read from

**I4: Resource Cleanup**
- Old Source instances must be cleaned up after switching
- FileSource must close file handles on cleanup
- SourceManager must not leak memory or file handles

### Source Frame Guarantees

**I5: ToneSource Frame Guarantees**
- ToneSource must produce frames of exactly 4096 bytes
- ToneSource frame generation must not break MP3 streaming
- Phase continuity across frames is optional but preferred
- ToneSource must never produce frames with incorrect format

**I6: SilenceSource Frame Guarantees**
- SilenceSource must produce frames of exactly 4096 bytes
- SilenceSource must produce frames containing all zeros
- SilenceSource must never produce non-zero samples

**I7: FileSource Frame Guarantees**
- FileSource must produce frames of exactly 4096 bytes
- FileSource must loop at EOF (continuous output)
- FileSource must reject WAV files that do not match canonical format (rebuffering/resampling deferred to later phase)
- FileSource must never produce frames with incorrect format
- Minimal audio glitches at loop boundaries are acceptable

**I8: Source Frame Format Consistency**
- All Source classes must produce frames in identical format:
  - Format: `s16le` (signed 16-bit little-endian)
  - Sample rate: `48000` Hz
  - Channels: `2` (stereo)
  - Frame size: `1024` samples per frame
  - Frame bytes: exactly `4096` bytes per frame

### HTTP Control API Invariants

**I9: Non-Blocking API**
- `/status` endpoint must never block audio threads
- `/control/source` endpoint must never block audio threads
- HTTP control API must return within 100 ms
- HTTP control API must be accessible even when audio threads are busy

**I10: Atomic Source Switching**
- `/control/source` must switch source atomically
- Source switch must complete before HTTP response is sent
- Source switch must not be visible to audio threads until complete

**I11: Stream Continuity**
- Source switching must not disconnect `/stream` clients
- Source switching must not interrupt MP3 stream output
- Source switching must not cause encoder to restart
- MP3 stream must remain continuous across source switches

**I12: Validation Correctness**
- `/control/source` must validate all inputs before switching
- `/control/source` must return 400 for all invalid inputs
- `/control/source` must return 200 only after successful switch
- Invalid source switches must not affect current source

### Backwards Compatibility Invariants

**I13: Phase 1 Compatibility**
- When `TOWER_DEFAULT_SOURCE` is not set, behavior must be identical to Phase 1
- When no `/control/source` calls are made, behavior must be identical to Phase 1
- `/stream` endpoint must behave exactly as Phase 1 externally
- All Phase 1 configuration options must continue to work

**I14: Default Source Behavior**
- Default source when `TOWER_DEFAULT_SOURCE` is unset must be `"tone"`
- Default `"tone"` source must behave identically to Phase 1 ToneGenerator
- MP3 output from default `"tone"` source must be identical to Phase 1

---

## Test Mapping

Each contract requirement above maps directly to one or more test cases:

- **Section 1 (Source System)** → SourceManager tests, Source class tests, thread-safety tests
- **Section 2 (Control API)** → HTTP endpoint tests, validation tests, response format tests
- **Section 3 (Startup Behavior)** → Configuration tests, startup sequence tests, file validation tests
- **Section 4 (Compatibility)** → Backwards compatibility tests, stream continuity tests
- **Section 5 (Testability)** → Structural behavior tests, API correctness tests
- **Invariants** → Invariant verification tests, edge case tests

---

## Out of Scope (Explicitly Excluded)

The following features are explicitly excluded from Phase 2:

- ❌ Station integration (Unix socket, live PCM input)
- ❌ Scheduling logic (automatic source switching based on time/events)
- ❌ Source transitions (fade-in/fade-out between sources)
- ❌ Multiple file sources or playlists
- ❌ Source history or logging
- ❌ Encoder restart logic
- ❌ Slow-client handling
- ❌ Audio quality verification (tests only verify structural behavior)
- ❌ WAV file format conversion (only canonical format supported)
- ❌ WAV rebuffering/resampling (deferred to later phase)

---

## Success Criteria

Phase 2 is complete when:

1. ✅ SourceMode enum is defined with three values (tone, silence, file)
2. ✅ SourceManager exists and provides thread-safe source switching
3. ✅ ToneSource, SilenceSource, and FileSource classes are implemented
4. ✅ GET /status endpoint returns correct JSON
5. ✅ POST /control/source endpoint validates inputs and switches sources
6. ✅ TOWER_DEFAULT_SOURCE configuration works for all three modes
7. ✅ Source switching does not interrupt Tower or disconnect clients
8. ✅ All Phase 1 behavior remains unchanged when using default tone mode
9. ✅ All contract requirements have passing tests
10. ✅ All invariants are verified by tests

---

**Document:** Tower Phase 2 Sources and Control Contract  
**Version:** 1.0  
**Last Updated:** 2025-01-XX

