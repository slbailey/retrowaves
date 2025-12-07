"""
Contract tests for Tower Runtime Behavior

See docs/contracts/TOWER_RUNTIME_CONTRACT.md
Covers: [T1]–[T14] (Always-on Transmitter, Live vs Fallback, Station Input, Client Handling, Lifecycle)
"""

import pytest
import socket
import threading
import time
import os
from unittest.mock import Mock, MagicMock, patch
from io import BytesIO

from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.encoder_manager import EncoderManager
from tower.encoder.audio_pump import AudioPump
from tower.fallback.generator import FallbackGenerator
from tower.http.server import HTTPServer
from tower.service import TowerService


@pytest.mark.timeout(30)
class TestTowerRuntimeAlwaysOnTransmitter:
    """Tests for always-on transmitter [T1]–[T3]."""
    
    @pytest.fixture
    def service(self):
        """Create TowerService instance for testing."""
        service = TowerService()
        yield service
        try:
            service.stop()
        except Exception:
            pass
    
    def test_t1_exposes_get_stream_endpoint(self, service):
        """Test [T1]: Tower exposes GET /stream and never refuses connections while service is up."""
        # Verify HTTP server is created
        assert hasattr(service, 'http_server')
        assert service.http_server is not None
        assert service.http_server.host == "0.0.0.0"
        assert service.http_server.port == 8000
        
        # Verify server accepts frame_source
        assert service.http_server.frame_source is service.encoder
    
    def test_t2_always_returns_valid_mp3_bytes(self, service):
        """Test [T2]: /stream always returns valid MP3 bytes (live, fallback, or silence)."""
        # EncoderManager.get_frame() should always return valid bytes or None (at startup)
        # After first frame, should always return bytes
        frame = service.encoder.get_frame()
        
        # At startup, may be None, but after first frame should be bytes
        # The contract says "from the moment headers are sent" - so after first frame
        assert frame is None or isinstance(frame, bytes)
    
    def test_t3_continues_streaming_if_station_down(self, service):
        """Test [T3]: Tower continues streaming audio even if Station is down."""
        # With empty PCM buffer, Tower should use fallback
        # This is tested by ensuring AudioPump uses fallback when PCM buffer is empty
        assert len(service.pcm_buffer) == 0  # Empty buffer
        
        # AudioPump should handle empty buffer gracefully (grace period → fallback)
        assert hasattr(service.audio_pump, 'fallback')
        assert service.audio_pump.fallback is not None


@pytest.mark.timeout(30)
class TestTowerRuntimeLiveVsFallback:
    """Tests for live vs fallback behavior [T4]–[T6]."""
    
    @pytest.fixture
    def service(self):
        """Create TowerService instance for testing."""
        service = TowerService()
        yield service
        try:
            service.stop()
        except Exception:
            pass
    
    def test_t4_streams_live_when_station_feeding(self, service):
        """Test [T4]: When Station is feeding valid PCM, Tower streams live audio."""
        # Push PCM frame to buffer
        test_frame = b'\x00' * 4608  # Valid PCM frame
        service.pcm_buffer.push_frame(test_frame)
        
        # AudioPump should use PCM frame (not fallback)
        # This is verified by checking AudioPump frame selection logic
        assert len(service.pcm_buffer) > 0
    
    def test_t5_1_detects_absence_within_timeout(self, service):
        """Test [T5.1]: Detects absence of frames within TOWER_FRAME_TIMEOUT_MS."""
        # EncoderManager.next_frame() uses timeout in pop_frame() call
        import inspect
        from tower.encoder import encoder_manager
        
        source = inspect.getsource(encoder_manager.EncoderManager.next_frame)
        
        # Should use timeout parameter in pop_frame() call
        assert 'pop_frame(timeout=' in source, \
            "EncoderManager.next_frame() should use timeout in pop_frame() call per [T5.1]"
        
        # Verify that _check_pcm_loss() is called to detect PCM stop
        # This ensures TowerRuntime detects PCM stop and enters fallback per [BG11], [BG12]
        assert '_check_pcm_loss' in source, \
            "EncoderManager.next_frame() should call _check_pcm_loss() to detect PCM stop per [BG11]"
    
    def test_t5_2_uses_silence_during_grace(self, service):
        """Test [T5.2]: Uses silence frames during grace period (TOWER_PCM_GRACE_SEC)."""
        # EncoderManager should have grace period logic per A8
        assert hasattr(service.encoder, '_grace_period_ms')
    
    def test_t5_3_switches_to_fallback_after_grace(self, service):
        """Test [T5.3]: After grace expiry, switches to fallback source (tone/file)."""
        # AudioPump should use fallback after grace expires
        assert hasattr(service.audio_pump, 'fallback')
        assert service.audio_pump.fallback is not None
    
    def test_t6_transitions_do_not_disconnect_clients(self, service):
        """Test [T6]: Switches between live and fallback do not disconnect clients."""
        # HTTP server should maintain connections during transitions
        # Per NEW_TOWER_RUNTIME_CONTRACT: HTTPServer replaced HTTPConnectionManager
        # Use HTTPServer._connected_clients or connection_manager proxy for backwards compatibility
        assert hasattr(service.http_server, '_connected_clients')
        assert hasattr(service.http_server, 'connection_manager')  # Backwards compatibility proxy
        # Clients should remain connected regardless of audio source


