# FFmpegDecoder Contract

## Purpose

Defines **WHAT** the decoder must guarantee, consistent with Station's architecture. FFmpegDecoder is responsible for decoding MP3 files to PCM frames.

**Note**: MP3 input files operate at ~24ms per MP3 frame (MP3 encoder domain), but decoder output **MUST** be PCM at 21.333ms cadence (1024 samples / 48000 Hz) to match Tower's internal PCM format.

---

## FD1 — Decode Rules

### FD1.1 — PCM Format

**MUST** produce PCM frames in **48kHz s16le stereo**.

- Sample rate: 48,000 Hz
- Bit depth: 16-bit signed integer (little-endian)
- Channels: 2 (stereo)
- Frame size: 1024 samples per channel (4096 bytes per frame)
- **PCM cadence**: 21.333ms per frame (1024 samples / 48000 Hz)

**Input Format**:
- MP3 files operate at ~24ms per MP3 frame (MP3 encoder timing domain)
- Decoder converts MP3 frames to PCM frames at 21.333ms cadence

### FD1.2 — Sequential Frames

**MUST** emit frames sequentially with no reordering.

- Frames must be emitted in file order
- No frame skipping or duplication
- Frame boundaries must be preserved

### FD1.3 — End of File

**MUST** stop decoding at end of file.

- Decoder stops when file ends (no padding)
- Decoder **MAY** produce a final partial PCM frame at end-of-file (EOF).
- Partial frames **MUST NOT** be forwarded to Tower PCM Ingestion unmodified.
- Station-level components (e.g., PlayoutEngine + OutputSink / TowerPCMSink) are responsible for padding or dropping partial frames to preserve Tower's requirement for atomic 4096-byte frames (per `NEW_PCM_INGEST_CONTRACT.md`).
- No infinite loops or hangs

### FD1.4 — Error Handling

**MUST** emit errors as fatal for segment, not for station.

- Decoder errors cause current segment to end
- Errors are logged but do not crash station
- Next segment begins normally after error

---

## FD2 — Performance

### FD2.1 — Non-Blocking

**MUST NOT** block **THINK/DO** windows.

- Decoding occurs during playback (not during THINK/DO)
- Decoder must keep up with real-time playback rate
- No blocking I/O or CPU-intensive operations

### FD2.2 — Consumption Rate

**MUST** deliver frames at playout consumption rate.

- Decoder must produce frames at 21.333ms intervals (PCM cadence)
- Frame delivery must match PlayoutEngine's consumption rate
- No buffering delays or frame accumulation

---

## LOG — Logging and Observability

### LOG1 — Log File Location
FFmpegDecoder **MUST** write all log output to `/var/log/retrowaves/station.log`.

- Log file path **MUST** be deterministic and fixed
- Log file **MUST** be readable by the retrowaves user/group
- FFmpegDecoder **MUST NOT** require elevated privileges at runtime to write logs

### LOG2 — Non-Blocking Logging
Logging operations **MUST** be non-blocking and **MUST NOT** interfere with decoding operations.

- Logging **MUST NOT** block frame decoding
- Logging **MUST NOT** delay PCM frame delivery
- Logging **MUST NOT** affect consumption rate requirement (FD2.2)
- Logging **MUST NOT** block file I/O operations
- Logging failures **MUST** degrade silently (stderr fallback allowed)

### LOG3 — Rotation Tolerance
FFmpegDecoder **MUST** tolerate external log rotation without crashing or stalling.

- FFmpegDecoder **MUST** assume logs may be rotated externally (e.g., via logrotate)
- FFmpegDecoder **MUST** handle log file truncation or rename gracefully
- FFmpegDecoder **MUST NOT** implement rotation logic in application code
- FFmpegDecoder **MUST** reopen log files if they are rotated (implementation-defined mechanism)
- Rotation **MUST NOT** cause decoding interruption

### LOG4 — Failure Behavior
If log file write operations fail, FFmpegDecoder **MUST** continue decoding frames normally.

- Logging failures **MUST NOT** crash the process
- Logging failures **MUST NOT** interrupt frame decoding
- Logging failures **MUST NOT** interrupt PCM frame delivery
- FFmpegDecoder **MAY** fall back to stderr for critical errors, but **MUST NOT** block on stderr writes

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

- FFmpegDecoder uses FFmpeg library for MP3 decoding
- Decoder is created per-segment (not reused)
- Decoder handles file opening, decoding, and cleanup
- **Input**: MP3 files at ~24ms per MP3 frame (MP3 encoder timing domain)
- **Output**: PCM frames at 21.333ms cadence (1024 samples, 4096 bytes) matching Tower's PCM format
- Frame format matches Tower's PCM format (per `NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md`)
- Decoder errors are caught and handled gracefully
- Partial frames from decoder are handled by OutputSink (padded or dropped to ensure atomic 4096-byte frames)

