# Retrowaves — Phase 1.0 Definition of Done (Broadcast-Grade Core)

## Purpose

This document defines the minimum feature set required to truthfully state:

**"This system behaves like real radio automation equipment."**

Phase 1.0 is about correctness, not features. All requirements in this document MUST be verifiable via logs, audio capture, test harness, or automated monitoring.

## Scope

Phase 1.0 includes ONLY:
- Core broadcast audio correctness
- Timing and clock discipline
- Buffer stability
- Fallback robustness
- Restart and failure safety
- Observability needed to prove the above

**Explicitly Excluded:**
- DJ programming intelligence
- Web UI
- Multi-station support
- Live mic UX
- Emergency broadcast UI polish
- Loudness normalization (tickler-driven, optional)
- Asset integrity analysis (optional, tickler-driven)
- Format anomaly detection (optional)

---

## 1️⃣ Continuous Audio Guarantee

### 1.1 Tower Output Continuity

**1.1.1** Tower MUST emit valid MP3 frames continuously under all conditions, including:
- Station online and streaming PCM
- Station offline (fallback mode)
- Station restarting
- Network disconnections between Station and Tower
- FFmpeg encoder process crashes
- System resource constraints

**1.1.2** Tower MUST NOT emit silence gaps exceeding 1.5 seconds (grace period, ± one tick tolerance) when Station PCM is unavailable.

**1.1.3** Tower MUST transition from Program PCM to fallback audio without audible artifacts (pops, clicks, or discontinuities).

**1.1.4** Tower MUST maintain MP3 stream continuity across encoder restarts. EncoderManager MUST restart FFmpeg encoder subprocesses without interrupting the output stream.

**1.1.5** Tower output MUST be decodable by standard MP3 decoders at all times. Invalid MP3 frames MUST NOT be emitted.

### 1.2 Encoder Frame Guarantee

**1.2.1** EncoderManager MUST always return a valid PCM frame per tick when queried, regardless of:
- PCM buffer state
- Station connection state
- Encoder subprocess health
- System load

**1.2.2** EncoderManager MUST NOT block the audio tick loop. Frame generation MUST complete within the tick window.

**1.2.3** When PCM buffer is empty or Station is offline, EncoderManager MUST return frames from the active fallback source (grace period silence, file fallback, or tone).

### 1.3 PCM Ingestion Continuity

**1.3.1** Tower PCM ingestion MUST accept frames from Station without blocking, regardless of:
- Buffer fill level
- Encoder processing speed
- Network latency variations

**1.3.2** PCM ingestion MUST drop frames (with logging) rather than block or deadlock when buffer is full.

**1.3.3** PCM ingestion MUST recover automatically when Station reconnects after disconnection, without manual intervention.

---

## 2️⃣ Fallback & Grace Behavior

### 2.1 Grace Period

**2.1.1** Tower MUST observe a grace period of 1.5 seconds (default, configurable) after Program PCM stops before engaging fallback audio.

**2.1.2** During grace period, Tower MUST emit silence (zero-amplitude PCM frames) encoded as valid MP3.

**2.1.3** Grace period MUST be observable via logs and events. Tower MUST log when grace period starts and when fallback engages.

### 2.2 Fallback Priority Sequence

**2.2.1** Tower MUST follow this fallback priority sequence (in order):
1. Program PCM (live audio from Station)
2. Grace Period Silence (1.5 seconds default)
3. MP3 File Fallback (if `TOWER_SILENCE_MP3_PATH` is configured and valid)
4. 440Hz Tone (synthetic sine wave)
5. Silence (last resort, zero-amplitude frames)

**2.2.2** Tower MUST transition between fallback sources without audible artifacts when higher-priority sources become unavailable.

**2.2.3** Tower MUST log fallback source transitions with timestamps and reason codes.

### 2.3 File Fallback Looping

