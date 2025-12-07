# Contract: TOWER_SERVICE_INTEGRATION

This contract defines the integration and wiring of TowerService components per Section 7.6 and 8.1 of ARCHITECTURE_TOWER.md.

## 1. Core Invariants

- [I1] TowerService is responsible for **component construction and wiring**.
- [I2] Startup sequence **MUST follow** the exact order defined in Section 8.1.
- [I3] No component references another by attribute that isn't defined in contract.

## 2. Component Construction Order

- [I4] Buffers are created first:
  1. Create PCM ring buffer
  2. Create MP3 ring buffer
- [I5] Component construction MUST follow strict dependency injection order:
  1. Initialize `AudioInputRouter`
  2. Initialize `FallbackGenerator`
  3. Initialize `HTTPConnectionManager`
  4. Construct `EncoderManager(pcm_buffer, mp3_buffer, supervisor_config)` → creates FFmpegSupervisor internally
  5. Construct `AudioPump(pcm_buffer, fallback_generator, encoder_manager)` → NOT supervisor
- [I5.1] No component may reference any other component not yet constructed.
- [I5.2] TowerService MUST construct all components before starting any thread.
- [I6] FFmpegSupervisor is **never constructed in TowerService** - only inside EncoderManager.

## 3. Startup Sequence (Critical Order)

- [I7] Components are started in this exact order:
  1. Start Supervisor (via `encoder_manager.start()` - initializes FFmpeg process)
  2. Start EncoderOutputDrain thread (via supervisor - drains FFmpeg stdout)
  3. Start AudioPump thread (begins writing PCM to encoder)
  4. Start HTTP server thread (accepts client connections)
  5. Start HTTP tick/broadcast thread (begins streaming MP3 frames)
- [I7.1] **AudioPump startup timing**: EncoderManager MAY start before AudioPump, but the system MUST feed initial silence per [S19] step 4, and AudioPump MUST begin ticking within ≤1 grace period (≈24ms) to ensure continuous PCM delivery per [S7.1] and [M19]. This prevents undefined boot windows where FFmpeg receives no PCM input.
- [I8] This order ensures:
  - Buffers exist before components use them
  - FFmpeg process and stdin exist before AudioPump writes
  - EncoderOutputDrain is ready before encoding begins
  - HTTP server is ready before broadcast loop starts
  - Initial silence covers the gap between FFmpeg spawn and AudioPump's first tick per [S19] step 4
- [I26] No startup phase may block waiting on dependencies from later phases. 
  Startup must be strictly forward-directed with no reverse wait cycles.

## 4. Interface Compliance

- [I9] AudioPump only calls `encoder_manager.write_pcm()` - never supervisor directly.
- [I10] HTTPBroadcast loop only calls `encoder_manager.get_frame()` - never checks state.
- [I11] Supervisor lifecycle is completely encapsulated within EncoderManager.
- [I23] HTTP broadcast MUST run on a wall-clock interval tick (default 24ms pacing),
  NOT only when new frames are available. Lack of frames MUST NOT stall transmission.
- [I24] During encoder restart, HTTP broadcast MUST continue uninterrupted using 
  existing MP3 buffer frames or fallback frames. Restart events MUST NOT stop streaming.

## 5. Shutdown Sequence

- [I12] Shutdown order (reverse of startup):
  1. Stop HTTP server (stop accepting connections)
  2. Stop HTTP broadcast thread
  3. Stop AudioPump thread
  4. Stop EncoderManager (stops supervisor and drain thread)
  5. Release resources
- [I27] Service Shutdown Contract:
  `TowerService.stop()` MUST:
  1. Stop AudioPump (metronome halts - AudioPump thread must be stopped and joined).
  2. Stop EncoderManager (which stops Supervisor per [M30] and [S31]).
  3. Stop HTTP connection manager (close client sockets - all active connections must be closed gracefully).
  4. Wait for all threads to exit (join - all background threads must be joined with appropriate timeouts).
  5. Return only after a fully quiescent system state (no active threads, no running processes, system is fully stopped).

## Required Tests

- `tests/contracts/test_tower_service_integration.py` MUST cover:
  - [I1]–[I3]: Component wiring and contract compliance
  - [I4]–[I6], [I5.1]–[I5.2]: Construction order and supervisor encapsulation
  - [I7]–[I8], [I26]: Critical startup sequence
  - [I9]–[I11], [I23]–[I24]: Interface compliance
  - [I12], [I27]: Shutdown sequence and service shutdown contract
  - [I13]–[I17], [I25]: Component isolation for testing
  - [I18]–[I22]: Operational modes + test mode separation
  - New test expectations for [I27]:
    - `test_shutdown_halts_audiopump_ticks`: Verify that after `tower_service.stop()`, AudioPump metronome halts (no further ticks occur).
    - `test_shutdown_allows_garbage_collection_within_timeout`: Verify that after shutdown completes, system reaches a fully quiescent state allowing garbage collection within a reasonable timeout (no lingering threads or resources).

