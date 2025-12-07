# Contract: TOWER_ENCODER

This contract defines the internal behavior of the encoding subsystem:
EncoderManager, MP3Packetizer, and the frame-based MP3 buffer.

## 1. Core Invariants

- [E1] MP3 output is **smooth and continuous** while Tower is running.
- [E2] Everything inside the encoder path operates on **complete MP3 frames only**.
- [E3] The tick-driven output loop is oblivious to encoder restart state and only calls `encoder_manager.get_frame()`.
- [E3.1] EncoderManager owns FFmpegSupervisor - supervisor is never exposed externally.
- [E3.2] AudioPump calls `encoder_manager.write_pcm()` - never supervisor directly.

## 2. Dual-buffer Model

- [E4] PCM input and MP3 output use **independent** ring buffers.
- [E5] PCM buffer:
  - [E5.1] Bounded capacity (configurable, default 100 frames).
  - [E5.2] Non-blocking writes: new frames are dropped when full.
  - [E5.3] Non-blocking reads: returns None when empty.
- [E6] MP3 buffer:
  - [E6.1] Capacity expressed in frames (default 400 frames ≈ 5s).
  - [E6.2] Stores complete MP3 frames only (no partials).
  - [E6.3] Non-blocking writes: oldest frame is dropped when full.
  - [E6.4] Non-blocking reads: returns None when empty.

## 3. Frame Semantics

- [E7] MP3Packetizer:
  - [E7.1] Detects the first valid MP3 frame via sync word (0xFF + (b2 & 0xE0 == 0xE0)).
  - [E7.2] Computes frame size from the first header for CBR profile.
  - [E7.3] Yields only complete frames of that size thereafter.
  - See `MP3_PACKETIZER_CONTRACT.md` for full specification [P1]–[P8].
- [E8] FrameRingBuffer never stores partial frames.
- [E9] `EncoderManager.get_frame()` returns:
  - Real MP3 frame if available.
  - A prebuilt silence frame if buffer is empty or encoder is down.

---

## EncoderOutputDrainThread Contract

```python
while running:
    data = stdout.read(N)
    for frame in packetizer.feed(data):
        mp3_buffer.push_frame(frame)
```

- [D1] Drain thread MUST call `packetizer.feed(data)` for each read
  - `feed()` returns an iterable of complete MP3 frames
  - Frames are yielded incrementally as they become complete
  - Partial chunks accumulate in packetizer until full frame appears

- [D2] Drain thread MUST NOT parse MP3 headers (packetizer handles this)

- [D3] Drain thread MUST call `mp3_buffer.push_frame(frame)` once per complete frame
  - `push_frame()` is called exactly once for each frame yielded by `feed()`
  - Never pushes partial frames (packetizer ensures only complete frames)

- [D4] Restart logic triggers when no frames output for STALL_TIMEOUT

---

## 4. Tick-driven Output

- [E10] The broadcast loop calls `get_frame()` at a fixed interval `TOWER_OUTPUT_TICK_INTERVAL_MS`.
- [E11] The loop does not inspect encoder state or buffers directly.
- [E12] It is safe to batch multiple frames into a single socket write, but frame boundaries must be preserved (concatenation only at the edge).

## 5. Encoder Stall & Restart

- [E13] Encoder stalls are detected by FFmpegSupervisor when no bytes are read from stdout for `TOWER_ENCODER_STALL_THRESHOLD_MS`.
- [E14] On stall or crash:
  - [E14.1] FFmpegSupervisor detects failure and transitions to RESTARTING state.
  - [E14.2] EncoderManager mirrors supervisor state (RUNNING → RESTARTING).
  - [E14.3] MP3 buffer is **not cleared** (preserved during restart).
  - [E14.4] Output continues: buffer frames → silence → real frames after restart.
- [E15] Encoder restart is handled by FFmpegSupervisor:
  - Follows configured backoff schedule
  - Stops after `TOWER_ENCODER_MAX_RESTARTS` attempts
  - Enters FAILED state if max restarts exceeded
  - EncoderManager mirrors supervisor state changes

## Required Tests

- `tests/contracts/test_tower_encoder_buffers.py` MUST cover [E4]–[E6].
- `tests/contracts/test_tower_encoder_packetizer.py` MUST cover [E7]–[E8] and [P1]–[P8] (see MP3_PACKETIZER_CONTRACT.md).
- `tests/contracts/test_tower_encoder_get_frame.py` MUST cover [E2], [E9], [E10]–[E12].
- `tests/contracts/test_tower_encoder_restart.py` MUST cover [E13]–[E15].
- `tests/contracts/test_tower_encoder_manager.py` MUST cover EncoderManager contract (see ENCODER_MANAGER_CONTRACT.md).
- `tests/contracts/test_tower_ffmpeg_supervisor.py` MUST cover FFmpegSupervisor contract (see FFMPEG_SUPERVISOR_CONTRACT.md).
