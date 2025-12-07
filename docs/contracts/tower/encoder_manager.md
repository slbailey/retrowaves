# Encoder Manager Contract

This document specifies the contract for the EncoderManager component in the Tower encoding subsystem.

## Overview

The EncoderManager is responsible for:
- Coordinating between AudioPump (PCM input) and FFmpegSupervisor (MP3 output)
- Managing encoder state transitions
- Providing continuous MP3 frames to clients via `next_frame()`
- Routing PCM to the supervisor
- Generating fallback frames when needed

## Continuous Output Guarantee

### M19. Continuous fallback during boot

While the encoder is in BOOTING state and before valid PCM has been admitted, EncoderManager.next_frame() MUST return a valid fallback frame (tone or silence) on every call. It MUST NOT return None, and it MUST NOT block.

During BOOTING, EncoderManager.next_frame() MUST return a valid fallback frame (tone or silence). The contract does not guarantee the acoustic content of the frame, only that a valid frame is returned on every tick without blocking.

**Rationale**: During BOOTING, client-facing output is fallback, not guaranteed silence. The encoder is allowed to output tone during boot. Tests that require "continuous silence during boot" are wrong for real radio. The correct invariant is: "continuous fallback frames, no None, frame size correct."

### M20. Grace period for PCM detection

A grace period (e.g., ~1 s) MAY be applied before treating the absence of PCM as loss. During this grace period, the broadcast output MUST remain continuous via fallback frames.

**Rationale**: This allows for normal startup delays without triggering failure conditions.

### M21. PCM forwarding independent of supervisor state

Once PCM meets the admission criteria, the manager MUST forward PCM to the supervisor's writer thread on every tick, even if the supervisor is still in BOOTING state. The supervisor is responsible for turning this PCM into MP3 frames as soon as it is ready.

**Rationale**: PCM must be forwarded to FFmpeg even during BOOTING. BOOTING vs RUNNING only affects how we interpret encoder status, not whether we write PCM.

### M22. No dead air at startup

From the moment the encoder is started, clients consuming the MP3 stream MUST receive a continuous sequence of valid MP3 frames sourced from either fallback or program PCM. The transition from fallback to PCM MUST NOT introduce gaps.

**Rationale**: No dead air, ever (Broadcast Grade). The MP3 stream must always have audio frames for clients to pull, even if FFmpeg is still booting, no PCM from upstream has arrived, or FFmpeg restarts.

## State Management

### M1. Encoder state enumeration

The EncoderManager MUST maintain the following states:
- STOPPED: Encoder is not running
- BOOTING: Encoder is starting up, supervisor may be in BOOTING state
- RUNNING: Encoder is operational, supervisor is RUNNING
- RESTARTING: Encoder is recovering from a failure
- FAILED: Encoder has failed and cannot recover

### M2. State transitions

State transitions MUST follow this flow:
- STOPPED → BOOTING (on start())
- BOOTING → RUNNING (when supervisor enters RUNNING and PCM is available)
- RUNNING → RESTARTING (on supervisor failure)
- RESTARTING → BOOTING (after restart attempt)
- Any state → FAILED (on persistent failure)
- Any state → STOPPED (on stop())

## PCM Handling

### M3. PCM admission criteria

The manager MUST apply admission criteria to PCM frames before forwarding to the supervisor. Invalid or malformed frames MUST be rejected.

### M4. PCM routing

Valid PCM frames MUST be routed to the supervisor's `write_pcm()` method on every AudioPump tick (24 ms cadence), regardless of supervisor state.

## MP3 Frame Delivery

### M5. next_frame() contract

The `next_frame()` method MUST:
- Return a valid MP3 frame (never None) on every call
- Not block the caller
- Return frames from the MP3 buffer when available
- Return fallback frames when buffer is empty (per M19)

### M6. Frame size consistency

All returned frames MUST have consistent size appropriate for the configured bitrate and sample rate.

## Fallback Behavior

### M7. Fallback frame generation

When the MP3 buffer is empty or the encoder is in BOOTING state, the manager MUST generate fallback frames. Fallback frames MAY be:
- Silence (zero samples)
- Tone (test tone at configured frequency)

**Rationale**: Fallback ensures no dead air. The specific type (silence vs tone) is an implementation detail.

### M8. Fallback during restarts

During encoder restarts, the manager MUST continue providing fallback frames to maintain continuous output (per M22).

## Supervisor Coordination

### M9. Supervisor lifecycle

The manager MUST create and manage the FFmpegSupervisor instance, including:
- Starting the supervisor on encoder start
- Stopping the supervisor on encoder stop
- Handling supervisor state changes

### M10. Supervisor state monitoring

The manager MUST monitor supervisor state and update its own state accordingly. Supervisor state changes MUST trigger appropriate manager state transitions.

## Error Handling

### M11. Error recovery

On supervisor failure, the manager MUST:
- Transition to RESTARTING state
- Continue providing fallback frames (per M8)
- Coordinate supervisor restart with backoff
- Log error details

### M12. Persistent failure handling

If the supervisor fails to recover after maximum restart attempts, the manager MUST:
- Transition to FAILED state
- Continue providing fallback frames (per M22)
- Log persistent failure

## Threading

### M13. Thread safety

All public methods MUST be thread-safe. The manager MUST coordinate between:
- AudioPump thread (calling next_frame())
- Supervisor writer thread (receiving PCM)
- Supervisor drain threads (producing MP3)

### M14. Non-blocking operations

All operations MUST be non-blocking to prevent stalls in the audio pipeline.

## Configuration

### M15. Configurable parameters

The manager MUST support configuration of:
- stall_threshold_ms: Threshold for detecting encoder stalls (default: 2000 ms)
- backoff_schedule_ms: Exponential backoff schedule for restarts
- max_restarts: Maximum restart attempts before FAILED state
- allow_ffmpeg: Whether to use FFmpeg (vs mock encoder for testing)

## Integration Points

### M16. AudioPump integration

The manager MUST integrate with AudioPump, which:
- Ticks every 24 ms (strict cadence)
- Calls `next_frame()` once per tick
- This is the only "clock" for the encoder system

### M17. Supervisor integration

The manager MUST integrate with FFmpegSupervisor, which:
- Receives PCM via `write_pcm()`
- Produces MP3 frames via stdout drain thread
- Manages FFmpeg process lifecycle

## Broadcast Grade Requirements

### M18. Broadcast grade compliance

The manager MUST comply with broadcast grade requirements:
- No dead air (per M22)
- Continuous frame delivery (per M5)
- Graceful degradation (per M7, M8)
- Self-healing (per M11)

See also: `docs/contracts/tower/broadcast_grade.md`
