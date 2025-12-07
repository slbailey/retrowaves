# Contract: MP3_PACKETIZER

This contract defines the behavior of the MP3Packetizer component, which converts raw MP3 byte streams from FFmpeg stdout into discrete, complete MP3 frames.

See also: `TOWER_ENCODER_CONTRACT.md` for integration with EncoderOutputDrainThread.

## Purpose

Convert raw MP3 byte stream from FFmpeg stdout into discrete, complete MP3 frames.

## Contract Compliance Goals

MP3Packetizer MUST:

- [P1] **Accept byte chunks of any size** - Accepts arbitrary byte chunks including incomplete frames, split headers, and multi-frame blobs. No restrictions on chunk size.

- [P2] **Buffer until a full valid frame is available** - Maintains internal streaming state across calls, accumulating partial data until complete frames can be extracted. Partial frames remain buffered until complete. Packetizer maintains internal state indefinitely and must continue processing unbounded streams without performance degradation or state reset unless buffer cap triggers. Implementation MUST limit internal buffer size (e.g., 64KB) to prevent unbounded growth when no valid sync word is found. **If buffer growth exceeds maximum size, oldest bytes MUST be discarded, preserving the most recent bytes so that eventual sync remains possible.** This prevents memory leaks while maintaining resync capability.

- [P3] **Emit frames one-by-one (generator/iterable)** - Returns an iterable (generator) that yields complete MP3 frames incrementally as they become available. Each frame is yielded individually, not batched.

- [P4] **Resync on malformed input or missing sync** - Packetizer is responsible for frame header parsing & resync. When malformed data or missing sync words are detected, must skip bytes and resync to the next valid sync word. If a sync word is found but header parsing fails (invalid bitrate/sample rate indices, wrong MPEG version/layer), packetizer MUST skip that sync word byte and continue searching for the next valid sync word. Applies to both initial parsing and subsequent frame extraction.

- [P5] **Never emit partial frames** - Only yields complete, valid MP3 frames. Never returns partial frames, even if stream ends abruptly. **feed() must execute in O(n) time relative to incoming data and must never block on external IO or wait for future data.**

- [P6] **Handle split headers + multi-frame blobs** - Correctly handles:
  - Frames split across multiple feed() calls (e.g., header in one call, payload in another)
  - Multiple complete frames in a single feed() call
  - Headers split across chunk boundaries
  - **Frame size MUST be computed from each header individually, supporting both CBR (Constant Bitrate) and VBR (Variable Bitrate) streams.**

## Method Definitions

### `feed(data: bytes) -> Iterable[bytes]`

Public API for feeding raw MP3 bytes to the packetizer. Returns an iterable that yields complete MP3 frames as they become available.

**Requirements:**

- [P1] Accepts arbitrary byte chunks including incomplete frames

- [P2] Maintains internal streaming state across calls

- [P3] Returns **zero or more complete MP3 frames** (emitted one-by-one as generator/iterable)

- [P4] Never returns partial frames

- [P5] Never blocks

- [P6] Packetizer is responsible for frame header parsing & resync

- [P7] Caller is not required to flush or signal boundaries

- [P8] Packetizer tolerates bad data—skips until next valid sync word

**Behavior:**

- Each call to `feed()` may yield zero, one, or multiple complete frames
- Frames are yielded incrementally as they become complete
- Partial data is buffered internally until a complete frame can be extracted
- Invalid or malformed data is skipped, and the packetizer resyncs to the next valid sync word
- No external flush or boundary signaling is required

**Output Guarantees:**

- Returned frames MUST be raw MP3 frame bytes exactly as received from stream
- No decoding, re-encoding, CRC removal, ID3 stripping, nor header mutation
- Frames are byte-for-byte identical to the original stream data
- Tests assume frames returned are raw MP3 frame bytes, unchanged

## Implementation Notes

- `_accumulate(data)` MAY exist internally, but MUST NOT be public API

- Only public ingestion entry point is `feed(data)`

- Contract prohibits drain thread from calling internal methods

- Implementation must handle MPEG-1 Layer III format (both CBR and VBR streams)
- Frame size MUST be computed from each header individually, not assumed constant

- Real FFmpeg streams may include:
  - CRC protected frames (valid, handled implicitly)
  - Joint stereo extensions (valid, handled implicitly)
  - Xing/LAME headers in first frame (valid, not audio data but acceptable)
  - The packetizer yields these frames as-is; detection/flagging of Xing frames is optional

## Integration with EncoderOutputDrainThread

The packetizer is designed to be used by `EncoderOutputDrainThread` as follows:

```python
while running:
    data = stdout.read(N)
    for frame in packetizer.feed(data):
        mp3_buffer.push_frame(frame)
```

See `TOWER_ENCODER_CONTRACT.md` section "EncoderOutputDrainThread Contract" for full integration requirements.

## Required Tests

- `tests/contracts/test_tower_encoder_packetizer.py` MUST cover [P1]–[P8] and [E7]–[E8].