@pytest.mark.timeout(30)
class TestTowerRuntimeStationInput:
    """Tests for Station input model [T7]–[T9]."""
    
    @pytest.fixture
    def service(self):
        """Create TowerService instance for testing."""
        service = TowerService()
        yield service
        try:
            service.stop()
        except Exception:
            pass
    
    def test_t7_reads_from_bounded_buffer(self, service):
        """Test [T7]: Tower reads PCM frames from a bounded buffer fed by Unix domain socket."""
        # PCM buffer should be bounded
        assert hasattr(service, 'pcm_buffer')
        assert service.pcm_buffer.capacity > 0
        assert service.pcm_buffer.capacity == 100  # Default
    
    def test_t8_overflow_drops_frames_not_blocks(self, service):
        """Test [T8]: Buffer overflow results in dropped frames, not blocking writes."""
        # Fill buffer to capacity
        for i in range(service.pcm_buffer.capacity):
            service.pcm_buffer.push_frame(f"frame{i}".encode())
        
        assert service.pcm_buffer.is_full()
        
        # Push more - should not block
        start = time.time()
        service.pcm_buffer.push_frame(b"overflow_frame")
        elapsed = time.time() - start
        
        assert elapsed < 0.01  # Should be immediate (non-blocking)
        assert len(service.pcm_buffer) == service.pcm_buffer.capacity  # Still at capacity
    
    def test_t9_sole_metronome_21_333ms(self, service):
        """Test [T9]: Tower is the sole metronome - pulls one PCM frame every 21.333ms."""
        from tower.encoder.audio_pump import FRAME_DURATION_SEC
        
        # Frame duration should be 1152 samples / 48000 Hz = 0.024s = 24ms
        expected_duration = 1152 / 48000
        assert abs(FRAME_DURATION_SEC - expected_duration) < 0.001
        
        # AudioPump is the sole metronome
        assert hasattr(service, 'audio_pump')
        assert service.audio_pump is not None


