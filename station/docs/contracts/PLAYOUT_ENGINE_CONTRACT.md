# PlayoutEngine Contract

## Purpose

Defines the real-time audio engine that executes the DO phase. PlayoutEngine is responsible for decoding and playing audio segments.

**Cross-Contract References:**
- **Two-Clock Architecture:** See `STATION_TOWER_PCM_BRIDGE_CONTRACT.md` Section C for the complete Two-Clock Model specification
- **Tower Buffer API:** See `NEW_TOWER_RUNTIME_CONTRACT.md` T-BUF for the `/tower/buffer` endpoint specification (used by PE6 PID controller)

---

## PE1 — Segment Lifecycle

### PE1.1 — Single Segment Playback

**MUST** decode and play exactly one segment at a time.

- Only one segment is active at any time
- Next segment starts only after current segment finishes
- No concurrent decoding or playback

### PE1.2 — Segment Start Event

**MUST** emit `on_segment_started` before first frame.

- Event is emitted synchronously before audio begins
- Event triggers THINK phase for next segment
- Event includes the AudioEvent being played

### PE1.3 — Segment Finish Event

**MUST** emit `on_segment_finished` after last frame.

- Event is emitted synchronously after audio ends
- Event triggers DO phase (queue execution)
- Event includes the AudioEvent that finished

---

## PE2 — Decision Prohibitions

### PE2.1 — Prohibited Operations

**PlayoutEngine** **MUST NOT**:

