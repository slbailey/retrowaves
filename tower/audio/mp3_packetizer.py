"""
MP3 frame packetizer for CBR (Constant Bitrate) encoding.

This module provides MP3Packetizer, which accumulates raw MP3 bytes from
FFmpeg stdout and yields only complete MP3 frames. It is designed for
fixed encoder profiles (MPEG-1 Layer III, CBR) where frame size is
constant after the first header is parsed.
"""

from __future__ import annotations

from typing import Iterator, Optional


class MP3Packetizer:
    """
    MP3 frame packetizer supporting both CBR and VBR MP3 streams.
    
    Supports FFmpeg output:
    - MPEG-1 Layer III
    - CBR (Constant Bitrate) and VBR (Variable Bitrate)
    - Variable sample rates (44100, 48000, 32000 Hz)
    - Frame size computed from each header individually (VBR support)
    
    The packetizer:
    1. Maintains an internal bytearray buffer (max 64KB per contract [P2])
    2. Continuously scans for MP3 sync words: b1 == 0xFF and (b2 & 0xE0) == 0xE0
    3. Parses each frame header to extract bitrate, sample_rate, and padding
    4. Computes frame size per header: frame_size = int(144 * bitrate / sample_rate) + padding
    5. Yields only complete frames of the computed size
    6. Resyncs on malformed input by searching for next valid sync word
    7. Discards oldest bytes when buffer exceeds 64KB limit (preserves most recent)
    
    Per contract compliance goals [P1]-[P6]:
    - [P1] Accepts byte chunks of any size
    - [P2] Buffers until full valid frame is available (max 64KB, discards oldest when exceeded)
    - [P3] Emits frames one-by-one (generator/iterable)
    - [P4] Resyncs on malformed input or missing sync
    - [P5] Never emits partial frames, O(n) time, never blocks
    - [P6] Handles split headers + multi-frame blobs, supports VBR (frame size per header)
    
    Output guarantees:
    - Returned frames are raw MP3 frame bytes exactly as received (byte-for-byte identical)
    - No decoding, re-encoding, CRC removal, ID3 stripping, nor header mutation
    
    Note on real-world FFmpeg streams:
    - First frame may contain Xing/LAME headers (not audio data) - this is valid
    - CRC protected frames are handled implicitly
    - Joint stereo extensions are handled implicitly
    - Packetizer yields all valid MP3 frames as-is; Xing detection is optional
    
    Attributes:
        _buffer: Internal bytearray buffer for accumulating bytes
        _max_buffer_size: Maximum buffer size in bytes (default: 64KB)
    """
    
    # MP3 sync word pattern: 0xFF + (next_byte & 0xE0 == 0xE0)
    SYNC_BYTE_1 = 0xFF
    SYNC_MASK = 0xE0  # Top 3 bits must be set
    
    # MPEG-1 Layer III bitrate lookup table (kbps)
    # Indexed by 4-bit bitrate index from header byte 2 (bits 4-7)
    # Values are in kbps, or 0 for invalid/reserved
    # Source: ISO/IEC 11172-3 Table D.1 (MPEG-1)
    BITRATE_TABLE_MPEG1_L3 = [
        0,    # 0000 - free
        32,   # 0001
        40,   # 0010
        48,   # 0011
        56,   # 0100
        64,   # 0101
        80,   # 0110
        96,   # 0111
        112,  # 1000
        128,  # 1001
        160,  # 1010
        192,  # 1011
        224,  # 1100
        256,  # 1101
        320,  # 1110
        0,    # 1111 - reserved
    ]
    
    # MPEG-1 sample rate lookup table (Hz)
    # Indexed by 2-bit sample rate index from header byte 2 (bits 2-3)
    # Source: ISO/IEC 11172-3 Table D.2 (MPEG-1)
    SAMPLE_RATE_TABLE_MPEG1 = [
        44100,  # 00
        48000,  # 01
        32000,  # 10
        0,      # 11 - reserved
    ]
    
    def __init__(self, max_buffer_size: int = 65536) -> None:
        """
        Initialize MP3 packetizer.
        
        Args:
            max_buffer_size: Maximum internal buffer size in bytes (default: 64KB).
                            When exceeded, oldest bytes are discarded to prevent
                            unbounded growth. Per contract [P2].
        """
        self._buffer = bytearray()
        self._max_buffer_size = max_buffer_size  # 64KB default per contract [P2]
    
    def _is_sync_word(self, b1: int, b2: int) -> bool:
        """
        Check if two bytes form a valid MP3 sync word.
        
        Sync word pattern: b1 == 0xFF and (b2 & 0xE0 == 0xE0)
        
        Args:
            b1: First byte
            b2: Second byte
            
        Returns:
            True if bytes form a valid sync word
        """
        return b1 == self.SYNC_BYTE_1 and (b2 & self.SYNC_MASK) == self.SYNC_MASK
    
    def _find_sync(self, buf: bytearray) -> int:
        """
        Find the first MP3 sync word in the buffer.
        
        Searches for sync pattern: 0xFF followed by byte with top 3 bits set (0xE0 mask).
        
        Args:
            buf: Byte array to search
            
        Returns:
            Index of first sync word if found, -1 otherwise
        """
        # Need at least 2 bytes for sync word
        if len(buf) < 2:
            return -1
        
        for i in range(len(buf) - 1):
            # 11111111 111xxxxx pattern
            if buf[i] == 0xFF and (buf[i + 1] & 0xE0) == 0xE0:
                return i
        
        return -1
    
    def _parse_header(self, header: bytes) -> tuple[int, int, int]:
        """
        Parse MP3 frame header to extract bitrate, sample_rate, and padding.
        
        Assumes MPEG-1 Layer III format.
        
        Header structure (4 bytes):
        - Byte 0: 0xFF (sync)
        - Byte 1: Sync + version + layer + protection
        - Byte 2: Bitrate index (bits 4-7) + sample rate index (bits 2-3) + padding (bit 1)
        - Byte 3: Channel mode + mode extension + copyright + original + emphasis
        
        Args:
            header: First 4 bytes of MP3 frame header
            
        Returns:
            Tuple of (bitrate_kbps, sample_rate_hz, padding)
            
        Raises:
            ValueError: If header is invalid or cannot be parsed
        """
        if len(header) < 4:
            raise ValueError(f"Header must be at least 4 bytes, got {len(header)}")
        
        # Verify sync word
        if not self._is_sync_word(header[0], header[1]):
            raise ValueError("Invalid sync word in header")
        
        # Verify MPEG-1 Layer III
        # Byte 1: bits 3-4 are version (11 = MPEG-1), bits 1-2 are layer (01 = Layer III)
        version_bits = (header[1] >> 3) & 0x03
        layer_bits = (header[1] >> 1) & 0x03
        
        if version_bits != 0x03:  # 11 = MPEG-1
            raise ValueError(f"Not MPEG-1 (version bits: {version_bits:02b})")
        if layer_bits != 0x01:  # 01 = Layer III
            raise ValueError(f"Not Layer III (layer bits: {layer_bits:02b})")
        
        # Extract bitrate index (bits 4-7 of byte 2)
        bitrate_index = (header[2] >> 4) & 0x0F
        
        # Extract sample rate index (bits 2-3 of byte 2)
        sample_rate_index = (header[2] >> 2) & 0x03
        
        # Extract padding bit (bit 1 of byte 2)
        padding = (header[2] >> 1) & 0x01
        
        # Look up bitrate and sample rate
        bitrate_kbps = self.BITRATE_TABLE_MPEG1_L3[bitrate_index]
        sample_rate_hz = self.SAMPLE_RATE_TABLE_MPEG1[sample_rate_index]
        
        if bitrate_kbps == 0:
            raise ValueError(f"Invalid bitrate index: {bitrate_index}")
        if sample_rate_hz == 0:
            raise ValueError(f"Invalid sample rate index: {sample_rate_index}")
        
        return (bitrate_kbps, sample_rate_hz, padding)
    
    def _frame_size(self, header: bytes) -> Optional[int]:
        """
        Parse MP3 frame header and return exact frame size.
        
        Validates MPEG-1 Layer III format:
        - version_bits == 0b11 (MPEG-1)
        - layer_bits == 0b01 (Layer III)
        
        Note: Real FFmpeg streams may include:
        - CRC protected frames (valid, handled implicitly)
        - Joint stereo extensions (valid, handled implicitly)
        - Xing/LAME headers in first frame (valid, not audio data but acceptable)
        The packetizer yields these frames as-is; detection/flagging of Xing frames
        is optional and can be added later for integration tests.
        
        Args:
            header: First 4 bytes of MP3 frame header
            
        Returns:
            Frame size in bytes if header is valid, None if incomplete/invalid
        """
        if len(header) < 4:
            return None
        
        # Verify sync word
        if not self._is_sync_word(header[0], header[1]):
            return None
        
        # Verify MPEG-1 Layer III
        # Byte 1: bits 3-4 are version (11 = MPEG-1), bits 1-2 are layer (01 = Layer III)
        version_bits = (header[1] >> 3) & 0x03
        layer_bits = (header[1] >> 1) & 0x03
        
        if version_bits != 0x03:  # 11 = MPEG-1
            return None
        if layer_bits != 0x01:  # 01 = Layer III
            return None
        
        # Extract bitrate index (bits 4-7 of byte 2)
        bitrate_index = (header[2] >> 4) & 0x0F
        
        # Extract sample rate index (bits 2-3 of byte 2)
        sample_rate_index = (header[2] >> 2) & 0x03
        
        # Extract padding bit (bit 1 of byte 2)
        padding = (header[2] >> 1) & 0x01
        
        # Look up bitrate and sample rate
        bitrate_kbps = self.BITRATE_TABLE_MPEG1_L3[bitrate_index]
        sample_rate_hz = self.SAMPLE_RATE_TABLE_MPEG1[sample_rate_index]
        
        if bitrate_kbps == 0 or sample_rate_hz == 0:
            return None
        
        # Compute frame size: frame_size = int(144 * bitrate / sample_rate) + padding
        bitrate_bps = bitrate_kbps * 1000
        frame_size = int((144 * bitrate_bps) / sample_rate_hz) + padding
        
        return frame_size
    
    
    def feed(self, data: bytes) -> Iterator[bytes]:
        """
        Public API: feed raw MP3 bytes, yield complete MP3 frames.
        
        Stateless to callers; maintains internal streaming state.
        Accepts arbitrary-sized chunks (including partial frames).
        Yields complete MP3 frames incrementally as they become available.
        Never returns partial frames. Never blocks. On malformed data,
        drops bad bytes and continues; does not raise in normal operation.
        
        Args:
            data: Raw MP3 bytes to feed (can be empty)
            
        Yields:
            Complete MP3 frames as bytes
        """
        yield from self._accumulate(data)
    
    def _accumulate(self, data: bytes) -> Iterator[bytes]:
        """
        Internal engine: accumulates data and yields complete frames.
        
        Per contract compliance goals:
        - [P1] Accepts byte chunks of any size
        - [P2] Buffers until full valid frame is available
        - [P3] Emits frames one-by-one (generator/iterable)
        - [P4] Resyncs on malformed input or missing sync (verifies sync on every frame)
        - [P5] Never emits partial frames
        - [P6] Handles split headers + multi-frame blobs
        
        This is the internal implementation. Public callers should use feed().
        
        Args:
            data: Raw MP3 bytes to feed (can be empty)
            
        Yields:
            Complete MP3 frames as bytes
        """
        if not data:
            return
        
        # [P1] Accept byte chunks of any size - add to buffer
        self._buffer.extend(data)
        
        # [P2] Buffer cap: If buffer exceeds max size, discard oldest bytes
        # Preserve most recent bytes so eventual sync remains possible
        if len(self._buffer) > self._max_buffer_size:
            # Keep most recent max_buffer_size bytes, discard oldest
            excess = len(self._buffer) - self._max_buffer_size
            del self._buffer[:excess]
        
        # [P4] Resync on malformed input - continuously search for sync words
        # [P6] Handle split headers + multi-frame blobs - extract all available frames
        # [P6] Frame size computed from each header individually (VBR support)
        while True:
            # Find sync word in buffer
            frame_start = self._find_sync(self._buffer)
            
            if frame_start < 0:
                # No sync word found - keep small amount to handle split sync words
                # [P2] Maintain state, wait for more input
                # Keep last 2 bytes in case sync word (0xFF + byte) is split across chunks
                # This handles: 0xFF might be second-to-last byte, waiting for next byte to complete sync
                if len(self._buffer) > 2:
                    # Keep last 2 bytes (might contain partial sync word)
                    self._buffer = self._buffer[-2:]
                # If buffer is 2 bytes or less, keep as-is (might be partial sync word)
                return  # [P2] Wait for more input
            
            # [P4] Drop junk before sync word
            if frame_start > 0:
                del self._buffer[:frame_start]
            
            # [P6] Need at least 4 bytes for header (handle split headers)
            if len(self._buffer) < 4:
                return  # [P2] Wait for header completion
            
            # [P6] Parse header to get frame size (computed individually per frame for VBR support)
            header = bytes(self._buffer[:4])
            frame_size = self._frame_size(header)
            
            if frame_size is None:
                # Invalid header - skip this sync word and resync
                # [P4] Resync on malformed input: skip invalid sync word, continue searching
                if len(self._buffer) > 1:
                    del self._buffer[0]  # Skip invalid sync word
                    continue  # Try next sync word
                return
            
            # [P2] Need full frame before emitting
            if len(self._buffer) < frame_size:
                return  # [P2] Wait for more data
            
            # [P5] Extract complete frame (never partial)
            # [Output Guarantees] Frame is byte-for-byte identical to stream
            frame = bytes(self._buffer[:frame_size])
            del self._buffer[:frame_size]
            
            # [P3] Emit frame one-by-one (generator)
            yield frame
    
    def reset(self) -> None:
        """
        Reset packetizer internal state.
        
        Clears buffer. Useful when starting a new stream or after encoder restart.
        Per contract [P2]: State reset only when explicitly called, not during normal operation.
        """
        self._buffer.clear()
    
    def flush(self) -> Optional[bytes]:
        """
        Flush remaining partial frame from buffer.
        
        Per contract [P7]: Caller is not required to flush or signal boundaries.
        This method exists for backwards compatibility but is not part of the
        public contract. Partial frames remain buffered until complete.
        
        Returns:
            Remaining partial frame bytes, or None if buffer is empty
        """
        if not self._buffer:
            return None
        
        # Return whatever is left in buffer (may be partial frame)
        remaining = bytes(self._buffer)
        self._buffer.clear()
        
        return remaining if remaining else None