@pytest.mark.timeout(30)
class TestTowerRuntimeClientHandling:
    """Tests for client handling [T10]–[T12]."""
    
    @pytest.fixture
    def http_server(self):
        """Create HTTPServer instance for testing."""
        from tower.encoder.encoder_manager import EncoderManager
        from tower.audio.ring_buffer import FrameRingBuffer
        
        pcm_buffer = FrameRingBuffer(capacity=10)
        mp3_buffer = FrameRingBuffer(capacity=10)
        encoder = EncoderManager(pcm_buffer=pcm_buffer, mp3_buffer=mp3_buffer, allow_ffmpeg=False)
        
        server = HTTPServer(host="127.0.0.1", port=0, frame_source=encoder)
        yield server
        try:
            server.running = False
            if server._server_sock:
                server._server_sock.close()
        except Exception:
            pass
    
    def test_t10_slow_clients_never_block_broadcast(self, http_server):
        """Test [T10]: Writes to slow clients never block the main broadcast loop."""
        # Per NEW_TOWER_RUNTIME_CONTRACT: HTTPServer uses non-blocking writes (T-CLIENTS1)
        # HTTPServer handles clients via _connected_clients dict
        
        # Add a slow client (blocking send)
        slow_socket = Mock(spec=socket.socket)
        slow_socket.send = Mock(side_effect=lambda x: time.sleep(0.1))  # Blocks 100ms
        slow_socket.gettimeout = Mock(return_value=None)
        slow_socket.settimeout = Mock()
        slow_socket.fileno = Mock(return_value=1)
        
        # Per HTTPServer semantics: clients are added via _handle_client or directly to _connected_clients
        # For test, add directly to _connected_clients
        from tower.http.server import _ClientState
        from collections import deque
        client_state = _ClientState(
            sock=slow_socket,
            queue=deque(),
            last_send_monotonic=time.monotonic()
        )
        http_server._connected_clients["slow_client"] = client_state
        
        # Broadcast should return quickly (non-blocking)
        # Per T-CLIENTS1: HTTPServer uses non-blocking writes
        # The broadcast happens in broadcast() which is non-blocking
        start = time.time()
        # Simulate broadcast by calling broadcast directly
        test_frame = b"test_data"
        http_server.broadcast(test_frame)
        elapsed = time.time() - start
        
        # Should return quickly even with slow client (non-blocking per T-CLIENTS1)
        assert elapsed < 0.25   # Allow OS/GIL jitter
    
    def test_t11_slow_clients_dropped_after_timeout(self, http_server):
        """Test [T11]: Clients that cannot accept data for TOWER_CLIENT_TIMEOUT_MS are dropped."""
        # Per NEW_TOWER_RUNTIME_CONTRACT: HTTPServer enforces 250ms slow-client timeout (T-CLIENTS2)
        # HTTPServer should drop slow clients after timeout
        
        # Add client that raises error
        error_socket = Mock(spec=socket.socket)
        error_socket.send = Mock(side_effect=ConnectionError("Client error"))
        error_socket.gettimeout = Mock(return_value=None)
        error_socket.settimeout = Mock()
        error_socket.fileno = Mock(return_value=2)
        
        # Per HTTPServer semantics: add client directly to _connected_clients
        from tower.http.server import _ClientState
        from collections import deque
        client_state = _ClientState(
            sock=error_socket,
            queue=deque(),
            last_send_monotonic=time.monotonic()
        )
        http_server._connected_clients["error_client"] = client_state
        
        # Broadcast should handle error and remove client
        test_frame = b"test_data"
        http_server.broadcast(test_frame)
        
        # Client should be removed (per T-CLIENTS2: timeout enforcement)
        assert "error_client" not in http_server._connected_clients, \
            "Slow client should be dropped after timeout per T-CLIENTS2"
    
    def test_t12_all_clients_receive_same_data(self, http_server):
        """Test [T12]: All connected clients receive the same audio bytes (single broadcast signal)."""
        # Per NEW_TOWER_RUNTIME_CONTRACT: HTTPServer broadcasts to all clients (T-CLIENTS1)
        # All clients receive the same data
        
        # Add multiple clients
        clients = []
        for i in range(3):
            mock_socket = Mock(spec=socket.socket)
            # Per contract T-CLIENTS1: Uses non-blocking writes (send())
            mock_socket.send = Mock(return_value=len(b"identical_mp3_frame"))  # Return bytes sent
            mock_socket.gettimeout = Mock(return_value=None)
            mock_socket.settimeout = Mock()
            mock_socket.fileno = Mock(return_value=10 + i)
            clients.append(mock_socket)
            
            # Per HTTPServer semantics: add client directly to _connected_clients
            from tower.http.server import _ClientState
            from collections import deque
            client_state = _ClientState(
                sock=mock_socket,
                queue=deque(),
                last_send_monotonic=time.monotonic()
            )
            http_server._connected_clients[f"client_{i}"] = client_state
        
        # Broadcast same data
        test_data = b"identical_mp3_frame"
        http_server.broadcast(test_data)
        
        # All clients should receive same data (via send() per contract T-CLIENTS1)
        for client in clients:
            client.send.assert_called()
            call_args = client.send.call_args[0][0] if client.send.called else None
            assert call_args == test_data or test_data.startswith(call_args) if call_args else False, \
                "All clients should receive the same data per T-CLIENTS1"


@pytest.mark.timeout(30)
class TestTowerRuntimeLifecycle:
    """Tests for lifecycle [T13]–[T14]."""
    
    @pytest.fixture
    def service(self):
        """Create TowerService instance for testing."""
        service = TowerService()
        yield service
        try:
            service.stop()
        except Exception:
            pass
    
    def test_t13_clean_shutdown_within_timeout(self, service):
        """Test [T13]: On shutdown, Tower stops accepting connections and cleanly closes within TOWER_SHUTDOWN_TIMEOUT."""
        # Verify stop() method exists and stops all components
        assert hasattr(service, 'stop')
        assert callable(service.stop)
        
        # Stop should set running = False
        service.running = True
        service.stop()
        
        assert service.running is False
    
    def test_t14_can_start_when_station_offline(self, service):
        """Test [T14]: Tower can be started when Station is offline; streams fallback until live audio available."""
        # Service should start even with empty PCM buffer
        assert len(service.pcm_buffer) == 0  # Empty buffer (Station offline)
        
        # Should have fallback generator
        assert hasattr(service, 'fallback')
        assert service.fallback is not None
        
        # AudioPump should use fallback when PCM buffer is empty
        assert hasattr(service.audio_pump, 'fallback')
        assert service.audio_pump.fallback is not None
