# Contract: AUDIOPUMP

This contract defines the behavior of AudioPump, which pumps PCM frames to the encoder at a stable 24ms metronome.

## 1. Core Invariants

- [A0] TowerService is responsible for creating and starting AudioPump. AudioPump MUST run continuously for the entire lifetime of Tower. System MP3 output depends on AudioPump providing continuous PCM.
- [A1] AudioPump is Tower's **sole metronome** - the only clock in the system.
- [A2] AudioPump **never interacts with FFmpegSupervisor directly**.
- [A3] AudioPump DOES NOT route audio. AudioPump MUST ONLY call `encoder_manager.next_frame(pcm_buffer)` each tick. AudioPump MUST NEVER call `encoder_manager.write_pcm()` or `encoder_manager.write_fallback()` directly. All routing decisions (PCM vs fallback, thresholds, operational modes) are made entirely inside EncoderManager's `next_frame()` method.
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

- [A7] At each tick (24ms), AudioPump MUST:
  1. Call `encoder_manager.next_frame(pcm_buffer)` exactly once
  2. Return immediately (non-blocking)
  3. AudioPump does NOT make any routing decisions:
     - AudioPump does NOT check PCM buffer availability
     - AudioPump does NOT determine operational mode
     - AudioPump does NOT apply PCM validity thresholds
     - AudioPump does NOT choose between PCM vs fallback
     - AudioPump does NOT call `write_pcm()` or `write_fallback()` directly
  4. All routing logic is internal to EncoderManager's `next_frame()` method, which:
     - Checks PCM buffer availability internally
     - Determines operational mode
     - Applies PCM validity threshold per [M16A]
     - Routes to write_pcm() or write_fallback() as appropriate
- [A8] Frame selection is non-blocking - never waits indefinitely. `next_frame()` MUST return immediately.

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

