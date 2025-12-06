"""
Contract tests for Tower Encoder Drain Thread

See docs/contracts/TOWER_ENCODER_CONTRACT.md
Covers: EncoderOutputDrainThread behavior, stall detection, frame feeding
New contract: [D1]–[D4] (EncoderOutputDrainThread Contract)
"""

import pytest
import select
import threading
import time
from io import BytesIO
from unittest.mock import Mock, patch, MagicMock

from tower.audio.mp3_packetizer import MP3Packetizer
from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.drain_thread import EncoderOutputDrainThread


# Helper to create fake MP3 frames (same as in packetizer tests)
def create_fake_mp3_frame(
    bitrate_kbps: int = 128,
    sample_rate: int = 48000,
    padding: int = 0,
    payload_seed: int = None
) -> bytes:
    """Create a fake MP3 frame with valid sync word and header."""
    import random
    
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
        0xFF,  # Sync byte
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
    
    # Create payload
    payload_size = frame_size - 4
    if payload_seed is not None:
        random.seed(payload_seed)
    else:
        random.seed(42)  # Default seed
    
    payload = bytes([random.randint(0, 255) for _ in range(payload_size)])
    
    return bytes(header) + payload


class TestEncoderOutputDrainThread:
    """Tests for EncoderOutputDrainThread."""
    
    @pytest.fixture
    def mp3_buffer(self):
        """Create MP3 buffer for testing."""
        return FrameRingBuffer(capacity=100)
    
    @pytest.fixture
    def packetizer(self):
        """Create MP3Packetizer for testing."""
        return MP3Packetizer()
    
    @pytest.fixture
    def mock_stdout(self):
        """Create mock stdout that can be read from."""
        # Use a pipe-like object that works with select
        # For testing, we'll use a mock that simulates readable stdout
        mock = MagicMock()
        mock.fileno.return_value = 1  # Valid file descriptor
        return mock
    
    @pytest.fixture
    def on_stall_callback(self):
        """Create mock stall callback."""
        return Mock()
    
    @pytest.fixture
    def shutdown_event(self):
        """Create shutdown event."""
        return threading.Event()
    
    @pytest.fixture
    def drain_thread(
        self, mp3_buffer, packetizer, mock_stdout, on_stall_callback, shutdown_event
    ):
        """Create EncoderOutputDrainThread instance."""
        return EncoderOutputDrainThread(
            stdout=mock_stdout,
            mp3_buffer=mp3_buffer,
            packetizer=packetizer,
            stall_threshold_ms=100,  # Short threshold for testing
            on_stall=on_stall_callback,
            shutdown_event=shutdown_event,
        )
    
    def test_feeds_packetizer_correctly(self, drain_thread, packetizer, mock_stdout, mp3_buffer):
        """Test that drain thread feeds bytes to packetizer correctly [D1]."""
        # [D1] Drain thread MUST call packetizer.feed(data) for each read
        # [P3] feed() returns iterable of complete MP3 frames
        # [D3] Each frame pushed via push_frame()
        # Create a fake MP3 frame
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=48000, payload_seed=1)
        
        # Configure mock to return frame data
        mock_stdout.read.return_value = frame
        
        # Mock select to indicate data is available
        with patch('select.select', return_value=([mock_stdout], [], [])):
            # Start thread
            drain_thread.start()
            time.sleep(0.2)  # Give thread time to read
            
            # Stop thread
            drain_thread.stop(timeout=1.0)
        
        # [D1] Packetizer should have received the data via feed()
        # [P3] feed() yields complete frames incrementally
        # [D3] Frames should be pushed to buffer via push_frame()
        assert len(mp3_buffer) > 0
        # Verify frame is complete (not partial)
        popped_frame = mp3_buffer.pop_frame()
        assert popped_frame is not None
        assert len(popped_frame) == len(frame)  # Complete frame
    
    def test_pushes_frames_into_mp3_buffer(self, drain_thread, mp3_buffer, mock_stdout):
        """Test that drain thread pushes complete frames into MP3 buffer [D1], [D2], [D3]."""
        # [D1] Drain thread calls packetizer.feed(data) and iterates frames
        # [P3] feed() yields frames incrementally (may yield multiple frames per call)
        # [D2] MUST NOT return partial frames (packetizer ensures this)
        # [D3] FrameRingBuffer interface is push_frame(frame: bytes) - called once per complete frame
        # Create multiple fake MP3 frames
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=48000, payload_seed=1)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=48000, payload_seed=2)
        
        # Configure mock to return frames (first call returns both, then EOF)
        mock_stdout.read.side_effect = [frame1 + frame2, b""]
        
        # Mock select to indicate data is available
        with patch('select.select', return_value=([mock_stdout], [], [])):
            # Start thread
            drain_thread.start()
            time.sleep(0.3)  # Give thread time to read and process
            
            # Stop thread
            drain_thread.stop(timeout=1.0)
        
        # [D3] Buffer should contain frames pushed via push_frame()
        # [P3] feed() should yield both frames incrementally
        assert len(mp3_buffer) >= 2  # Both frames should be pushed
        # Verify frames are complete
        popped1 = mp3_buffer.pop_frame()
        popped2 = mp3_buffer.pop_frame()
        assert popped1 == frame1
        assert popped2 == frame2
    
    def test_detects_stall_and_triggers_restart(self, drain_thread, on_stall_callback, shutdown_event):
        """Test that drain thread detects stall and triggers restart callback [D4]."""
        # [D4] Restart logic triggers when no frames output for STALL_TIMEOUT
        # Create a mock stdout that never has data
        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 1
        
        # Mock select to return no ready files (simulating no data)
        with patch('select.select', return_value=([], [], [])):
            drain_thread.stdout = mock_stdout
            drain_thread._last_data_time = time.monotonic() - 0.2  # Set old timestamp (200ms ago)
            
            # Start thread
            drain_thread.start()
            time.sleep(0.15)  # Wait for stall detection (threshold is 100ms)
            
            # Stop thread
            drain_thread.stop(timeout=1.0)
        
        # [D4] Stall callback should have been called when no frames for threshold
        assert on_stall_callback.called
    
    def test_no_blocking_behavior(self, drain_thread, mock_stdout, shutdown_event):
        """Test that drain thread never blocks permanently."""
        # Create a mock stdout that blocks on read
        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 1
        mock_stdout.read.side_effect = lambda size: b""  # Always returns empty (EOF)
        
        drain_thread.stdout = mock_stdout
        
        # Mock select to simulate data available, but read returns EOF
        with patch('select.select', return_value=([mock_stdout], [], [])):
            drain_thread.start()
            time.sleep(0.1)  # Thread should handle EOF and exit quickly
            
            # Stop thread
            drain_thread.stop(timeout=1.0)
        
        # Thread should have exited (not blocked)
        assert not drain_thread.is_alive()
    
    def test_thread_exits_cleanly_on_stop(self, drain_thread, mock_stdout, shutdown_event):
        """Test that thread exits cleanly when stop() is called."""
        # Write some data to keep thread busy
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=48000, payload_seed=1)
        mock_stdout.write(frame)
        mock_stdout.seek(0)
        
        # Start thread
        drain_thread.start()
        time.sleep(0.1)  # Let it run briefly
        
        # Stop thread
        start_stop = time.time()
        drain_thread.stop(timeout=1.0)
        stop_elapsed = time.time() - start_stop
        
        # Should stop quickly
        assert stop_elapsed < 1.0
        # Thread should be stopped
        assert not drain_thread.is_alive()
    
    def test_handles_eof_gracefully(self, drain_thread, on_stall_callback, mock_stdout):
        """Test that thread handles EOF (encoder death) gracefully."""
        # Create stdout that immediately returns EOF
        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 1
        mock_stdout.read.return_value = b""  # EOF
        
        drain_thread.stdout = mock_stdout
        
        # Mock select to indicate data available
        with patch('select.select', return_value=([mock_stdout], [], [])):
            drain_thread.start()
            time.sleep(0.1)  # Give thread time to detect EOF
            
            # Stop thread
            drain_thread.stop(timeout=1.0)
        
        # Stall callback should be called (EOF = encoder died)
        assert on_stall_callback.called
    
    def test_handles_select_errors(self, drain_thread, mock_stdout, shutdown_event):
        """Test that thread handles select() errors gracefully."""
        # Create stdout that causes select error
        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 1
        
        drain_thread.stdout = mock_stdout
        
        # Mock select to raise OSError
        with patch('select.select', side_effect=OSError("Bad file descriptor")):
            drain_thread.start()
            time.sleep(0.1)  # Give thread time to handle error
            
            # Stop thread
            drain_thread.stop(timeout=1.0)
        
        # Thread should have exited cleanly
        assert not drain_thread.is_alive()
    
    def test_reads_in_chunks(self, drain_thread, mp3_buffer, mock_stdout):
        """Test that thread reads data in chunks (~4096 bytes) [D1], [P2], [P3]."""
        # [D1] Drain thread reads in chunks and feeds to packetizer
        # [P2] Packetizer maintains internal streaming state across calls
        # [P3] feed() yields frames incrementally as they become complete
        # Create multiple frames
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=48000, payload_seed=1)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=48000, payload_seed=2)
        frame3 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=48000, payload_seed=3)
        large_data = frame1 + frame2 + frame3
        
        # Configure mock to return data in chunks, then EOF
        read_calls = []
        chunk_size = 4096
        for i in range(0, len(large_data), chunk_size):
            read_calls.append(large_data[i:i + chunk_size])
        read_calls.append(b"")  # EOF
        
        mock_stdout.read.side_effect = read_calls
        
        # Mock select to indicate data is available
        with patch('select.select', return_value=([mock_stdout], [], [])):
            # Start thread
            drain_thread.start()
            time.sleep(0.3)  # Give thread time to read
            
            # Stop thread
            drain_thread.stop(timeout=1.0)
        
        # [P2] Partial chunks accumulate until full frame appears
        # [P3] feed() yields frames incrementally as they become complete
        # [D3] push_frame() called once per complete frame
        assert len(mp3_buffer) >= 3  # All three frames should be complete
        # Verify frames are complete and correct
        assert mp3_buffer.pop_frame() == frame1
        assert mp3_buffer.pop_frame() == frame2
        assert mp3_buffer.pop_frame() == frame3
    
    def test_partial_chunks_accumulate_until_full_frame(self, drain_thread, mp3_buffer, mock_stdout):
        """Test that partial chunks accumulate until a full frame appears [P2], [P3], [D3]."""
        # [P1] Accepts arbitrary byte chunks including incomplete frames
        # [P2] Maintains internal streaming state across calls
        # [P3] Returns zero or more complete MP3 frames (zero until frame complete)
        # [D3] push_frame() called once per complete frame
        frame = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=48000, payload_seed=10)
        
        # Split frame into multiple partial chunks
        chunk1 = frame[:100]  # First 100 bytes
        chunk2 = frame[100:200]  # Next 100 bytes
        chunk3 = frame[200:]  # Rest of frame
        
        # Configure mock to return chunks incrementally
        mock_stdout.read.side_effect = [chunk1, chunk2, chunk3, b""]
        
        # Track push_frame calls
        original_push_frame = mp3_buffer.push_frame
        push_frame_calls = []
        def tracked_push_frame(frame_data):
            push_frame_calls.append(frame_data)
            return original_push_frame(frame_data)
        mp3_buffer.push_frame = tracked_push_frame
        
        # Mock select to indicate data is available
        with patch('select.select', return_value=([mock_stdout], [], [])):
            # Start thread
            drain_thread.start()
            time.sleep(0.3)  # Give thread time to process all chunks
            
            # Stop thread
            drain_thread.stop(timeout=1.0)
        
        # [P2] Partial chunks should accumulate
        # [P3] feed() should yield zero frames for chunk1 and chunk2, then one frame for chunk3
        # [D3] push_frame() should be called exactly once when frame becomes complete
        assert len(push_frame_calls) == 1  # Called once per complete frame
        assert push_frame_calls[0] == frame  # Complete frame pushed
        assert len(mp3_buffer) == 1  # One complete frame in buffer
    
    def test_feed_yields_frames_incrementally(self, drain_thread, mp3_buffer, mock_stdout):
        """Test that feed() yields frames incrementally [P3], [D3]."""
        # [P3] feed() returns zero or more complete MP3 frames incrementally
        # [D3] push_frame() is called once per complete frame yielded
        frame1 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=48000, payload_seed=20)
        frame2 = create_fake_mp3_frame(bitrate_kbps=128, sample_rate=48000, payload_seed=21)
        
        # First read: frame1 complete + partial frame2
        # Second read: rest of frame2
        split_point = len(frame1) + 50
        data1 = frame1 + frame2[:50]
        data2 = frame2[50:]
        
        mock_stdout.read.side_effect = [data1, data2, b""]
        
        # Track push_frame calls
        original_push_frame = mp3_buffer.push_frame
        push_frame_calls = []
        def tracked_push_frame(frame_data):
            push_frame_calls.append(frame_data)
            return original_push_frame(frame_data)
        mp3_buffer.push_frame = tracked_push_frame
        
        # Mock select to indicate data is available
        with patch('select.select', return_value=([mock_stdout], [], [])):
            # Start thread
            drain_thread.start()
            time.sleep(0.3)  # Give thread time to process
            
            # Stop thread
            drain_thread.stop(timeout=1.0)
        
        # [P3] feed() should yield frame1 immediately from first data chunk
        # [P3] feed() should yield frame2 from second data chunk (after accumulation)
        # [D3] push_frame() called once per frame (twice total)
        assert len(push_frame_calls) == 2  # One call per complete frame
        assert push_frame_calls[0] == frame1
        assert push_frame_calls[1] == frame2
        assert len(mp3_buffer) == 2  # Both frames in buffer