**2.3.1** When file fallback is active, Tower MUST loop the pre-decoded audio file seamlessly without audible pops, clicks, or discontinuities at loop boundaries.

**2.3.2** File fallback MUST use zero-latency frame access (pure array indexing, no I/O, no locks, no subprocess calls) during normal operation.

**2.3.3** File fallback MUST pre-decode the entire audio file to PCM at startup. Decoding MUST NOT occur during `next_frame()` calls.

**2.3.4** File fallback loop boundaries MUST use crossfade (default 2048 samples ≈ 42.6ms) to eliminate audible seams.

**2.3.5** If file fallback file is invalid, missing, or exceeds maximum duration (default 10 minutes), Tower MUST fall back to tone without blocking or erroring.

### 2.4 Tone Fallback

**2.4.1** When tone fallback is active, Tower MUST generate a continuous 440Hz sine wave at consistent amplitude.

**2.4.2** Tone generation MUST be zero-latency (synthetic PCM generation, no file I/O, no subprocess calls).

**2.4.3** Tone MUST maintain phase continuity across frame boundaries (no phase jumps or audible artifacts).

### 2.5 Phase Continuity Rules

**2.5.1** Fallback transitions MUST NOT interrupt in-progress MP3 frames. Transitions MUST occur at frame boundaries.

**2.5.2** Tower MUST NOT mix fallback sources. Only one source (Program PCM, file, or tone) MUST be active at a time.

**2.5.3** When Program PCM resumes after fallback, Tower MUST transition back to Program PCM without audible artifacts.

---

## 3️⃣ Timing & Two-Clock Discipline

### 3.1 Clock A vs Clock B Separation

**3.1.1** Clock A (Station decode timing) and Clock B (Tower encoding timing) MUST operate independently. Clock A MUST NOT be influenced by Clock B state, buffer fill, or encoder processing time.

**3.1.2** Clock A MUST advance based on wall-clock time for segment timing. Segment duration MUST be calculated from wall-clock start time, not from decode rate or buffer state.

**3.1.3** Clock B (Tower audio tick) MUST run at fixed 48kHz sample rate (1024 samples per tick ≈ 21.33ms). Tick timing MUST NOT vary based on Station state or PCM buffer fill.

**3.1.4** Clock A decode pacing adjustments (via PID controller) MUST NOT modify the Clock A timeline. Timeline advancement MUST remain wall-clock based.

### 3.2 Segment Timing Rules

**3.2.1** Station MUST decode audio segments at the rate required to maintain Clock A timeline. Decode rate MUST match segment playback rate (1x real-time for normal playback).

**3.2.2** Station MUST NOT skip, rewind, or duplicate audio frames within a segment. Each PCM frame in the source audio file MUST be decoded exactly once per segment playout.

**3.2.3** Station MUST complete segment playout within the segment's declared duration (allowing for small timing drift tolerance, but no frame drops or additions).

**3.2.4** Station MUST log segment start time, expected duration, and actual completion time for observability.

### 3.3 Decode Pacing Rules

**3.3.1** Station decode pacing MUST use Clock A base timing (`next_frame_time - now`) as the primary sleep calculation.

**3.3.2** When PID controller is enabled, PID adjustment MUST be added to Clock A sleep: `sleep = clock_a_sleep + pid_adjustment`. PID MUST NOT replace Clock A timing.

**3.3.3** Decode pacing MUST NOT block THINK operations. Decode loop sleep MUST occur between frame decodes, not during THINK.

**3.3.4** Station MUST NOT decode faster than real-time during normal operation (except during pre-fill stage). Decode rate MUST match or be slightly slower than playback rate to prevent buffer overflow.

### 3.4 Forbidden Timing Behaviors

**3.4.1** Station MUST NOT modify Clock A timeline based on Tower buffer state. Timeline MUST remain wall-clock based regardless of buffer fill level.

**3.4.2** Station MUST NOT skip segments or jump ahead in timeline to "catch up" after slow decode periods.

