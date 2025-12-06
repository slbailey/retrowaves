# Contract: FRAME_RING_BUFFER

This contract defines the behavior of FrameRingBuffer, a thread-safe ring buffer for complete frames (PCM or MP3).

## 1. Core Invariants

- [B1] FrameRingBuffer stores **complete frames only** (no partial frames).
- [B2] FrameRingBuffer is **bounded** (fixed capacity, never grows unbounded).
- [B3] FrameRingBuffer is **thread-safe** (supports concurrent push/pop operations).
- [B4] FrameRingBuffer operations are **non-blocking** (never wait indefinitely).

## 2. Thread Safety Model

- [B5] FrameRingBuffer supports **multi-producer, multi-consumer** model.
- [B6] **Reentrant lock protection**:
  - All public operations on FrameRingBuffer (push_frame, pop_frame, stats, clear, etc.)
  - MUST be protected by a **reentrant lock** stored on `self._lock`.
  - The lock MUST be an instance returned by `threading.RLock()` (or its underlying `_thread.RLock` implementation).
  - Tests MUST validate that `self._lock` is reentrant (supports `.acquire()` multiple times by same thread)
  - rather than comparing exact class identity.
- [B7] `push_frame()` and `pop_frame()` can be called concurrently without deadlock.
- [B8] Thread safety is **explicitly guaranteed** (not assumed).

## 3. Overflow Strategy

- [B9] Overflow strategy depends on buffer type:
  - **PCM buffer**: Drop **newest** frame (maintains low latency)
  - **MP3 buffer**: Drop **oldest** frame (maintains freshness)
- [B10] When buffer is full and `push_frame()` is called:
  - Drop frame according to strategy (newest for PCM, oldest for MP3)
  - Increment overflow counter (for monitoring)
  - Never block or raise exception
- [B11] Overflow strategy is **configurable** via constructor parameter or buffer type.

## 4. Underflow Strategy

- [B12] When buffer is empty and `pop_frame()` is called:
  - Return `None` immediately (non-blocking)
  - Never block or wait
- [B13] Underflow is **expected behavior** (not an error condition).

## 5. Interface Contract

- [B14] Constructor takes:
  - `capacity: int` → maximum number of frames
- [B15] Provides:
  - `push_frame(frame: bytes)` → non-blocking write, drops on overflow
  - `pop_frame() -> Optional[bytes]` → non-blocking read, returns None if empty
  - `clear() -> None` → clears all frames
  - `stats() -> FrameRingBufferStats` → returns buffer statistics
- [B16] All methods are **O(1)** time complexity.

## 6. Frame Semantics

- [B17] **Arbitrary byte frames (non-empty)**: FrameRingBuffer MUST accept and store arbitrary non-empty bytes objects without inspecting or validating their format. Passing `None` or an empty frame (`b""`) MUST raise `ValueError` and MUST NOT be stored.
- [B18] Caller is responsible for ensuring frames are complete and correctly formatted.
- [B19] Frame boundaries are **preserved** (frames are never split or merged).

## 7. Statistics

- [B20] `stats()` returns:
  - `count: int` → current number of frames
  - `capacity: int` → maximum capacity
  - `overflow_count: int` → number of frames dropped due to overflow
- [B21] Statistics are **thread-safe** (can be called concurrently).

## Required Tests

- `tests/contracts/test_tower_frame_ring_buffer.py` MUST cover:
  - [B1]–[B4]: Core invariants (complete frames, bounded, thread-safe, non-blocking)
  - [B5]–[B8]: Thread safety model (multi-producer, multi-consumer)
  - [B9]–[B11]: Overflow strategy (PCM vs MP3 drop behavior)
  - [B12]–[B13]: Underflow strategy (non-blocking)
  - [B14]–[B16]: Interface contract and O(1) guarantees
  - [B17]–[B19]: Frame semantics
  - [B20]–[B21]: Statistics thread safety



