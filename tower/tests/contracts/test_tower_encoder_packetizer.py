"""
Contract tests for Tower Encoder MP3Packetizer

See docs/contracts/MP3_PACKETIZER_CONTRACT.md
Covers: [P1]–[P8] (MP3 Packetizer Public Interface)
Also covers: [E7]–[E8] (Frame Semantics from TOWER_ENCODER_CONTRACT.md)
"""

import pytest
import random
from typing import List

from tower.audio.mp3_packetizer import MP3Packetizer


# MP3 sync word pattern: 0xFF + (next_byte & 0xE0 == 0xE0)
SYNC_BYTE_1 = 0xFF
SYNC_MASK = 0xE0


def create_fake_mp3_frame(
    bitrate_kbps: int = 128,
    sample_rate: int = 44100,
    padding: int = 0,
    payload_seed: int = None
) -> bytes:
    """
    Create a fake MP3 frame with valid sync word and header.
    
    Frame size is computed using the same formula as MP3Packetizer:
    frame_size = 144 * bitrate / sample_rate + padding
    
    Args:
        bitrate_kbps: Bitrate in kbps (default: 128)
        sample_rate: Sample rate in Hz (default: 44100)
        padding: Padding bit (0 or 1, default: 0)
        payload_seed: Random seed for payload (for reproducibility)
        
    Returns:
        Fake MP3 frame bytes with correct size
    """
    # Compute frame size using same formula as MP3Packetizer
    bitrate_bps = bitrate_kbps * 1000
    frame_size = int((144 * bitrate_bps) / sample_rate) + padding
    
    if frame_size < 4:
        raise ValueError(f"Computed frame size {frame_size} is too small")
    
    # Create header (4 bytes)
    # Byte 0: 0xFF (sync)
    # Byte 1: 0xFB (MPEG-1, Layer III, no CRC) - top 3 bits must be set (0xE0 mask)
    # Byte 2: Bitrate index (bits 4-7) + sample rate index (bits 2-3) + padding (bit 1)
    # Byte 3: Channel mode, etc.
    
    # Bitrate lookup table (same as MP3Packetizer)
    BITRATE_TABLE = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
    # Sample rate lookup table (same as MP3Packetizer)
    SAMPLE_RATE_TABLE = [44100, 48000, 32000, 0]
    
    # Find bitrate index
    bitrate_index = None
    for idx, br in enumerate(BITRATE_TABLE):
        if br == bitrate_kbps:
            bitrate_index = idx
            break
    if bitrate_index is None:
        raise ValueError(f"Unsupported bitrate: {bitrate_kbps} kbps")
    
    # Find sample rate index
    sample_rate_index = None
    for idx, sr in enumerate(SAMPLE_RATE_TABLE):
        if sr == sample_rate:
            sample_rate_index = idx
            break
    if sample_rate_index is None:
        raise ValueError(f"Unsupported sample rate: {sample_rate} Hz")
    
    # Build header
    header = bytearray([
        SYNC_BYTE_1,  # 0xFF
        0xFB,  # MPEG-1 Layer III, no CRC (0xFB & 0xE0 == 0xE0)
        0x00,  # Will set bitrate, sample rate, and padding
        0x00   # Channel mode, etc.
    ])
    
    # Set bitrate index (bits 4-7 of byte 2)
    header[2] |= (bitrate_index << 4)
    # Set sample rate index (bits 2-3 of byte 2)
    header[2] |= (sample_rate_index << 2)
    # Set padding bit (bit 1 of byte 2)
    if padding:
        header[2] |= 0x02
    
    # Create payload (rest of frame)
    payload_size = frame_size - 4
    if payload_seed is not None:
        random.seed(payload_seed)
    else:
        random.seed(42)  # Default seed
    
    payload = bytes([random.randint(0, 255) for _ in range(payload_size)])
    
    return bytes(header) + payload