**3.4.3** Station MUST NOT rewind or replay audio frames that have already been sent to Tower.

**3.4.4** Tower MUST NOT request Station to adjust decode rate. Tower MUST NOT send timing corrections back to Station.

**3.4.5** Station and Tower MUST NOT share timing locks or synchronization primitives that could cause deadlock or priority inversion.

---

## 4️⃣ Buffer Stability & Prefill

### 4.1 Buffer Fill Expectations

**4.1.1** Tower PCM buffer MUST maintain a target fill ratio (default 0.5, configurable 0.1-0.9) during normal operation when Station is online and decode pacing is stable.

**4.1.2** Tower buffer MUST NOT overflow (drop frames) during normal operation when PID controller is active and functioning correctly.

**4.1.3** Tower buffer MUST NOT underflow (empty buffer causing silence) during normal operation when Station is online and decode pacing is stable.

**4.1.4** Tower buffer fill ratio MUST be observable via `/tower/buffer` endpoint. Buffer status MUST be queryable without blocking the audio tick loop.

### 4.2 Prefill Entry/Exit Conditions

**4.2.1** Station MUST enter pre-fill stage when Tower buffer ratio is below target (default < 0.5) at the start of a new segment.

**4.2.2** During pre-fill, Station MUST decode and send frames as fast as possible (no Clock A sleep) until:
- Buffer reaches target ratio, OR
- Pre-fill timeout is reached (default 5 seconds), OR
- Frame limit is reached (~470 frames ≈ 10 seconds of audio)

**4.2.3** Pre-fill MUST NOT modify Clock A timeline. Segment timing MUST remain wall-clock based regardless of pre-fill activity.

**4.2.4** Station MUST exit pre-fill and transition to normal PID-controlled pacing when exit conditions are met. Transition MUST be smooth (no audible artifacts, no frame drops).

**4.2.5** Pre-fill MUST be observable via logs. Station MUST log pre-fill entry, buffer ratio at entry, and pre-fill exit with final buffer ratio.

### 4.3 PID Controller Expectations

**4.3.1** When PID controller is enabled, Station MUST poll Tower buffer status periodically (non-blocking) during decode loop.

**4.3.2** PID controller MUST adjust Clock A sleep time based on buffer fill error (target - actual). Control direction MUST be correct:
- Low buffer (positive error) → Positive adjustment → More sleep → Slower decode
- High buffer (negative error) → Negative adjustment → Less sleep → Faster decode

**4.3.3** PID controller MUST handle edge cases without oscillation or instability:
- Small dt (< 1ms): D-term disabled
- dt = 0: D-term disabled, no division by zero
- Buffer ratio extremes (0.0, 1.0): Handled without oscillations
- Tower unavailability: Falls back to Clock A base pacing, resets integral

**4.3.4** PID controller MUST NOT cause decode rate to exceed real-time playback rate during normal operation (except during pre-fill).

**4.3.5** PID controller state (integral sum, previous error, current adjustment) MUST be observable via logs or metrics.

### 4.4 No-Artifact Guarantees

**4.4.1** Buffer transitions (pre-fill to normal, normal to pre-fill) MUST NOT cause audible artifacts (pops, clicks, silence gaps, or duplicated audio).

**4.4.2** PID controller adjustments MUST NOT cause audible artifacts. Sleep time adjustments MUST be smooth and gradual.

**4.4.3** Station MUST NOT rewind, skip, or duplicate PCM frames during buffer management operations.

**4.4.4** Tower MUST NOT emit invalid MP3 frames or silence gaps during buffer state transitions.

---

## 5️⃣ Failure & Restart Resilience

### 5.1 Station Restart

**5.1.1** When Station restarts, Tower MUST transition to fallback audio (grace period → file/tone) without manual intervention.

