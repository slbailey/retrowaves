# FFmpeg Supervisor Contract

This document specifies the contract for the FFmpeg Supervisor component in the Tower encoding subsystem.

## Overview

The FFmpeg Supervisor is responsible for:
- Managing the FFmpeg process lifecycle
- Writing PCM data to FFmpeg's stdin
- Reading MP3 frames from FFmpeg's stdout
- Detecting encoder stalls and failures
- Performing self-healing through restarts

## Frame Timing and Cadence

### S15. Frame interval tracking

The supervisor MUST track the arrival time of each MP3 frame using a monotonic clock. It MUST record the time of the last frame and compute the interval to detect stalls or encoder misbehavior.

**Rationale**: While PCM input cadence is strict (24 ms), FFmpeg/libmp3lame output cadence is NOT strict. The encoder may emit frames in batches (e.g., every ~48 ms or more), which is normal behavior. Frame interval tracking is used solely for stall detection, not for enforcing strict timing.

### S16. Stall detection threshold

Supervisor MUST track MP3 output intervals to detect stalls. It MUST treat intervals greater than STALL_THRESHOLD_MS (e.g., 250 ms) as a stall. Shorter intervals, including normal encoder batching (e.g., ~48 ms), MUST NOT be considered violations.

**Rationale**: Encoder batching is expected behavior. Only extended gaps indicate a genuine stall or encoder failure.

### S17. Stall handling

When a stall is detected, the supervisor MUST:

1. Log a warning that includes the measured interval.
2. Transition into the appropriate failure/restart path (per S11/S13) without interrupting client-facing MP3 output from the buffer.

**Rationale**: Client-facing output must remain continuous even during encoder recovery.

### S18. Non-strict output cadence

The supervisor MUST NOT enforce a strict 1:1 relationship between PCM frame cadence and MP3 frame cadence. It MUST tolerate encoder batching and variable output intervals, as long as STALL_THRESHOLD_MS is not exceeded.

**Rationale**: This reflects real-world encoder behavior where libmp3lame may batch frames for efficiency.

## Process Lifecycle

### S5. Process startup

On initialization, FFmpegSupervisor MUST start the ffmpeg process with the configured command.

### S6. Process monitoring

The supervisor MUST continuously monitor the ffmpeg process for:
- Process termination (poll() returns non-None)
- Stderr output indicating errors
- Stall conditions (per S16)

### S7. Startup timeout

The supervisor MUST apply a startup timeout (configurable via TOWER_FFMPEG_STARTUP_TIMEOUT_MS, default 1500ms). If the first MP3 frame is not received within this timeout, the supervisor MUST treat this as a failure and restart.

### S11. Failure detection

The supervisor MUST detect the following failure conditions:
- Process termination
- Stall detection (per S16/S17)
- Startup timeout (per S7)

### S13. Restart behavior

On failure detection, the supervisor MUST:
1. Preserve MP3 buffer contents
2. Restart the encoder with exponential backoff
3. Continue serving MP3 frames from buffer during restart
4. Log restart events with appropriate detail

## PCM Writing

### S7.1. PCM forwarding

The supervisor MUST accept PCM frames via `write_pcm()` and forward them to FFmpeg's stdin, regardless of supervisor state (BOOTING or RUNNING).

Supervisor MUST accept PCM writes during BOOTING. The BOOTING/RUNNING distinction applies only to encoder output readiness, not to input acceptance.

**Rationale**: PCM must be forwarded to FFmpeg even during BOOTING state. The BOOTING vs RUNNING distinction only affects how we interpret encoder status, not whether we write PCM.

### S7.3. Boot priming burst

The priming burst MUST be written synchronously to stdin before the PCM writer thread begins pacing. This ensures deterministic startup behavior.

**Rationale**: The burst is synchronous and the writer thread starts only after execution of burst, ensuring deterministic startup behavior.

### S7.4. PCM cadence

PCM cadence is driven by AudioPump/EncoderManager (strict 24 ms), not the Supervisor. The Supervisor is responsible for writing PCM as it arrives.

## MP3 Output

### S3. Non-blocking output

The supervisor MUST never block the MP3 frame delivery path. Frame reading and buffer management must be non-blocking.

### S4. Buffer preservation

During restarts, the supervisor MUST preserve existing MP3 buffer contents to ensure continuous client-facing output.

## I/O Behavior

### S14. Blocking I/O

FFmpeg stdin/stdout MUST use blocking file descriptors. The supervisor relies on threads and small writes to maintain responsiveness.

**Rationale**: This avoids Python 3.11 non-blocking pipe issues and simplifies the implementation.

### S14.1-S14.7. Drain threads

The supervisor MUST maintain separate daemon threads for:
- Stderr capture (S14.1-S14.5)
- Stdout MP3 frame reading (S14.7)

These threads MUST be daemon threads and MUST NOT block process termination.

## State Management

### S6A. BOOTING state

The supervisor enters BOOTING state after process startup and remains in BOOTING until the first MP3 frame is received. During BOOTING, PCM forwarding continues (per S7.1).

### S19. State transitions

The supervisor MUST manage state transitions:
- STARTING → BOOTING (after process creation)
- BOOTING → RUNNING (after first MP3 frame)
- RUNNING → RESTARTING (on failure)
- RESTARTING → BOOTING (after restart)
- Any state → FAILED (on persistent failure)
- Any state → STOPPED (on explicit stop)

## Source Agnosticism

### S22A. Source-agnostic PCM handling

The supervisor MUST NOT know about noise/silence generation. It is source-agnostic and treats all valid Tower-format PCM frames identically. PCM source selection (silence, tone, or live) is handled by AudioPump/EncoderManager.

## Diagnostics

### S21.3. Stderr capture

The supervisor MUST capture and log FFmpeg stderr output with a [FFMPEG] prefix for diagnostics. Stderr capture MUST be limited in size to prevent memory leaks.

## Constants

- FRAME_SIZE_SAMPLES: 1152
- SAMPLE_RATE: 48000
- FRAME_INTERVAL_MS: 24 (PCM input cadence)
- FRAME_BYTES: 4608 (1152 samples × 2 channels × 2 bytes)
- STALL_THRESHOLD_MS: Configurable, default 250 ms (example)
- STARTUP_TIMEOUT_MS: Configurable via TOWER_FFMPEG_STARTUP_TIMEOUT_MS, default 1500 ms