## 6. Component Isolation for Testing

These requirements ensure TowerService components remain independently testable,
preventing unintended coupling to FFmpegSupervisor or other subsystems.

- [I13] TowerService MUST support constructing and operating without starting
        the encoder pipeline for tests not involving encoding.

- [I14] EncoderManager and FFmpegSupervisor MUST be replaceable or disable-able
        via constructor flags or dependency injection for unit and broadcast
        semantics tests.

- [I15] HTTPConnectionManager, Runtime loop, and FrameRingBuffer MUST function
        correctly when EncoderManager is replaced with a stub object that returns
        synthetic MP3 frames.

- [I16] Unit tests MUST NOT require launching FFmpeg. Integration tests that
        specifically test encoding or liveness behavior MUST explicitly enable it.

- [I17] No component outside EncoderManager may assume ffmpeg is running.
        All consumption of MP3 frames must tolerate silence, mock output, or
        empty-frame sequences at startup.
- [I25] FFmpeg startup must be opt-in.

        The default TowerService/EncoderManager instantiation MUST NOT start FFmpeg
        unless explicitly enabled. Unit and runtime-only tests run with encoding
        disabled automatically.

        FFmpeg may start only when one of the following is provided:

          • constructor flag `encoder_enabled=True`, or
          • explicit integration test config/environment enabling encoding

        Production code MUST NOT contain test-framework detection or test-path logic.

        Enforcement is implemented in `FFmpegSupervisor._start_encoder_process()`
        per [S19.12].

### Testing Tiers (Normative)

| Tier | Encoder Required | Purpose |
|---|---|---|
| Unit Tests | ❌ No | RingBuffer, HTTP broadcast, routing, semantics |
| Runtime Tests | ⚙ Optional/Mock | Scheduling, client handling, smoothness |
| Full Integration Tests | ✔ Yes | End-to-end encoder + broadcast validation |

Tests MUST enforce these boundaries.

## 7. Operational Modes + Test Mode Separation

- [I18] TowerService MUST expose mode selection & status (Operational Mode [O1]–[O7] per ENCODER_OPERATION_MODES.md).
- [I19] When `encoder_enabled=False` OR `TOWER_ENCODER_ENABLED=0` → TowerService MUST initialize system in [O6] OFFLINE_TEST_MODE.
- [I20] No contract test involving HTTP broadcast, client fanout, or RingBuffer semantics may launch FFmpeg unless Operational Mode explicitly requests LIVE_INPUT.
- [I21] Full system startup MUST follow Operational Mode transitions:
  - COLD_START → BOOTING → LIVE_INPUT
  - with FALLBACK used whenever audio is unavailable.
- [I22] TowerService MUST be the root owner of Operational Mode state. 
  EncoderManager and Supervisor MAY update internal state, but TowerService is responsible 
  for exposing and publishing the final operational mode externally.

## 8. HTTP Status and Monitoring Endpoints

- [I27] HTTP server MUST expose `/tower/buffer` endpoint wired to AudioInputRouter stats per HTTP_STATUS_MONITORING_CONTRACT.md.
  - Endpoint MUST call `AudioInputRouter.get_stats()` per [R23].
  - Endpoint MUST return JSON with `fill` (count) and `capacity` fields.
  - Endpoint is a stable public API per [M2.4] - must not be removed without deprecation.
- [I28] HTTP server MUST be constructed after AudioInputRouter and before start of broadcasting.
  - Construction order: AudioInputRouter → HTTP server → start broadcasting.
  - Ensures HTTP server has access to AudioInputRouter instance for status endpoints.
- [I29] The HTTP server MUST have access to AudioInputRouter instance to query buffer statistics.
- [I30] Status endpoints MUST be non-blocking and thread-safe per HTTP_STATUS_MONITORING_CONTRACT.md [M8].
- [I31] Status endpoints MUST NOT impact Tower's core audio processing performance per HTTP_STATUS_MONITORING_CONTRACT.md [M10].

**Note:** This functionality was present in the legacy implementation (`tower/_legacy/http_server.py`) and must be preserved. See HTTP_STATUS_MONITORING_CONTRACT.md for full requirements.