**5.1.2** Station MUST recover to normal operation when restarted, including:
- Reconnecting to Tower PCM socket
- Resuming decode and PCM transmission
- Re-establishing buffer management (pre-fill if needed, PID control)

**5.1.3** Station restart MUST NOT cause Tower to emit invalid MP3 frames or extended silence (> 1.5 seconds grace period).

**5.1.4** Station MUST log restart events with context (time, active segment type if known, queue state if available).

### 5.2 Tower Restart

**5.2.1** When Tower restarts, Station MUST continue decoding and attempting PCM transmission. Station MUST NOT stop or error when Tower is unavailable.

**5.2.2** Tower MUST recover to normal operation when restarted, including:
- Re-initializing PCM buffer
- Starting encoder subprocess
- Accepting PCM frames from Station
- Transitioning from fallback to Program PCM when Station reconnects

**5.2.3** Tower restart MUST NOT cause extended silence in output (> 1.5 seconds). Tower MUST engage fallback immediately if Station is not yet connected.

**5.2.4** Tower MUST log restart events with context (time, buffer state, encoder state).

### 5.3 FFmpeg Process Crashes

**5.3.1** When FFmpeg encoder subprocess crashes, EncoderManager MUST automatically restart the subprocess without manual intervention.

**5.3.2** Encoder restart MUST occur within the grace period (1.5 seconds default). Tower MUST NOT emit extended silence during encoder restart.

**5.3.3** EncoderManager MUST maintain MP3 stream continuity across encoder restarts. New encoder MUST resume encoding from the next tick without frame loss or discontinuity.

**5.3.4** EncoderManager MUST log encoder crashes and restarts with timestamps and error details.

**5.3.5** When FFmpeg decoder subprocess crashes in Station, PlayoutEngine MUST automatically restart the decoder and resume decode from the current segment position (if possible), otherwise skip cleanly to next segment.

### 5.4 PCM Ingest Disconnection

**5.4.1** When Station PCM socket disconnects, Tower MUST detect disconnection within the grace period (1.5 seconds default).

**5.4.2** Tower MUST transition to fallback audio (file/tone) immediately after grace period expires.

**5.4.3** Tower MUST log PCM disconnection events with timestamps.

**5.4.4** When Station PCM socket reconnects, Tower MUST transition back to Program PCM without manual intervention and without audible artifacts.

### 5.5 Network Socket Disconnection

**5.5.1** When network socket between Station and Tower disconnects, both components MUST handle disconnection gracefully:
- Station: Continue decode operations, attempt reconnection, log disconnection
- Tower: Transition to fallback, continue encoding, log disconnection

**5.5.2** Station MUST attempt automatic reconnection to Tower PCM socket without manual intervention.

**5.5.3** Tower MUST accept reconnection from Station and resume Program PCM transmission without manual intervention.

**5.5.4** Reconnection MUST NOT cause extended silence (> 1.5 seconds grace period) or audible artifacts.

### 5.6 System Resource Constraints

**5.6.1** Under CPU load, Station decode pacing MUST slow down (via Clock A sleep) rather than drop frames or skip segments.

**5.6.2** Under memory pressure, Tower MUST continue encoding and emitting MP3 frames. Tower MUST NOT crash or deadlock due to memory constraints.

**5.6.3** Under I/O load, file fallback MUST continue operating (pre-decoded frames in memory). File fallback MUST NOT block on disk I/O during normal operation.

**5.6.4** System resource constraints MUST be observable via logs. Components MUST log when resource constraints affect operation.

---

## 6️⃣ Observability Requirements

### 6.1 Logging Requirements

**6.1.1** All components MUST write logs to deterministic paths:
- Tower components: `/var/log/retrowaves/tower.log`
- Station components: `/var/log/retrowaves/station.log`
- FFmpegSupervisor: `/var/log/retrowaves/ffmpeg.log`

**6.1.2** Logging MUST be non-blocking. Log operations MUST NOT block audio tick loops, decode loops, or PCM transmission.

