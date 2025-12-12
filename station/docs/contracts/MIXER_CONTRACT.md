# Mixer Contract

## Purpose

Defines the gain/combination layer. Mixer applies gain adjustments and combines audio streams (if multiple sources are mixed).

---

## MX1 — Guarantees

### MX1.1 — Gain Application

**MUST** apply gain accurately per frame.

- Gain is applied as dB adjustment (converted to linear multiplier)
- Gain is applied to each sample in the frame
- Gain application must not introduce clipping (unless intentional)
- Gain from AudioEvent.gain is applied to each frame

### MX1.2 — Timing Preservation

**MUST** preserve timing (1:1 input/output frame count).

- One input frame produces exactly one output frame
- No frame dropping or duplication
- Frame boundaries are preserved

### MX1.3 — Latency

**MUST NOT** introduce latency or buffering beyond 1 frame.

- Mixer processes frames immediately (no buffering)
- Maximum latency is one frame (21.333ms)
- No accumulation or delay

---

## MX2 — Prohibitions

### MX2.1 — Prohibited Operations

**MUST NOT**:

- Alter playout order (order is determined by queue)
- Change file selection (selection is DJEngine's responsibility)
- Perform ducking or overlays unless explicitly configured
  - Mixer applies gain only
  - No automatic ducking, crossfading, or effects
  - Effects must be explicitly configured if needed

---

## LOG — Logging and Observability

### LOG1 — Log File Location
Mixer **MUST** write all log output to `/var/log/retrowaves/station.log`.

- Log file path **MUST** be deterministic and fixed
- Log file **MUST** be readable by the retrowaves user/group
- Mixer **MUST NOT** require elevated privileges at runtime to write logs

### LOG2 — Non-Blocking Logging
Logging operations **MUST** be non-blocking and **MUST NOT** interfere with frame processing.

- Logging **MUST NOT** block gain application
- Logging **MUST NOT** delay frame output
- Logging **MUST NOT** affect latency requirement (MX1.3)
- Logging **MUST NOT** affect timing preservation (MX1.2)
- Logging failures **MUST** degrade silently (stderr fallback allowed)

### LOG3 — Rotation Tolerance
Mixer **MUST** tolerate external log rotation without crashing or stalling.

- Mixer **MUST** assume logs may be rotated externally (e.g., via logrotate)
- Mixer **MUST** handle log file truncation or rename gracefully
- Mixer **MUST NOT** implement rotation logic in application code
- Mixer **MUST** reopen log files if they are rotated (implementation-defined mechanism)
- Rotation **MUST NOT** cause frame processing interruption

### LOG4 — Failure Behavior
If log file write operations fail, Mixer **MUST** continue processing frames normally.

- Logging failures **MUST NOT** crash the process
- Logging failures **MUST NOT** interrupt gain application
- Logging failures **MUST NOT** interrupt frame output
- Mixer **MAY** fall back to stderr for critical errors, but **MUST NOT** block on stderr writes

---

## Required Tests

This contract requires the following logging compliance tests:

- LOG1 — Log File Location
- LOG2 — Non-Blocking Logging
- LOG3 — Rotation Tolerance
- LOG4 — Failure Behavior

See `tests/contracts/LOGGING_TEST_REQUIREMENTS.md` for test specifications.

---

## Implementation Notes

- Mixer is stateless (no memory between frames)
- Gain is applied per-frame using AudioEvent.gain
- Mixer operates on PCM frames (4096 bytes, 1024 samples)
- Mixer output goes to OutputSink
- Mixer must be real-time and non-blocking