- Pick songs (song selection is DJEngine's responsibility)
- Insert IDs (ID insertion is DO phase's responsibility)
- Modify scheduling (scheduling is queue's responsibility)
- Generate any audio content (content comes from files only)

---

## PE3 — Two-Clock Architecture

### PE3.1 — Station Playback Clock (Clock A)

**Station MUST maintain its own wall-clock-based content playback clock.**

This clock is based on `time.monotonic()` and measures **content time**, NOT PCM output cadence.

**Station Playback Clock is responsible for:**
- Segment progression
- DJ THINK/DO logic timing
- Breaks, intros, outros timing
- Knowing how long a song has "played"
- Maintaining real-time program flow
- **Decode pacing metronome** (Clock A) to ensure songs play at real duration

**Station MAY use Clock A for decode pacing:**
- Station may use an internal timer to pace consumption of decoded PCM frames
- This pacing must target ≈21.333 ms per 1024-sample frame for real-time MP3 playback
- This metronome is for local playback correctness only — ensuring songs take their real duration (e.g., a 200-second MP3 takes 200 seconds to decode)
- Clock A must be monotonic and maintain wall-clock fidelity
- Clock A may observe Tower buffer status via `/tower/buffer` endpoint exclusively for the optional Clock A PID controller (PE6)
- Clock A must never alter pacing based on socket success/failure

**Playback duration MUST be measured as:**
```python
elapsed = time.monotonic() - segment_start
```

**Station MUST NOT:**
- Use decoder speed to determine content duration
- Use number of frames decoded to advance segments
- Use number of frames sent to determine segment timing
- Use PCM buffer depth to influence segment timing
- Use Tower consumption rate to determine segment timing

**Segment duration rules:**
- Segments MUST be tied ONLY to real-time wall clock
- Segment ends when: `elapsed_time >= expected_duration_seconds`
- NOT based on: frames decoded, frames sent, decoder speed, PCM buffer depth, Tower consumption rate

### PE3.2 — Tower PCM Clock (Clock B)

**Tower's AudioPump (21.333ms) is the ONLY authoritative PCM timing source for broadcast timing.**

**Station MUST NOT (Tower-synchronized pacing is FORBIDDEN):**
- Attempt to match Tower's AudioPump timing
- Adjust timing based on Tower ingestion behavior
- Slow down or speed up based on socket backpressure
- Attempt cadence alignment or drift correction relative to Tower
- Try to match PCM rate
- Predict PCM rate
- Influence PCM rate
- Derive timing from PCM writes
- Use PCM write success/failure to influence segment timing or decode pacing

**Tower PCM Clock is responsible for:**
- Actual PCM pacing (strict 21.333ms)
- EncoderManager timing
- Consistent audio output timing
- **Sole authority for broadcast timing**

**Clock A (Station decode metronome) and Clock B (Tower AudioPump) are independent:**
- Clock A paces decode consumption for local playback correctness
- Clock B paces broadcast output
- Station-to-Tower interface remains asynchronous, non-blocking, and timing-agnostic

### PE3.3 — Decoder Output Rules

**Station MAY use Clock A (decode pacing metronome) to pace frame consumption.**

**Decode pacing rules (Clock A):**
- Station may pace consumption of decoded PCM frames using Clock A
- After decoding a PCM frame, Station should:
  - `next_frame_time += FRAME_DURATION`  # ~21.333 ms
  - `sleep(max(0, next_frame_time - now))`  # allow drift correction
- Clock A must be monotonic and maintain wall-clock fidelity
- Clock A may observe Tower buffer status via `/tower/buffer` endpoint exclusively for the optional Clock A PID controller (PE6)
- Clock A must never alter pacing based on socket success/failure

**Socket write rules (MUST remain non-blocking):**
- Even if Clock A decode metronome is used, `write()` must remain non-blocking and fire immediately
- Station MUST NOT apply pacing to the socket write
- Socket writes must fire as soon as frames are available (after decode pacing, if used)

**FORBIDDEN pacing approaches:**
- Station MUST NOT apply Tower-synchronized pacing (see PE3.2)
- Station MUST NOT attempt to match Tower's AudioPump cadence

**ALLOWED adaptive pacing (when PID controller is enabled):**
- Station MAY use adaptive Clock A pacing based on Tower buffer status (per PE6)
- PID controller adjusts decode pacing to maintain Tower buffer at target fill level
- PID controller does NOT affect segment timing, Clock B, or Tower-synchronized pacing

**Segment timing invariant:**
- Segment timing = wall clock only
- Station may rely on Clock A + file duration metadata to ensure its internal timeline advances in real time
- DJ THINK/DO cycle must continue to use wall-clock timing, not Tower timing
- Playback duration must reflect actual MP3 duration, independent of Tower ingestion

### PE3.4 — No Prefetching

**MUST NOT** prefetch or concurrently decode beyond the current segment.

- Only current segment is decoded
- Next segment decoding begins only after current finishes
- No background decoding or buffering beyond current segment

### PE3.5 — Error Propagation

**MUST** propagate decoder errors upward as segment termination only.

- Decoder errors cause segment to end (not station crash)
- Errors are logged but do not stop playout
- Next segment begins normally after error

---

## PE4 — Heartbeat Events

PlayoutEngine **MUST** emit control-channel events for observability. These events are purely observational and **MUST NOT** influence playout behavior or timing decisions.

### PE4.1 — New Song Event

**MUST** emit `new_song` event when a song segment starts playing.

- Event **MUST** be emitted synchronously before audio begins
- Event **MUST NOT** block playout thread
- Event **MUST** include metadata:
  - `file_path`: Path to the MP3 file
  - `title`: Song title (from MP3 metadata, if available, otherwise None)
  - `artist`: Artist name (from MP3 metadata, if available, otherwise None)
  - `album`: Album name (from MP3 metadata, if available, otherwise None)
  - `duration`: Duration in seconds (from MP3 metadata, if available, otherwise None)
- MP3 metadata **MUST** be retrieved from the `AudioEvent.metadata` field, which was populated during the THINK phase
- If metadata is not available in `AudioEvent.metadata`, it **MAY** be extracted during DO phase as a fallback (though this should not occur in normal operation)
- Event **MUST** be emitted from the playout thread
- Event **MUST NOT** modify queue or state
- Event **MUST NOT** rely on Tower timing or state
- Event **MUST** be emitted for every song that starts playing

### PE4.2 — DJ Talking Event

**MUST** emit `dj_talking` event when DJ starts talking between songs.

- Event **MUST** be emitted synchronously before audio begins
- Event **MUST NOT** block playout thread
- Event **MUST** include empty metadata: `{}`
- Event **MUST** be emitted from the playout thread
- Event **MUST NOT** modify queue or state
- Event **MUST NOT** rely on Tower timing or state
- Event **MUST** be emitted only once when talking starts, even if multiple talking MP3 files are strung together consecutively
- Event **MUST NOT** be emitted again until a non-talk segment (e.g., song) starts, at which point the talking sequence flag is reset

### PE4.3 — Event Emission Rules

All heartbeat events **MUST** follow these behavioral rules:

- **Non-blocking**: Events **MUST NOT** block the playout thread or delay PCM frame processing
- **Observational only**: Events **MUST NOT** influence segment timing, decode pacing, or queue operations
- **Station-local**: Events **MUST NOT** rely on Tower timing, Tower state, or PCM write success/failure
- **Clock A only**: Events **MUST** use Clock A (wall clock) for all timing measurements
- **No state mutation**: Events **MUST NOT** modify queue, rotation history, or any system state (except internal talking sequence tracking)
- **Lifecycle boundaries**: Events **MUST** be emitted at the correct lifecycle boundaries (when segments start)
- **Metadata completeness**: Events **MUST** include all required metadata fields
  - `compensation_applied`: Boolean indicating whether compensation was applied
- Event **MUST** be emitted from Clock A pacing layer (if decode pacing is used)
- Event **MUST NOT** modify queue or state
- Event **MUST NOT** rely on Tower timing or state
- Event **MUST** be purely observational

---

## PE5 — Optional Station Timebase Drift Compensation

Station **MAY** implement optional timebase drift compensation within Clock A. This compensation operates purely within Station's local clock domain and **MUST NOT** attempt to match or synchronize with Tower's Clock B.

### PE5.1 — Drift Definition

**Drift** is defined as the difference between:
- Expected decode time (based on Clock A metronome pacing)
- Actual decode time (based on wall clock measurement)

Drift is measured in milliseconds and represents how far ahead or behind the decode metronome is relative to wall clock.

### PE5.2 — Drift Detection

If drift compensation is enabled, Station **MUST** detect drift by comparing:
- Clock A decode metronome time (expected frame time)
- Wall clock time (`time.monotonic()`)

Drift **MUST** be calculated using only Station-local monotonic time. Station **MUST NOT** use Tower timing, PCM write success/failure, or any Tower state to detect drift.

### PE5.3 — Permitted Compensation

If drift compensation is enabled, Station **MAY** adjust Clock A decode metronome pacing within very small allowed bounds.

**Permitted adjustments:**
- Station **MAY** adjust decode metronome pacing to correct small drift (< threshold)
- Station **MAY** use proportional correction within bounds (e.g., ±1% of frame duration)
- Station **MAY** apply correction gradually over multiple frames

**Forbidden adjustments:**
- Station **MUST NOT** attempt to match Tower PCM clock (Clock B)
- Station **MUST NOT** apply adaptive pacing based on PCM ingestion feedback (for drift compensation)
- Station **MUST NOT** use Tower state to influence compensation
- Station **MUST NOT** exceed permitted compensation bounds (implementation-defined threshold)
- Station **MUST NOT** affect segment duration logic (segments still wall clock driven)
- **Note:** This restriction applies only to drift compensation. It does not prohibit the Clock A PID controller described in PE6, which is allowed to use Tower buffer telemetry.

### PE5.4 — Segment Duration Invariant

Drift compensation **MUST NOT** affect segment duration logic.

- Segment duration **MUST** remain wall clock driven
- Segment ends when: `elapsed_time >= expected_duration_seconds` (measured via wall clock)
- Drift compensation **MUST NOT** alter segment timing or THINK/DO cadence
- Segment duration **MUST** reflect actual MP3 duration, independent of decode pacing adjustments

### PE5.5 — Drift Reporting

If drift compensation is enabled, Station **MUST** emit `decode_clock_skew` event (per PE4.5) whenever drift exceeds the permitted threshold.

- Event **MUST** be emitted when drift is detected and compensation is applied
- Event **MUST** include drift magnitude and compensation details
- Event **MUST** be purely observational (does not influence playout)

### PE5.6 — Optional Implementation

Drift compensation is **OPTIONAL** and implementation-defined.

- Station **MAY** implement drift compensation
- Station **MAY** choose not to implement drift compensation
- If not implemented, Station **MUST NOT** emit `decode_clock_skew` events
- Implementation details (thresholds, correction algorithms) are implementation-defined
- Behavioral restrictions (PE5.1 through PE5.5) **MUST** be followed if compensation is implemented

### PE5.7 — Tower Independence

Drift compensation **MUST** operate independently of Tower.

- Station **MUST NOT** use Tower timing to detect or correct drift
- Station **MUST NOT** use PCM write success/failure to influence compensation
- Station **MUST NOT** attempt to synchronize with Tower's Clock B
- Station **MUST NOT** apply adaptive pacing based on Tower ingestion behavior (for drift compensation)
- All drift detection and compensation **MUST** use only Station-local monotonic time
- **Note:** This restriction applies only to drift compensation. It does not prohibit the Clock A PID controller described in PE6, which is allowed to use Tower buffer telemetry.

---

## PE6 — Optional Adaptive Buffer Management with PID Controller

Station **MAY** implement optional PID (Proportional-Integral-Derivative) controller for adaptive Clock A decode pacing based on Tower buffer status. This extends PE3.3 to allow adaptive pacing while maintaining all architectural invariants.

### PE6.1 — Scope and Architectural Alignment

**The PID controller extends Clock A (Station decode metronome) to be adaptive based on Tower buffer feedback.**

- **Clock A** remains the Station decode pacing metronome (per PE3.1, PE3.3)
- **Clock B** (Tower AudioPump) remains the sole authority for broadcast timing (per PE3.2)
- **Segment timing** remains wall-clock based and is NOT affected by PID controller (per PE3.1)
- PID controller **ONLY** adjusts decode pacing (Clock A) to prevent Tower buffer underflow/overflow
- PID controller does NOT affect segment duration, DJ THINK/DO timing, or content playback clock

**Station MAY observe Tower buffer status via `/tower/buffer` endpoint to inform Clock A pacing adjustments.**

- Station queries Tower buffer status periodically (configurable interval, default: 500ms)
- Buffer status includes: `fill`, `capacity`, `ratio` (0.0-1.0)
- Buffer status is used **ONLY** for Clock A pacing adjustment, NOT for segment timing
- If Tower buffer status is unavailable, PID controller falls back to fixed-rate Clock A pacing
- Buffer observation must be non-blocking and must not affect decode thread

**PID controller adjusts Clock A frame-to-frame sleep duration to maintain Tower buffer at target fill level.**

- Target buffer fill ratio: configurable (default: 0.5 = 50% full)
- PID controller calculates error: `error = target_ratio - current_ratio`
- PID controller calculates sleep adjustment: `sleep_adjustment = PID(error)`
- Adjusted sleep duration: `sleep_duration = base_frame_duration + sleep_adjustment`
- Sleep duration is clamped to safety limits (min/max sleep times)

### PE6.2 — PID Controller Algorithm

**Proportional term (P) responds to current buffer fill deviation from target.**

- **P term calculation:**
  ```
  P = Kp * error
  ```
  where:
  - `Kp` = Proportional gain coefficient (configurable, default: 0.1)
  - `error` = `target_ratio - current_ratio` (range: -1.0 to +1.0)
  
- **Behavior:**
  - Positive error (buffer too low): P term increases sleep duration (slows decode)
  - Negative error (buffer too high): P term decreases sleep duration (speeds decode)
  - Response is immediate and proportional to error magnitude

**Integral term (I) accumulates error over time to eliminate steady-state offset.**

- **I term calculation:**
  ```
  I = Ki * integral_sum
  integral_sum += error * dt
  ```
  where:
  - `Ki` = Integral gain coefficient (configurable, default: 0.01)
  - `integral_sum` = Accumulated error over time (initialized to 0.0)
  - `dt` = Time since last PID update (seconds)
  
- **Behavior:**
  - Accumulates persistent error to correct long-term drift
  - Prevents steady-state offset (e.g., buffer consistently at 40% when target is 50%)
  - Integral term is clamped to prevent windup (configurable limit, default: ±10.0)
  
- **Integral Windup Prevention:**
  - When sleep duration hits safety limits (min/max), integral accumulation is paused
  - This prevents integral term from growing unbounded when controller is saturated

**Derivative term (D) predicts future error based on rate of change.**

- **D term calculation:**
  ```
  D = Kd * (error - previous_error) / dt
  ```
  where:
  - `Kd` = Derivative gain coefficient (configurable, default: 0.05)
  - `previous_error` = Error from previous PID update
  - `dt` = Time since last PID update (seconds)
  
- **Behavior:**
  - Responds to rate of change in buffer fill
  - Dampens oscillations and provides predictive correction
  - Helps prevent overshoot when buffer is approaching target

**PID controller combines P, I, and D terms to calculate sleep adjustment.**

- **Combined calculation:**
  ```
  sleep_adjustment = P + I + D
  adjusted_sleep = base_frame_duration + sleep_adjustment
  ```
  where:
  - `base_frame_duration` = 21.333 ms (1024 samples / 48000 Hz)
  - `sleep_adjustment` = Combined PID output (can be positive or negative)
  
- **Final sleep duration:**
  ```
  sleep_duration = clamp(adjusted_sleep, min_sleep, max_sleep)
  ```
  where:
  - `min_sleep` = Minimum sleep duration (configurable, default: 0.0 ms)
  - `max_sleep` = Maximum sleep duration (configurable, default: 100.0 ms)

### PE6.3 — Configuration Parameters

**PID controller MUST support configurable coefficients (Kp, Ki, Kd).**

- **Kp (Proportional gain):**
  - Default: 0.1
  - Range: 0.0 to 10.0
  - Higher values = more aggressive response to current error
  - Lower values = gentler response, more stable but slower correction
  
- **Ki (Integral gain):**
  - Default: 0.01
  - Range: 0.0 to 1.0
  - Higher values = faster elimination of steady-state offset
  - Lower values = slower offset correction, less overshoot
  
- **Kd (Derivative gain):**
  - Default: 0.05
  - Range: 0.0 to 1.0
  - Higher values = stronger damping, less oscillation
  - Lower values = less damping, more responsive but potentially oscillatory

**Target buffer fill ratio MUST be configurable.**

- **Target ratio:**
  - Default: 0.5 (50% full)
  - Range: 0.1 to 0.9
  - Lower values = maintain buffer closer to empty (more aggressive)
  - Higher values = maintain buffer closer to full (more conservative)

**Sleep duration MUST be clamped to safety limits.**

- **Minimum sleep:**
  - Default: 0.0 ms (no minimum delay)
  - Range: 0.0 to 50.0 ms
  - Prevents negative sleep durations
  
- **Maximum sleep:**
  - Default: 100.0 ms (5x base frame duration)
  - Range: 10.0 to 500.0 ms
  - Prevents excessive delays that could cause decode stuttering
  
- **Integral windup limit:**
  - Default: ±10.0
  - Range: ±1.0 to ±100.0
  - Prevents integral term from growing unbounded

**PID controller MUST update at configurable intervals.**

- **Update interval:**
  - Default: 500 ms
  - Range: 100 ms to 5000 ms
  - Shorter intervals = more responsive but more CPU overhead
  - Longer intervals = less responsive but lower CPU overhead

### PE6.4 — Implementation Requirements

**Tower buffer status queries MUST be non-blocking and must not affect decode thread.**

- Buffer queries MUST use async HTTP client or timeout-limited requests
- Query timeout: configurable (default: 100 ms)
- If query fails or times out, PID controller uses last known buffer status or falls back to fixed-rate pacing
- Query failures MUST NOT block decode thread or cause frame drops

**PID controller state MUST be thread-safe.**

- PID state (error history, integral sum, previous error) MUST be protected by locks
- Buffer status updates and sleep duration calculations MUST be atomic
- Decode thread MUST read sleep duration atomically without blocking

**PID controller MUST gracefully handle Tower unavailability.**

- If Tower buffer status is unavailable:
  - PID controller falls back to fixed-rate Clock A pacing (21.333 ms per frame)
  - Integral term is reset to prevent stale accumulation
  - Controller resumes PID control when Tower buffer status becomes available again

**PID controller MUST initialize with safe defaults.**

- On startup:
  - Integral sum = 0.0
  - Previous error = 0.0
  - Sleep duration = base_frame_duration (21.333 ms)
  - Controller begins with fixed-rate pacing until first buffer status is received

### PE6.5 — Integration with PlayoutEngine

**PID controller replaces the current 3-zone buffer controller in `PlayoutEngine._play_audio_segment()`.**

- Current zone-based logic (low/normal/high zones with fixed sleep times) is replaced by PID controller
- PID controller provides continuous rate adjustment instead of discrete zone transitions
- This eliminates stuttering from zone transitions

**PID controller integrates with Clock A decode pacing metronome.**

- In `_play_audio_segment()`:
  ```python
  # Clock A: Adaptive decode pacing with PID controller
  now = time.monotonic()
  sleep_duration = pid_controller.get_sleep_duration(now)
  if sleep_duration > 0:
      time.sleep(sleep_duration)
  next_frame_time += FRAME_DURATION  # Update Clock A timeline
  ```
  
- PID controller calculates sleep duration based on:
  - Base frame duration (21.333 ms)
  - Current Tower buffer status
  - PID error terms (P, I, D)
  - Safety limits (min/max sleep)

**PID controller MUST update buffer status periodically during decode loop.**

- Buffer status is queried at configurable intervals (default: every 500 ms)
- Query happens in decode loop but MUST be non-blocking
- If query is in progress, controller uses last known buffer status
- Query failures are handled gracefully (fallback to fixed-rate pacing)

### PE6.6 — Observability and Monitoring

**PID controller MUST log state changes for observability.**

- Log PID state at configurable intervals (default: every 10 seconds):
  - Current buffer fill ratio
  - Target buffer fill ratio
  - Error (target - current)
  - P, I, D terms
  - Calculated sleep adjustment
  - Final sleep duration
  - Integral sum (for windup detection)

**PID controller MUST track performance metrics.**

- Track:
  - Number of buffer status queries
  - Number of query failures/timeouts
  - Number of times sleep duration hit safety limits (min/max)
  - Number of integral windup events
  - Average buffer fill ratio over time
  - Buffer fill ratio variance (for stability assessment)

**PID controller MAY emit control-channel events for monitoring.**

- Optional events:
  - `pid_state_update`: Emitted periodically with PID state (buffer ratio, error, terms, sleep duration)
  - `pid_limit_hit`: Emitted when sleep duration hits min/max limits
  - `pid_windup_detected`: Emitted when integral windup limit is reached

### PE6.7 — Architectural Invariants

**PID controller MUST maintain all architectural invariants from this contract.**

- ✅ **Clock A (Station decode metronome):** PID controller extends Clock A to be adaptive, but Clock A remains Station's decode pacing mechanism
- ✅ **Clock B (Tower AudioPump):** Clock B remains the sole authority for broadcast timing (unchanged)
- ✅ **Segment timing:** Segment timing remains wall-clock based and is NOT affected by PID controller
- ✅ **Socket writes:** Socket writes remain non-blocking and fire immediately (unchanged)
- ✅ **No Tower-synchronized pacing:** PID controller adjusts decode pacing based on buffer status, but does NOT attempt to match Tower's AudioPump cadence

### PE6.8 — Optional Implementation

PID controller is **OPTIONAL** and implementation-defined.

- Station **MAY** implement PID controller
- Station **MAY** choose not to implement PID controller
- If not implemented, Station uses fixed-rate Clock A pacing (21.333 ms per frame)
- When disabled, behavior matches current implementation
- Configuration allows gradual rollout and testing
- Behavioral restrictions (PE6.1 through PE6.7) **MUST** be followed if PID controller is implemented

---

## Implementation Notes

- PlayoutEngine reads from playout queue (DO phase enqueues)
- Decoding uses FFmpegDecoder (per FFmpegDecoder Contract)
- Output uses OutputSink (per OutputSink Contract)
- Mixing uses Mixer (per Mixer Contract)
- All operations must be real-time and non-blocking
- **Segment timing:** Uses wall clock (`time.monotonic()`) to measure elapsed time
- **Decode pacing:** Station may use Clock A (decode metronome) to pace frame consumption at ~21.333ms per frame
  - **Optional PID controller (PE6):** Station may use adaptive Clock A pacing based on Tower buffer status
  - **Optional drift compensation (PE5):** Station may use drift compensation within Clock A
- **PCM output:** Socket writes remain non-blocking and fire immediately (no pacing on writes)
- **Two clocks:** Clock A (Station decode metronome) for local playback correctness; Clock B (Tower AudioPump) for broadcast timing
- **PID Controller:** Create `BufferPIDController` class in `station/broadcast_core/buffer_pid_controller.py` if implementing PE6
- **Pre-Fill Stage:** Optional pre-fill stage may be implemented in `PlayoutEngine._play_audio_segment()` to build up Tower buffer before normal pacing. See Station-Tower Bridge Contract C8 for requirements.