**6.1.3** Logging MUST handle log rotation gracefully (WatchedFileHandler or equivalent). Log rotation MUST NOT cause log loss or component crashes.

**6.1.4** Components MUST log at minimum:
- Startup and shutdown events
- Fallback source transitions (with timestamps and reason codes)
- Buffer state changes (pre-fill entry/exit, buffer ratio changes)
- Process crashes and restarts (FFmpeg encoder/decoder)
- Network disconnections and reconnections
- PID controller state changes (if enabled)
- Segment lifecycle (start, progress, completion)

**6.1.5** Logs MUST include timestamps with sufficient precision (millisecond or better) for timing analysis.

### 6.2 Event Emission

**6.2.1** Station MUST emit events via `/tower/events/ingest` endpoint for:
- `segment_started` (with type, path, metadata)
- `segment_progress` (at least once per second during playback)
- `segment_finished` (with type and duration)
- `station_underflow` (when buffer underflows)
- `station_overflow` (when frames are dropped)

**6.2.2** Tower MUST broadcast events to WebSocket clients via `/tower/events` endpoint for all events received from Station.

**6.2.3** Event emission MUST be non-blocking. Event operations MUST NOT block audio tick loops, decode loops, or PCM transmission.

**6.2.4** Events MUST include timestamps with sufficient precision (millisecond or better).

### 6.3 Health & Status Endpoints

**6.3.1** Tower MUST provide `GET /health` endpoint that returns 200 OK when service is running, 503 when service is unhealthy.

**6.3.2** Tower MUST provide `GET /status` endpoint that returns JSON with:
- Encoder health (FFmpegSupervisor status)
- Buffer occupancy (PCM buffer fill ratio, MP3 buffer state if applicable)
- Number of connected clients
- Current source (program/tone/silence/file)
- Uptime and restart counts

**6.3.3** Status endpoints MUST NOT interfere with audio tick loop. Status queries MUST be non-blocking and thread-safe.

**6.3.4** Status endpoints MUST return responses within 100ms (target) to avoid blocking clients.

### 6.4 Buffer Observability

**6.4.1** Tower MUST provide `GET /tower/buffer` endpoint that returns:
- Current buffer fill ratio (0.0-1.0)
- Buffer capacity (frames or bytes)
- Buffer state (filling, stable, draining, empty, full)

**6.4.2** Buffer endpoint MUST be queryable without blocking the audio tick loop.

**6.4.3** Buffer status MUST be logged periodically (at least on state changes: empty, full, pre-fill entry/exit).

### 6.5 Metrics for Validation

**6.5.1** System MUST provide sufficient observability to validate all Phase 1.0 requirements via:
- Log analysis (automated or manual)
- Event stream analysis
- Health endpoint polling
- Audio capture analysis (MP3 stream continuity, artifact detection)

**6.5.2** No manual inspection or UI access is required to validate Phase 1.0 compliance. All requirements MUST be provable via logs, events, endpoints, or automated test harness.

---

## Validation Criteria

Phase 1.0 is considered complete when:

1. All requirements in Sections 1-6 are implemented and verified
2. All requirements are testable via automated tests, log analysis, or audio capture
3. System demonstrates continuous MP3 output under all failure scenarios (Station restart, Tower restart, FFmpeg crashes, network disconnections)
4. System demonstrates proper fallback behavior (grace period, file/tone fallback, seamless transitions)
5. System demonstrates correct two-clock operation (Clock A independent of Clock B, wall-clock based segment timing)
6. System demonstrates buffer stability (pre-fill, PID control, no artifacts during transitions)
7. All observability requirements are met (logs, events, health endpoints sufficient to prove compliance)

---

## Document Status

This document defines Phase 1.0 completion criteria only. It does not define implementation details, architecture decisions, or future enhancements.

All requirements use MUST / MUST NOT / SHOULD language per RFC 2119 semantics.