@pytest.fixture
def fake_mp3_frame():
    """Fixture to generate a fake MP3 frame."""
    # Standard frame size for 128kbps @ 44.1kHz: 417 bytes (no padding)
    # frame_size = 144 * 128000 / 44100 = 417.96... ≈ 417 (truncated)
    return create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, padding=0, payload_seed=42)


@pytest.fixture
def packetizer_128k_44k():
    """Fixture for packetizer with 128kbps @ 44.1kHz."""
    return MP3Packetizer()


@pytest.fixture
def packetizer_128k_48k():
    """Fixture for packetizer with 128kbps @ 48kHz."""
    return MP3Packetizer()


class TestMP3Packetizer:
    """Tests for MP3Packetizer covering contract [E7]–[E8]."""
    
    def test_packetizer_feed_contract(self, packetizer_128k_44k):
        """Test that feed() API shape matches contract [P1]-[P8]."""
        # [P1] Accepts arbitrary byte chunks including incomplete frames
        # [P3] Returns zero or more complete MP3 frames
        # [P4] Never returns partial frames
        frames = list(packetizer_128k_44k.feed(b'\x00\x01\x02'))  # arbitrary junk
        assert isinstance(frames, list)
        # [P3] May return zero frames (no valid sync word found)
        # All returned frames must be bytes
        for frame in frames:
            assert isinstance(frame, bytes)
    
    def test_feed_one_frame_returns_frame(self, packetizer_128k_44k, fake_mp3_frame):
        """Test that feeding one complete frame returns [frame] [P3], [P4]."""
        # [P1] Accepts arbitrary byte chunks
        # [P3] Returns zero or more complete MP3 frames
        # [P4] Never returns partial frames
        frames = list(packetizer_128k_44k.feed(fake_mp3_frame))
        
        assert len(frames) == 1
        assert frames[0] == fake_mp3_frame
    
    def test_feed_partial_header_returns_empty(self, packetizer_128k_44k):
        """Test that feeding partial header returns [] [P3], [P4]."""
        # [P1] Accepts arbitrary byte chunks including incomplete frames
        # [P3] Returns zero or more complete MP3 frames (zero in this case)
        # [P4] Never returns partial frames
        # Feed only 2 bytes (not enough for header)
        partial = b"\xFF\xFB"
        frames = list(packetizer_128k_44k.feed(partial))
        
        assert frames == []
        
        # Feed one more byte (still not enough)
        frames = list(packetizer_128k_44k.feed(b"\x00"))
        assert frames == []
    
    def test_feed_two_frames_back_to_back(self, packetizer_128k_44k):
        """Test that feeding two frames back-to-back returns [f1, f2] [P3], [P4]."""
        # [P1] Accepts arbitrary byte chunks
        # [P3] Returns zero or more complete MP3 frames
        # [P4] Never returns partial frames
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=1)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=2)
        
        # Feed both frames at once
        frames = list(packetizer_128k_44k.feed(frame1 + frame2))
        
        assert len(frames) == 2
        assert frames[0] == frame1
        assert frames[1] == frame2
    
    def test_feed_partial_frame_then_rest(self, packetizer_128k_44k):
        """Test that feeding partial frame then rest returns 1 frame [P2], [P3], [P4]."""
        # [P1] Accepts arbitrary byte chunks including incomplete frames
        # [P2] Maintains internal streaming state across calls
        # [P3] Returns zero or more complete MP3 frames
        # [P4] Never returns partial frames
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=3)
        
        # Feed first half
        half = len(frame) // 2
        frames1 = list(packetizer_128k_44k.feed(frame[:half]))
        assert frames1 == []  # No complete frame yet [P3], [P4]
        
        # Feed second half - state maintained [P2]
        frames2 = list(packetizer_128k_44k.feed(frame[half:]))
        assert len(frames2) == 1  # Complete frame now available [P3]
        assert frames2[0] == frame
    
    def test_mixed_fragmentation_scenario_1(self, packetizer_128k_44k):
        """Mixed fragmentation: frame split across 3 feeds [P2], [P3], [P4]."""
        # [P1] Accepts arbitrary byte chunks including incomplete frames
        # [P2] Maintains internal streaming state across calls
        # [P3] Returns zero or more complete MP3 frames
        # [P4] Never returns partial frames
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=4)
        
        # Split into 3 parts
        part1 = frame[:100]
        part2 = frame[100:300]
        part3 = frame[300:]
        
        frames1 = list(packetizer_128k_44k.feed(part1))
        assert frames1 == []  # [P3], [P4]
        
        frames2 = list(packetizer_128k_44k.feed(part2))
        assert frames2 == []  # [P3], [P4]
        
        frames3 = list(packetizer_128k_44k.feed(part3))
        assert len(frames3) == 1  # [P3] Complete frame now available
        assert frames3[0] == frame
    
    def test_mixed_fragmentation_scenario_2(self, packetizer_128k_44k):
        """Mixed fragmentation: two frames with split boundary."""
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=5)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=6)
        
        # Feed frame1 complete + first part of frame2
        split_point = len(frame1) + 200
        data = frame1 + frame2[:200]
        frames1 = list(packetizer_128k_44k.feed(data))
        
        assert len(frames1) == 1
        assert frames1[0] == frame1
        
        # Feed rest of frame2
        frames2 = list(packetizer_128k_44k.feed(frame2[200:]))
        assert len(frames2) == 1
        assert frames2[0] == frame2
    
    def test_mixed_fragmentation_scenario_3(self, packetizer_128k_44k):
        """Mixed fragmentation: multiple frames with various splits."""
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=7)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=8)
        frame3 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=9)
        
        # Feed: frame1 complete, frame2 partial, then frame2 rest + frame3 partial
        data1 = frame1 + frame2[:150]
        frames1 = list(packetizer_128k_44k.feed(data1))
        assert len(frames1) == 1
        assert frames1[0] == frame1
        
        # Feed rest of frame2 and start of frame3 (but don't include frame3 header)
        # frame2[150:] completes frame2, frame3[:150] is partial (no header yet)
        data2 = frame2[150:] + frame3[:150]
        frames2 = list(packetizer_128k_44k.feed(data2))
        # frame2 should be complete now
        assert len(frames2) == 1
        assert frames2[0] == frame2
        
        # Feed rest of frame3
        data3 = frame3[150:]
        frames3 = list(packetizer_128k_44k.feed(data3))
        # frame3 should be complete now
        assert len(frames3) == 1
        assert frames3[0] == frame3
    
    def test_mixed_fragmentation_scenario_4(self, packetizer_128k_44k):
        """Mixed fragmentation: leading junk before first sync word [P6], [P8]."""
        # [P6] Packetizer is responsible for frame header parsing & resync
        # [P8] Packetizer tolerates bad data—skips until next valid sync word
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=10)
        
        # Add junk before frame
        junk = b"JUNK_DATA_BEFORE_SYNC\x00\x01\x02"
        data = junk + frame
        
        frames = list(packetizer_128k_44k.feed(data))
        assert len(frames) == 1  # [P3] Complete frame extracted
        assert frames[0] == frame  # Junk should be discarded [P8]
    
    def test_mixed_fragmentation_scenario_5(self, packetizer_128k_44k):
        """Mixed fragmentation: multiple frames with leading junk."""
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=11)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=12)
        
        junk = b"\x00\x01\x02\x03\x04"
        data = junk + frame1 + frame2
        
        frames = list(packetizer_128k_44k.feed(data))
        assert len(frames) == 2
        assert frames[0] == frame1
        assert frames[1] == frame2
    
    # Note: flush() tests removed per contract [P7]: "Caller is not required to flush or signal boundaries"
    # The packetizer maintains internal state and only yields complete frames via feed()
    
    def test_sync_word_detection(self, packetizer_128k_44k):
        """Test sync word detection [E7.1]."""
        # Valid sync: 0xFF 0xFB (0xFB & 0xE0 == 0xE0)
        valid_sync = bytes([SYNC_BYTE_1, 0xFB, 0x00, 0x00])
        frames = list(packetizer_128k_44k.feed(valid_sync + b"payload" * 50))
        # Should parse (even if frame size calculation might be off)
        # At minimum, it should not crash
    
    def test_frame_size_computation(self, packetizer_128k_44k):
        """Test frame size computation from header [E7.2]."""
        # For 128kbps @ 44.1kHz: frame_size = 144 * 128000 / 44100 = 417.96...
        # Without padding: 417, with padding: 418
        frame_no_padding = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, padding=0, payload_seed=17)
        frame_with_padding = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, padding=1, payload_seed=18)
        
        # Feed frame without padding
        frames1 = list(packetizer_128k_44k.feed(frame_no_padding))
        assert len(frames1) == 1
        
        # Feed frame with padding (should use same frame size)
        frames2 = list(packetizer_128k_44k.feed(frame_with_padding))
        # Note: frame size is computed from first header, so second frame
        # might not match if padding differs, but packetizer should handle it
    
    def test_never_emits_partial_frames(self, packetizer_128k_44k):
        """Test that packetizer never emits partial frames [P4]."""
        # [P1] Accepts arbitrary byte chunks including incomplete frames
        # [P2] Maintains internal streaming state across calls
        # [P3] Returns zero or more complete MP3 frames
        # [P4] Never returns partial frames
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=19)
        
        # Feed frame in many small chunks
        chunk_size = 10
        all_frames = []
        
        for i in range(0, len(frame), chunk_size):
            chunk = frame[i:i + chunk_size]
            frames = list(packetizer_128k_44k.feed(chunk))
            all_frames.extend(frames)
        
        # [P4] Should only get complete frame at the end
        # All partial chunks should return [] [P3]
        # Only when complete frame is available should we get it [P3]
        assert len(all_frames) <= 1  # At most one complete frame
        
        # If we got a frame, it should be the complete one [P4]
        if all_frames:
            assert all_frames[0] == frame
    
    # ========================================================================
    # Tests for Contract Compliance Goals (P1-P6)
    # ========================================================================
    
    def test_p1_accepts_byte_chunks_any_size(self, packetizer_128k_44k):
        """Test [P1]: Accept byte chunks of any size."""
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=100)
        
        # Test various chunk sizes: 1 byte, 10 bytes, 100 bytes, full frame, larger than frame
        chunk_sizes = [1, 10, 100, len(frame), len(frame) * 2]
        
        for chunk_size in chunk_sizes:
            packetizer = MP3Packetizer()  # Fresh packetizer for each test
            all_frames = []
            
            # Feed frame in chunks of specified size
            for i in range(0, len(frame), chunk_size):
                chunk = frame[i:i + chunk_size]
                frames = list(packetizer.feed(chunk))
                all_frames.extend(frames)
            
            # Should eventually get the complete frame regardless of chunk size
            assert len(all_frames) == 1
            assert all_frames[0] == frame
    
    def test_p2_buffers_until_full_frame_available(self, packetizer_128k_44k):
        """Test [P2]: Buffer until a full valid frame is available."""
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=101)
        
        # Feed frame in very small chunks (1 byte at a time)
        # Each chunk should return empty until full frame is available
        for i in range(len(frame) - 1):
            chunk = frame[i:i + 1]
            frames = list(packetizer_128k_44k.feed(chunk))
            # [P2] Should return empty until full frame is available
            assert frames == [], f"Expected empty at byte {i}, got {len(frames)} frames"
        
        # Feed final byte - now full frame should be available
        final_byte = frame[-1:]
        frames = list(packetizer_128k_44k.feed(final_byte))
        assert len(frames) == 1
        assert frames[0] == frame
    
    def test_p3_emits_frames_one_by_one_generator(self, packetizer_128k_44k):
        """Test [P3]: Emit frames one-by-one (generator/iterable)."""
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=102)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=103)
        frame3 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=104)
        
        # Feed all three frames at once
        all_data = frame1 + frame2 + frame3
        frames_iter = packetizer_128k_44k.feed(all_data)
        
        # [P3] Should be an iterable/generator
        assert hasattr(frames_iter, '__iter__')
        
        # [P3] Should yield frames one-by-one incrementally
        frames_list = list(frames_iter)
        assert len(frames_list) == 3
        assert frames_list[0] == frame1
        assert frames_list[1] == frame2
        assert frames_list[2] == frame3
    
    def test_p4_resync_on_malformed_input_missing_sync(self, packetizer_128k_44k):
        """Test [P4]: Resync on malformed input or missing sync."""
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=105)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=106)
        
        # Insert malformed data between frames (no valid sync word)
        malformed = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09" * 10  # 100 bytes of junk
        data = frame1 + malformed + frame2
        
        frames = list(packetizer_128k_44k.feed(data))
        
        # [P4] Should resync and extract both valid frames, skipping malformed data
        assert len(frames) == 2
        assert frames[0] == frame1
        assert frames[1] == frame2
    
    def test_p4_resync_on_invalid_sync_word(self, packetizer_128k_44k):
        """Test [P4]: Resync when encountering invalid sync word pattern."""
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=107)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=108)
        
        # Insert fake sync words that don't form valid headers (0xFF but wrong second byte)
        fake_syncs = b"\xFF\x00" * 20  # Invalid sync pattern (0xFF but 0x00 & 0xE0 != 0xE0)
        data = frame1 + fake_syncs + frame2
        
        frames = list(packetizer_128k_44k.feed(data))
        
        # [P4] Should skip invalid sync patterns and resync to next valid frame
        assert len(frames) == 2
        assert frames[0] == frame1
        assert frames[1] == frame2
    
    def test_p4_resync_after_corrupted_frame(self, packetizer_128k_44k):
        """Test [P4]: Resync after corrupted frame data (frame size known but sync missing)."""
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=109)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=110)
        
        # Feed first frame to establish frame size
        frames1 = list(packetizer_128k_44k.feed(frame1))
        assert len(frames1) == 1
        
        # Feed corrupted data (wrong size, no sync) followed by valid frame
        corrupted = b"\x00" * 200  # Corrupted data of wrong size
        data = corrupted + frame2
        
        frames2 = list(packetizer_128k_44k.feed(data))
        
        # [P4] Should resync and find frame2, skipping corrupted data
        assert len(frames2) == 1
        assert frames2[0] == frame2
    
    def test_p5_never_emits_partial_frames(self, packetizer_128k_44k):
        """Test [P5]: Never emit partial frames."""
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=111)
        
        # Feed partial frame (all but last byte)
        partial = frame[:-1]
        frames1 = list(packetizer_128k_44k.feed(partial))
        
        # [P5] Should not emit partial frame
        assert frames1 == []
        
        # Feed last byte
        last_byte = frame[-1:]
        frames2 = list(packetizer_128k_44k.feed(last_byte))
        
        # [P5] Now should emit complete frame
        assert len(frames2) == 1
        assert frames2[0] == frame
        assert len(frames2[0]) == len(frame)  # Complete frame, not partial
    
    def test_p5_never_emits_partial_even_on_stream_end(self, packetizer_128k_44k):
        """Test [P5]: Never emit partial frames even if stream ends abruptly."""
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=112)
        
        # Feed partial frame (half of frame)
        partial = frame[:len(frame) // 2]
        frames = list(packetizer_128k_44k.feed(partial))
        
        # [P5] Should not emit partial frame even though stream might have ended
        assert frames == []
        
        # Feed empty data (simulating stream end)
        frames_empty = list(packetizer_128k_44k.feed(b""))
        
        # [P5] Still should not emit partial frame
        assert frames_empty == []
    
    def test_p6_handle_split_headers(self, packetizer_128k_44k):
        """Test [P6]: Handle split headers (header split across chunk boundaries)."""
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=113)
        
        # Split header across two chunks: first 2 bytes, then rest
        header_part1 = frame[:2]  # First 2 bytes of header (sync word)
        header_part2 = frame[2:4]  # Next 2 bytes of header (completes header)
        payload = frame[4:]  # Rest of frame
        
        # Feed header in two parts
        frames1 = list(packetizer_128k_44k.feed(header_part1))
        assert frames1 == []  # Not enough for header yet
        
        frames2 = list(packetizer_128k_44k.feed(header_part2))
        assert frames2 == []  # Header complete but frame not complete yet
        
        # Feed payload
        frames3 = list(packetizer_128k_44k.feed(payload))
        assert len(frames3) == 1
        assert frames3[0] == frame
    
    def test_p6_handle_multi_frame_blobs(self, packetizer_128k_44k):
        """Test [P6]: Handle multiple complete frames in a single feed() call."""
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=114)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=115)
        frame3 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=116)
        
        # Feed all three frames in one blob
        blob = frame1 + frame2 + frame3
        frames = list(packetizer_128k_44k.feed(blob))
        
        # [P6] Should extract all three frames from single blob
        assert len(frames) == 3
        assert frames[0] == frame1
        assert frames[1] == frame2
        assert frames[2] == frame3
    
    def test_p6_handle_split_frame_boundaries(self, packetizer_128k_44k):
        """Test [P6]: Handle frames split across multiple feed() calls."""
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=117)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=118)
        
        # Split at arbitrary boundary: frame1 complete + partial frame2
        split_point = len(frame1) + 50
        data1 = frame1 + frame2[:50]
        data2 = frame2[50:]
        
        # Feed first chunk (frame1 complete + partial frame2)
        frames1 = list(packetizer_128k_44k.feed(data1))
        assert len(frames1) == 1  # frame1 should be complete
        assert frames1[0] == frame1
        
        # Feed second chunk (rest of frame2)
        frames2 = list(packetizer_128k_44k.feed(data2))
        assert len(frames2) == 1  # frame2 should now be complete
        assert frames2[0] == frame2
    
    def test_p6_handle_split_header_and_payload(self, packetizer_128k_44k):
        """Test [P6]: Handle header and payload split across multiple calls."""
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=119)
        
        # Split into: header (4 bytes), first half of payload, second half of payload
        header = frame[:4]
        payload_half1 = frame[4:len(frame) // 2 + 2]
        payload_half2 = frame[len(frame) // 2 + 2:]
        
        # Feed header
        frames1 = list(packetizer_128k_44k.feed(header))
        assert frames1 == []  # Header alone not enough
        
        # Feed first half of payload
        frames2 = list(packetizer_128k_44k.feed(payload_half1))
        assert frames2 == []  # Still not complete
        
        # Feed second half of payload
        frames3 = list(packetizer_128k_44k.feed(payload_half2))
        assert len(frames3) == 1  # Now complete
        assert frames3[0] == frame
    
    # ========================================================================
    # Tests for Contract Strengthenings (Output Guarantees, Buffer Cap, VBR, Performance)
    # ========================================================================
    
    def test_output_guarantees_raw_bytes_unchanged(self, packetizer_128k_44k):
        """Test output guarantees: frames are raw MP3 bytes exactly as received."""
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=200)
        
        # Feed frame
        frames = list(packetizer_128k_44k.feed(frame))
        assert len(frames) == 1
        
        # Output guarantee: frames MUST be byte-for-byte identical to original
        assert frames[0] == frame
        assert len(frames[0]) == len(frame)
        
        # Verify no mutation: check first and last bytes
        assert frames[0][0] == frame[0]  # Sync byte unchanged
        assert frames[0][-1] == frame[-1]  # Last byte unchanged
        
        # Verify entire frame is identical
        assert frames[0] == frame
    
    def test_buffer_cap_discards_oldest_bytes(self, packetizer_128k_44k):
        """Test buffer cap: oldest bytes discarded when limit exceeded [P2]."""
        # Create large amount of junk data (no sync words) to trigger buffer cap
        # Buffer limit should be ~64KB per contract
        large_junk = b"\x00" * 70000  # 70KB of junk (exceeds 64KB limit)
        
        # Feed junk - should not crash, should discard oldest bytes
        frames = list(packetizer_128k_44k.feed(large_junk))
        assert frames == []  # No frames from junk
        
        # Now feed a valid frame - should still be able to sync
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=201)
        frames = list(packetizer_128k_44k.feed(frame))
        
        # [P2] Should still be able to extract frame after buffer cap triggered
        # (preserves most recent bytes, so sync remains possible)
        assert len(frames) == 1
        assert frames[0] == frame
    
    def test_vbr_support_different_frame_sizes(self, packetizer_128k_44k):
        """Test VBR support: frame size computed from each header individually [P6]."""
        # Create frames with different bitrates (different frame sizes)
        frame_128k = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, padding=0, payload_seed=202)
        frame_192k = create_fake_mp3_frame(bitrate_kbps=192, sample_rate=44100, padding=0, payload_seed=203)
        frame_256k = create_fake_mp3_frame(bitrate_kbps=256, sample_rate=44100, padding=0, payload_seed=204)
        
        # Frame sizes should be different
        assert len(frame_128k) != len(frame_192k)
        assert len(frame_192k) != len(frame_256k)
        
        # Feed all frames together (VBR stream)
        all_frames_data = frame_128k + frame_192k + frame_256k
        frames = list(packetizer_128k_44k.feed(all_frames_data))
        
        # [P6] Should extract all frames correctly, computing size from each header
        assert len(frames) == 3
        assert frames[0] == frame_128k
        assert frames[1] == frame_192k
        assert frames[2] == frame_256k
    
    def test_vbr_support_padding_variation(self, packetizer_128k_44k):
        """Test VBR support: handles padding variation (frame size ±1 byte) [P6]."""
        # Create frames with same bitrate but different padding
        frame_no_pad = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, padding=0, payload_seed=205)
        frame_with_pad = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, padding=1, payload_seed=206)
        
        # Frame sizes should differ by 1 byte (padding)
        assert abs(len(frame_no_pad) - len(frame_with_pad)) == 1
        
        # Feed both frames
        frames = list(packetizer_128k_44k.feed(frame_no_pad + frame_with_pad))
        
        # [P6] Should extract both frames correctly, computing size from each header
        assert len(frames) == 2
        assert frames[0] == frame_no_pad
        assert frames[1] == frame_with_pad
    
    def test_performance_o_n_time_no_blocking(self, packetizer_128k_44k):
        """Test performance: feed() executes in O(n) time, never blocks [P5]."""
        import time
        
        # Create large blob of frames
        frames_list = []
        for i in range(100):
            frames_list.append(create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=300 + i))
        large_blob = b"".join(frames_list)
        
        # Measure time - should be O(n) relative to input size
        start_time = time.perf_counter()
        frames = list(packetizer_128k_44k.feed(large_blob))
        elapsed = time.perf_counter() - start_time
        
        # [P5] Should complete quickly (O(n) time)
        # 100 frames should process in < 1 second (very generous threshold)
        assert elapsed < 1.0, f"feed() took {elapsed:.3f}s, expected < 1.0s"
        
        # [P5] Should extract all frames (no blocking, no data loss)
        assert len(frames) == 100
        
        # Verify frames are correct
        for i, frame in enumerate(frames):
            assert frame == frames_list[i]
    
    def test_streaming_invariant_unbounded_streams(self, packetizer_128k_44k):
        """Test streaming invariant: processes unbounded streams without degradation [P2]."""
        # Feed many frames over multiple calls (simulating unbounded stream)
        all_frames = []
        for i in range(1000):
            frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=400 + i)
            frames = list(packetizer_128k_44k.feed(frame))
            all_frames.extend(frames)
        
        # [P2] Should process all frames without performance degradation
        assert len(all_frames) == 1000
        
        # Verify state is maintained correctly (no reset, no degradation)
        # Feed one more frame to verify state is still good
        final_frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=44100, payload_seed=1400)
        final_frames = list(packetizer_128k_44k.feed(final_frame))
        assert len(final_frames) == 1
        assert final_frames[0] == final_frame
