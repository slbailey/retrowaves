# Contract: AUDIO_INPUT_ROUTER

This contract defines the behavior of AudioInputRouter, which buffers PCM frames from Station via Unix domain socket.

## 1. Core Invariants

- [R1] AudioInputRouter provides a **bounded queue** for PCM frames.
- [R2] Queue operations are **thread-safe** (multiple writers, single reader).
- [R3] Queue **never blocks** Tower operations (non-blocking writes, timeout-based reads).
- [R4] Queue **never grows unbounded** (bounded capacity with drop strategy).

## 2. Interface Contract

- [R5] Constructor takes:
  - `capacity: Optional[int]` (defaults to `TOWER_PCM_BUFFER_SIZE` or 100)
- [R6] Provides:
  - `push_frame(frame: bytes)` → non-blocking write
  - `pop_frame(timeout: Optional[float] = None) -> Optional[bytes]` → blocking read with timeout
  - `get_frame(timeout: Optional[float] = None) -> Optional[bytes]` → alias for pop_frame

## 3. Buffer Overflow Handling

- [R7] When queue is full and `push_frame()` is called:
  - **Drop newest frame** (not oldest) to maintain low latency
  - Increment overflow counter (for monitoring)
  - Never block or raise exception
- [R8] Station writes are unpaced bursts; Tower's steady consumption rate (21.333ms) stabilizes the buffer.

## 4. Buffer Underflow Handling

- [R9] When queue is empty and `pop_frame(timeout)` is called:
  - If `timeout` is None: return `None` immediately (non-blocking)
  - If `timeout > 0`: wait up to `timeout` seconds for frame, then return `None` if still empty
  - Never block indefinitely
- [R10] Underflow triggers fallback logic in AudioPump (grace period → fallback source).

## 5. Partial Frame Handling

- [R11] If Station crashes mid-write, AudioInputRouter may receive incomplete PCM frames.
- [R12] Partial frames are **discarded** (not buffered).
- [R13] `pop_frame()` never returns partial frames (only complete frames or None).
- [R14] Partial frame handling ensures continuous audio output even during Station failures.

## 6. Thread Safety

- [R15] All operations are thread-safe (protected by `threading.RLock`).
- [R16] Supports **multiple concurrent writers** (Station may have multiple threads writing).
- [R17] Supports **single reader** (AudioPump is the sole consumer).
- [R18] `push_frame()` and `pop_frame()` can be called concurrently without deadlock.

## 7. Unix Socket Integration (Decoupled)

- [R19] AudioInputRouter is **decoupled** from Unix socket implementation.
- [R20] Socket reading logic is separate from buffer management.
- [R21] Socket reader thread calls `push_frame()` when complete frames arrive.
- [R22] AudioPump calls `pop_frame()` independently of socket state.

## 8. Statistics and Monitoring Interface

- [R23] AudioInputRouter MUST expose:
  - `get_stats() -> dict[str, int]` returning `{"count": int, "capacity": int, "overflow_count": int}`
  - `count`: Current number of frames in the buffer (0 to capacity)
  - `capacity`: Maximum number of frames the buffer can hold
  - `overflow_count`: Total number of frames dropped due to buffer being full
- [R24] `get_stats()` MUST be lock-free or have extremely short lock duration.
  - Lock duration MUST be < 1ms typical, < 10ms maximum.
  - Method MUST NOT block on I/O, network calls, or expensive computations.
  - Method is designed for frequent polling by external monitoring systems (e.g., Station adaptive throttling).

## Required Tests

- `tests/contracts/test_tower_audio_input_router.py` MUST cover:
  - [R1]–[R4]: Core invariants (bounded, thread-safe, non-blocking)
  - [R5]–[R6]: Interface contract
  - [R7]–[R8]: Overflow handling (drop newest)
  - [R9]–[R10]: Underflow handling (timeout semantics)
  - [R11]–[R14]: Partial frame handling
  - [R15]–[R18]: Thread safety
  - [R19]–[R22]: Socket integration decoupling
  - [R23]–[R24]: Statistics and monitoring interface



