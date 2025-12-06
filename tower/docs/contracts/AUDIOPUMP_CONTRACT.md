# Contract: AUDIOPUMP

This contract defines the behavior of AudioPump, which pumps PCM frames to the encoder at a stable 24ms metronome.

## 1. Core Invariants

- [A0] TowerService is responsible for creating and starting AudioPump. AudioPump MUST run continuously for the entire lifetime of Tower. System MP3 output depends on AudioPump providing continuous PCM.
- [A1] AudioPump is Tower's **sole metronome** - the only clock in the system.
- [A2] AudioPump **never interacts with FFmpegSupervisor directly**.
- [A3] AudioPump only calls `encoder_manager.write_pcm(frame: bytes)`.
- [A4] Timing loop operates at exactly **24ms intervals** (1152 samples at 48kHz).

## 2. Interface Contract

- [A5] AudioPump constructor takes:
  - `pcm_buffer: FrameRingBuffer`
  - `fallback_generator: FallbackGenerator`
  - `encoder_manager: EncoderManager` (NOT supervisor)
- [A6] AudioPump provides:
  - `start()` → starts thread, begins real-time pumping
  - `stop()` → stops thread gracefully

## 3. Frame Selection Logic

- [A7] At each tick (24ms):
  1. Try to pull frame from `pcm_buffer.pop_frame()`
  2. If None → get frame from `fallback_generator.get_frame()`
  3. Call `encoder_manager.write_pcm(frame)`
- [A8] Frame selection is non-blocking - never waits indefinitely.

## 4. Timing Model

- [A9] Uses absolute clock timing (`next_tick += FRAME_DURATION_SEC`) to prevent drift.
- [A10] If loop falls behind schedule, resyncs clock instead of accumulating delay.
- [A11] Sleeps only if ahead of schedule; logs warning if behind.

## 5. Error Handling

- [A12] Write errors (e.g., broken pipe) are logged but do not crash the thread.
- [A13] On write error, sleeps briefly (0.1s) then continues loop.

## Required Tests

- `tests/contracts/test_tower_audiopump.py` MUST cover:
  - [A0]: TowerService lifecycle responsibility and continuous operation requirement
  - [A1]–[A4]: Metronome behavior and interface isolation
  - [A5]–[A6]: Constructor and public interface
  - [A7]–[A8]: Frame selection logic
  - [A9]–[A11]: Timing model and drift prevention
  - [A12]–[A13]: Error handling

