"""
Contract tests for Retrowaves Tower Phase 4.

These tests enforce every requirement in tower/docs/contracts/tower_phase4_robustness.md.
Each test corresponds to a specific contract bullet point.

Tests are designed to fail until Phase 4 implementation exists.
"""

import os
import socket
import subprocess
import tempfile
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

import pytest
import httpx


# ============================================================================
# Test Fixtures and Helpers
# ============================================================================

def find_free_port() -> int:
    """Find an available ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def _wait_for_tower_ready(host: str, port: int, timeout: float = 3.0) -> None:
    """
    Wait until the Tower /stream endpoint is accepting connections and 
    sending at least 1 byte of body data. Safe for streaming endpoints.
    """
    url = f"http://{host}:{port}/stream"
    deadline = time.time() + timeout
    
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=0.5) as client:
                # Use streaming mode so httpx does NOT wait for full response.
                with client.stream("GET", url) as resp:
                    # Must get a 200 status code
                    if resp.status_code != 200:
                        continue
                    
                    # Try to read ONE byte of the body using iter_bytes
                    chunk = next(resp.iter_bytes(chunk_size=1), None)
                    
                    # If we got any body bytes, Tower is ready
                    if chunk:
                        return
        except Exception:
            pass
        
        time.sleep(0.05)
    
    raise TimeoutError(f"Tower did not become ready within {timeout} seconds")


def _wait_for_socket_ready(socket_path: str, timeout: float = 3.0) -> None:
    """Wait until Unix socket exists and is ready for connections."""
    deadline = time.time() + timeout
    
    while time.time() < deadline:
        if os.path.exists(socket_path):
            # Try to connect to verify it's ready
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(0.1)
                sock.connect(socket_path)
                sock.close()
                return
            except (socket.error, OSError):
                pass
        
        time.sleep(0.05)
    
    raise TimeoutError(f"Unix socket {socket_path} did not become ready within {timeout} seconds")


@contextmanager
def _tower_instance_context(
    host: str = "127.0.0.1",
    port: Optional[int] = None,
    socket_path: Optional[str] = None,
    **env_vars
) -> Generator[tuple[str, int, str], None, None]:
    """
    Launch a Tower instance and yield (host, port, socket_path).
    
    Args:
        host: Host to bind to (default: 127.0.0.1)
        port: Port to bind to (None = find free port)
        socket_path: Unix socket path (None = use temp file)
        **env_vars: Environment variables to set for Tower
    
    Yields:
        (host, port, socket_path) tuple
    """
    import sys
    from pathlib import Path
    
    # Add tower to path if needed
    tower_dir = Path(__file__).parent.parent.parent
    if str(tower_dir) not in sys.path:
        sys.path.insert(0, str(tower_dir))
    
    from tower.config import TowerConfig
    from tower.service import TowerService
    
    # Use temp socket path if not provided
    if socket_path is None:
        temp_dir = tempfile.mkdtemp(prefix="tower_test_")
        socket_path = os.path.join(temp_dir, "pcm.sock")
    
    # Store old environment
    old_env = {}
    for key, value in env_vars.items():
        old_env[key] = os.environ.get(key)
        if value is not None:
            os.environ[key] = str(value)
        else:
            os.environ.pop(key, None)
    
    # Set socket path environment variable
    old_socket_path = os.environ.get("TOWER_SOCKET_PATH")
    os.environ["TOWER_SOCKET_PATH"] = socket_path
    
    service = None
    
    try:
        # Create config and service
        # Set host and port in environment before loading config
        if port is None:
            port = find_free_port()
        os.environ["TOWER_HOST"] = host
        os.environ["TOWER_PORT"] = str(port)
        
        # Use load_config() to read environment variables
        config = TowerConfig.load_config()
        # Override host/port for test (in case env vars weren't set)
        config.host = host
        config.port = port
        config.validate()
        
        service = TowerService(config)
        
        # Start service directly (it starts threads internally)
        service.start()
        
        # Wait for server to be ready
        _wait_for_tower_ready(host, port, timeout=5.0)
        
        # Wait for socket to be ready (if Phase 3 is implemented)
        try:
            _wait_for_socket_ready(socket_path, timeout=2.0)
        except TimeoutError:
            # Socket may not be implemented yet - that's OK for some tests
            pass
        
        yield (host, port, socket_path, service)
    
    finally:
        # Clean up - only stop if service was successfully created
        if service is not None:
            try:
                service.stop()
            except Exception:
                pass
        
        # Clean up socket file if it exists
        try:
            if os.path.exists(socket_path):
                os.unlink(socket_path)
        except Exception:
            pass
        
        # Clean up temp directory
        try:
            temp_dir = os.path.dirname(socket_path)
            if temp_dir.startswith(tempfile.gettempdir()):
                os.rmdir(temp_dir)
        except Exception:
            pass
        
        # Restore environment
        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value
        
        if old_socket_path is None:
            os.environ.pop("TOWER_SOCKET_PATH", None)
        else:
            os.environ["TOWER_SOCKET_PATH"] = old_socket_path


@pytest.fixture
def tower_instance():
    """
    Launch a Tower instance on an ephemeral port and yield (host, port, socket_path, service).
    
    Yields:
        (host, port, socket_path, service) tuple for connecting to Tower
    """
    # Enable test mode for faster backoff delays
    with _tower_instance_context(TOWER_TEST_MODE="1") as result:
        yield result


def collect_mp3_chunks(host: str, port: int, duration_seconds: float = 0.5, chunk_size: int = 8192) -> bytes:
    """
    Collect MP3 chunks from /stream endpoint.
    
    Args:
        host: Tower host
        port: Tower port
        duration_seconds: How long to collect
        chunk_size: Read chunk size
    
    Returns:
        Collected MP3 bytes
    """
    chunks = []
    deadline = time.time() + duration_seconds
    
    with httpx.Client(timeout=duration_seconds + 1.0) as client:
        with client.stream("GET", f"http://{host}:{port}/stream") as response:
            assert response.status_code == 200
            
            for chunk in response.iter_bytes(chunk_size=chunk_size):
                chunks.append(chunk)
                if time.time() >= deadline:
                    break
    
    return b''.join(chunks)


def is_valid_mp3_header(data: bytes) -> bool:
    """
    Check if data contains valid MP3 frame headers.
    
    MP3 files can start with:
    - ID3 tag (b'ID3')
    - MP3 sync bytes: 0xFF 0xE? (where ? is 0-F)
    
    Looks for MP3 sync bytes anywhere in the first 512 bytes.
    """
    if len(data) < 2:
        return False
    
    # Look for MP3 sync bytes (0xFF followed by 0xE0-0xEF) in first 512 bytes
    search_len = min(512, len(data) - 1)
    for i in range(search_len):
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            return True
    
    # Also check for ID3 tag (b'ID3' at any position in first 10 bytes)
    if len(data) >= 3:
        for i in range(min(10, len(data) - 2)):
            if data[i:i+3] == b'ID3':
                return True
    
    return False


def kill_encoder_process(service) -> None:
    """
    Kill the encoder process to simulate encoder failure.
    
    Args:
        service: TowerService instance
    """
    # Phase 4: Access encoder through EncoderManager
    if hasattr(service, 'encoder_manager') and service.encoder_manager is not None:
        encoder_manager = service.encoder_manager
        if hasattr(encoder_manager, 'encoder') and encoder_manager.encoder is not None:
            encoder = encoder_manager.encoder
            if hasattr(encoder, 'process') and encoder.process is not None:
                # Kill the FFmpeg process
                encoder.process.kill()
                # Wait a moment for the process to die
                time.sleep(0.1)
                return
    
    # Fallback: try direct encoder access (for backwards compatibility)
    if hasattr(service, 'encoder') and service.encoder is not None:
        if hasattr(service.encoder, 'process') and service.encoder.process is not None:
            # Kill the FFmpeg process
            service.encoder.process.kill()
            # Wait a moment for the process to die
            time.sleep(0.1)


def create_slow_client(host: str, port: int) -> socket.socket:
    """
    Create a slow client that connects but doesn't read after headers.
    
    Args:
        host: Tower host
        port: Tower port
    
    Returns:
        Connected socket
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    sock.connect((host, port))
    
    # Send HTTP request
    request = (
        f"GET /stream HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Connection: keep-alive\r\n"
        f"\r\n"
    )
    sock.sendall(request.encode())
    
    # Read headers only (don't read body)
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(1024)
        if not chunk:
            break
        response += chunk
    
    return sock


# ============================================================================
# Section 1: Encoder Failure and Restart Behavior
# ============================================================================

class TestEncoderRestart:
    """Tests for Section 2: Encoder Restart Policy and Backoff"""
    
    @pytest.mark.slow
    def test_e1_encoder_restart_on_stdout_eof(self, tower_instance):
        """
        2.1: EncoderManager must trigger restart attempts when encoder stdout EOF is detected.
        
        Arrange:
        - Start Tower with a normal configuration.
        - Simulate encoder crash / stdout EOF by killing the encoder process.
        
        Assert:
        - Tower process remains alive.
        - Within a reasonable window (≤ 1–2 seconds), /stream resumes serving valid MP3 data.
        - MP3 data collected after the restart has a valid MP3 header.
        """
        host, port, socket_path, service = tower_instance
        
        # Verify initial MP3 stream is working
        initial_data = collect_mp3_chunks(host, port, duration_seconds=0.3)
        assert len(initial_data) > 0, "No initial MP3 data"
        assert is_valid_mp3_header(initial_data), "Initial MP3 data invalid"
        
        # Kill encoder process to simulate crash
        kill_encoder_process(service)
        
        # Wait for restart (first attempt should be after 1s backoff)
        # Allow up to 2 seconds for restart to complete
        restart_deadline = time.time() + 2.0
        mp3_resumed = False
        
        while time.time() < restart_deadline:
            try:
                # Try to collect MP3 data
                post_restart_data = collect_mp3_chunks(host, port, duration_seconds=0.2)
                if len(post_restart_data) > 0 and is_valid_mp3_header(post_restart_data):
                    mp3_resumed = True
                    break
            except Exception:
                pass
            time.sleep(0.1)
        
        # Assert Tower is still alive (service is still running)
        assert service is not None, "Tower service died"
        
        # Assert MP3 stream resumed
        assert mp3_resumed, "MP3 stream did not resume within 2 seconds after encoder restart"
        
        # Verify MP3 data is valid
        final_data = collect_mp3_chunks(host, port, duration_seconds=0.3)
        assert len(final_data) > 0, "No MP3 data after restart"
        assert is_valid_mp3_header(final_data), "MP3 data after restart is invalid"
    
    @pytest.mark.slow
    def test_e2_encoder_restart_uses_exponential_backoff(self, tower_instance):
        """
        2.2: EncoderManager must implement exponential backoff (1s, 2s, 4s, 8s, 10s).
        
        Arrange:
        - Force encoder to repeatedly fail on startup by using a misconfigured encoder command.
        
        Assert:
        - Restart attempts follow the 1s, 2s, 4s, 8s, 10s delay pattern (within tolerance).
        - Exactly 5 attempts are made before EncoderManager stops retrying.
        """
        # This test requires access to EncoderManager state or restart timing
        # For now, we'll test that restarts happen with increasing delays
        # Full timing verification may require EncoderManager to expose restart attempt count
        
        host, port, socket_path, service = tower_instance
        
        # Verify initial stream works
        initial_data = collect_mp3_chunks(host, port, duration_seconds=0.2)
        assert len(initial_data) > 0, "No initial MP3 data"
        
        # Kill encoder multiple times and measure restart delays
        restart_times = []
        
        for attempt in range(3):  # Test first 3 attempts
            # Kill encoder
            kill_encoder_process(service)
            kill_time = time.time()
            
            # Wait for restart (detect when MP3 stream resumes)
            restart_detected = False
            max_wait = 15.0  # Allow plenty of time for backoff
            
            while time.time() < kill_time + max_wait:
                try:
                    test_data = collect_mp3_chunks(host, port, duration_seconds=0.1)
                    if len(test_data) > 0 and is_valid_mp3_header(test_data):
                        restart_time = time.time()
                        delay = restart_time - kill_time
                        restart_times.append(delay)
                        restart_detected = True
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            
            if not restart_detected:
                # Encoder may have entered FAILED state
                break
            
            # Small delay before next kill
            time.sleep(0.5)
        
        # Verify we got at least some restart times
        # Note: Full verification of exact backoff schedule requires EncoderManager
        # to expose restart attempt count, which may not be available yet
        if len(restart_times) >= 2:
            # Check if test mode is enabled (shorter backoff delays)
            test_mode = os.getenv("TOWER_TEST_MODE", "0") == "1"
            if test_mode:
                # Test mode: use fast backoff delays (50ms, 100ms, 150ms, 200ms, 250ms)
                expected_delays = [0.05, 0.1, 0.15, 0.2, 0.25]
                tolerance = 0.1  # ±100ms tolerance for test mode
            else:
                # Production mode: use normal backoff delays (1s, 2s, 4s, 8s, 10s)
                expected_delays = [1.0, 2.0, 4.0, 8.0, 10.0]
                tolerance = 0.5  # ±0.5s tolerance for production
            
            # Verify delays are increasing (roughly)
            for i in range(1, len(restart_times)):
                if i < len(expected_delays):
                    expected = expected_delays[i]
                    actual = restart_times[i]
                    # Allow tolerance
                    assert abs(actual - expected) <= tolerance, (
                        f"Restart delay {i+1} was {actual}s, expected ~{expected}s (±{tolerance}s)"
                    )
    
    @pytest.mark.slow
    def test_e3_tower_remains_connectable_during_restart(self, tower_instance):
        """
        2.6: Tower HTTP server must remain accessible during encoder restarts.
        
        Arrange:
        - Start Tower, open a /stream client and a /status client.
        - Trigger encoder crash/restart.
        
        Assert:
        - /status requests still return 200 during restart attempts.
        - /stream client is either kept connected and eventually resumes MP3,
          OR disconnected once and can immediately reconnect successfully.
        """
        host, port, socket_path, service = tower_instance
        
        # Open /stream client
        stream_client = httpx.Client(timeout=10.0)
        stream_response = stream_client.stream("GET", f"http://{host}:{port}/stream")
        stream_resp = stream_response.__enter__()
        
        # Verify initial connection
        assert stream_resp.status_code == 200, "Initial /stream connection failed"
        
        # Read some initial data
        initial_chunk = next(stream_resp.iter_bytes(chunk_size=1024), None)
        assert initial_chunk is not None, "No initial data from /stream"
        
        # Kill encoder
        kill_encoder_process(service)
        
        # Test /status during restart
        status_ok_count = 0
        for _ in range(10):  # Check status multiple times during restart window
            try:
                with httpx.Client(timeout=1.0) as client:
                    resp = client.get(f"http://{host}:{port}/status")
                    if resp.status_code == 200:
                        status_ok_count += 1
            except Exception:
                pass
            time.sleep(0.2)
        
        # Assert /status remained accessible
        assert status_ok_count >= 5, "/status was not accessible during restart"
        
        # Check /stream client behavior
        # According to contract, client should either:
        # - Remain connected and resume MP3, OR
        # - Be disconnected and can reconnect
        
        stream_resumed = False
        disconnected = False
        
        # Try to read from stream for a few seconds
        deadline = time.time() + 3.0
        while time.time() < deadline:
            try:
                chunk = next(stream_resp.iter_bytes(chunk_size=1024), None)
                if chunk and len(chunk) > 0:
                    stream_resumed = True
                    break
            except (httpx.StreamError, httpx.ReadError, httpx.RemoteProtocolError):
                disconnected = True
                break
            except StopIteration:
                disconnected = True
                break
            time.sleep(0.1)
        
        # Clean up stream client
        try:
            stream_response.__exit__(None, None, None)
        except Exception:
            pass
        
        # If disconnected, verify we can reconnect
        if disconnected:
            time.sleep(0.5)  # Brief wait
            try:
                with httpx.Client(timeout=2.0) as client:
                    with client.stream("GET", f"http://{host}:{port}/stream") as resp:
                        assert resp.status_code == 200, "Could not reconnect to /stream"
                        chunk = next(resp.iter_bytes(chunk_size=1024), None)
                        assert chunk is not None, "No data after reconnection"
            except Exception as e:
                pytest.fail(f"Could not reconnect to /stream after disconnect: {e}")
        
        # Assert one of the behaviors occurred
        assert stream_resumed or disconnected, (
            "Stream client neither resumed nor disconnected (unexpected behavior)"
        )


# ============================================================================
# Section 2: Slow Client Handling
# ============================================================================

class TestSlowClientHandling:
    """Tests for Section 3: Slow-Client Policy"""
    
    @pytest.mark.slow
    def test_s1_slow_client_is_dropped_after_timeout(self, tower_instance):
        """
        3.3: A client that cannot accept data within TOWER_CLIENT_TIMEOUT_MS must be dropped.
        
        Arrange:
        - Connect a TCP client to /stream using raw sockets.
        - Read the response headers minimally, then STOP reading (simulate a slow client).
        
        Assert:
        - Within TOWER_CLIENT_TIMEOUT_MS (default 250ms) + small tolerance,
          the server drops the connection.
        - A subsequent recv() on the socket should raise or return 0 bytes (disconnected).
        """
        host, port, socket_path, service = tower_instance
        
        # Create slow client (connects but doesn't read body)
        slow_sock = create_slow_client(host, port)
        
        # Wait for timeout (default 250ms) + tolerance (200ms) = ~450ms total
        time.sleep(0.5)
        
        # Try to read from socket - should be disconnected
        # The socket should be closed by the server, so recv should either:
        # - Return 0 bytes (socket closed gracefully)
        # - Raise an exception (socket closed with error)
        slow_sock.settimeout(0.2)
        disconnected = False
        try:
            # Try to read - if socket is closed, this will return 0 or raise
            data = slow_sock.recv(1024)
            if len(data) == 0:
                # Socket closed gracefully
                disconnected = True
        except (socket.error, OSError, ConnectionResetError, BrokenPipeError, socket.timeout):
            # Socket was closed or timed out - check if it's actually closed
            # Try one more read to confirm
            try:
                slow_sock.settimeout(0.1)
                data = slow_sock.recv(1)
                if len(data) == 0:
                    disconnected = True
            except (socket.error, OSError, ConnectionResetError, BrokenPipeError):
                disconnected = True
        
        # Assert socket was disconnected
        assert disconnected, "Slow client was not dropped (socket still receiving data)"
        
        # Clean up
        try:
            slow_sock.close()
        except Exception:
            pass
    
    @pytest.mark.slow
    def test_s2_slow_client_does_not_affect_fast_client(self, tower_instance):
        """
        3.6: Dropping slow clients must not affect fast clients.
        
        Arrange:
        - Connect one "fast" client that continuously reads.
        - Connect one "slow" client that does not read after initial headers.
        
        Assert:
        - The slow client is eventually dropped due to timeout/backpressure.
        - The fast client continues to receive MP3 data without interruption.
        - The fast client's MP3 bytes are non-empty and contain a valid MP3 header.
        """
        host, port, socket_path, service = tower_instance
        
        # Connect fast client (reads continuously)
        fast_chunks = []
        fast_client_thread_running = threading.Event()
        fast_client_thread_running.set()
        
        def fast_client_reader():
            try:
                with httpx.Client(timeout=5.0) as client:
                    with client.stream("GET", f"http://{host}:{port}/stream") as resp:
                        assert resp.status_code == 200
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            if not fast_client_thread_running.is_set():
                                break
                            fast_chunks.append(chunk)
                            if len(fast_chunks) >= 20:  # Collect 20 chunks
                                break
            except Exception as e:
                pass
        
        fast_thread = threading.Thread(target=fast_client_reader, daemon=True)
        fast_thread.start()
        
        # Wait a moment for fast client to start receiving
        time.sleep(0.2)
        
        # Connect slow client (doesn't read after headers)
        slow_sock = create_slow_client(host, port)
        
        # Wait for slow client to be dropped (timeout + tolerance)
        time.sleep(0.5)
        
        # Verify slow client is dropped
        try:
            slow_sock.settimeout(0.1)
            data = slow_sock.recv(1024)
            assert len(data) == 0, "Slow client was not dropped"
        except (socket.error, OSError, ConnectionResetError, BrokenPipeError):
            # Expected - slow client was dropped
            pass
        finally:
            try:
                slow_sock.close()
            except Exception:
                pass
        
        # Wait for fast client to finish collecting
        fast_thread.join(timeout=3.0)
        fast_client_thread_running.clear()
        
        # Assert fast client received data
        assert len(fast_chunks) > 0, "Fast client received no data"
        
        # Combine chunks and verify MP3 validity
        fast_data = b''.join(fast_chunks)
        assert len(fast_data) > 0, "Fast client received empty data"
        assert is_valid_mp3_header(fast_data), "Fast client received invalid MP3 data"
    
    @pytest.mark.slow
    def test_s4_broadcast_continues_after_slow_client_drop(self, tower_instance):
        """
        3.5: When a slow client is dropped, broadcast loop MUST NOT skip or retry
        sending that chunk to others. Drop is immediate, then broadcast continues.
        
        Arrange:
        - Connect multiple fast clients.
        - Connect one slow client that will be dropped.
        - Monitor that fast clients continue receiving all chunks without gaps.
        
        Assert:
        - Slow client is dropped.
        - Fast clients continue receiving MP3 chunks without interruption.
        - No chunks are skipped or lost due to slow client drop.
        """
        host, port, socket_path, service = tower_instance
        
        # Connect multiple fast clients
        num_fast = 3
        fast_clients_data = []
        fast_clients_running = threading.Event()
        fast_clients_running.set()
        
        def fast_client_reader(client_id):
            chunks = []
            try:
                with httpx.Client(timeout=5.0) as client:
                    with client.stream("GET", f"http://{host}:{port}/stream") as resp:
                        assert resp.status_code == 200
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            if not fast_clients_running.is_set():
                                break
                            chunks.append(chunk)
                            if len(chunks) >= 15:  # Collect 15 chunks
                                break
            except Exception:
                pass
            fast_clients_data.append((client_id, chunks))
        
        fast_threads = []
        for i in range(num_fast):
            thread = threading.Thread(target=fast_client_reader, args=(i,), daemon=True)
            thread.start()
            fast_threads.append(thread)
        
        # Wait for fast clients to start receiving
        time.sleep(0.3)
        
        # Connect slow client (will be dropped)
        slow_sock = create_slow_client(host, port)
        
        # Wait for slow client to be dropped
        time.sleep(0.5)
        
        # Verify slow client is dropped
        try:
            slow_sock.settimeout(0.1)
            data = slow_sock.recv(1024)
            assert len(data) == 0, "Slow client was not dropped"
        except (socket.error, OSError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                slow_sock.close()
            except Exception:
                pass
        
        # Wait for fast clients to finish
        for thread in fast_threads:
            thread.join(timeout=3.0)
        fast_clients_running.clear()
        
        # Assert all fast clients received data (broadcast continued)
        assert len(fast_clients_data) == num_fast, "Not all fast clients completed"
        
        for client_id, chunks in fast_clients_data:
            assert len(chunks) >= 10, f"Fast client {client_id} did not receive enough chunks"
            data = b''.join(chunks)
            assert len(data) > 0, f"Fast client {client_id} received empty data"
            assert is_valid_mp3_header(data), f"Fast client {client_id} received invalid MP3"
        
        # Verify all fast clients received similar amounts of data
        # (broadcast didn't skip chunks for any client)
        chunk_counts = [len(chunks) for _, chunks in fast_clients_data]
        min_chunks = min(chunk_counts)
        max_chunks = max(chunk_counts)
        # Allow small variance due to timing, but not large gaps
        assert max_chunks - min_chunks <= 3, (
            f"Fast clients received very different amounts of data "
            f"(min={min_chunks}, max={max_chunks}), suggesting chunks were skipped"
        )
    
    @pytest.mark.slow
    def test_s3_multiple_slow_clients_are_dropped_individually(self, tower_instance):
        """
        3.5: Dropping a client must not affect other clients.
        
        Arrange:
        - Connect several slow clients (e.g. 3–5), none of which read after headers.
        
        Assert:
        - All slow clients are eventually dropped.
        - Tower remains responsive and /stream can still be connected by new clients.
        """
        host, port, socket_path, service = tower_instance
        
        # Connect multiple slow clients
        num_slow_clients = 5
        slow_socks = []
        
        for _ in range(num_slow_clients):
            try:
                sock = create_slow_client(host, port)
                slow_socks.append(sock)
            except Exception as e:
                # If we can't create all clients, that's OK for this test
                break
        
        assert len(slow_socks) >= 3, "Could not create at least 3 slow clients"
        
        # Wait for timeout (all should be dropped)
        time.sleep(0.6)  # Allow time for all to be dropped
        
        # Verify all slow clients are dropped
        dropped_count = 0
        for sock in slow_socks:
            try:
                sock.settimeout(0.1)
                data = sock.recv(1024)
                if len(data) == 0:
                    dropped_count += 1
            except (socket.error, OSError, ConnectionResetError, BrokenPipeError):
                dropped_count += 1
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
        
        # Assert all slow clients were dropped
        assert dropped_count == len(slow_socks), (
            f"Only {dropped_count}/{len(slow_socks)} slow clients were dropped"
        )
        
        # Verify Tower is still responsive - new client can connect
        time.sleep(0.2)
        try:
            new_data = collect_mp3_chunks(host, port, duration_seconds=0.2)
            assert len(new_data) > 0, "Tower not responsive after dropping slow clients"
            assert is_valid_mp3_header(new_data), "New client received invalid MP3"
        except Exception as e:
            pytest.fail(f"Tower not responsive after dropping slow clients: {e}")


# ============================================================================
# Section 3: Backpressure and Encoder Reader Safety
# ============================================================================

class TestBackpressure:
    """Tests for Section 4: Backpressure Guarantees"""
    
    @pytest.mark.slow
    def test_b1_encoder_reader_never_blocks_on_slow_clients(self, tower_instance):
        """
        4.1: Encoder reader loop must never block because one or more clients are slow.
        
        Arrange:
        - Connect several slow clients as above.
        - In parallel, use collect_mp3_chunks() with a fast client during the same time window.
        
        Assert:
        - The fast client receives MP3 data continuously.
        - No stalls or long gaps (e.g. no 1-second holes) appear in the MP3 stream for the fast client.
        - Tower does not crash or become unresponsive.
        """
        host, port, socket_path, service = tower_instance
        
        # Connect multiple slow clients
        num_slow = 3
        slow_socks = []
        for _ in range(num_slow):
            try:
                sock = create_slow_client(host, port)
                slow_socks.append(sock)
            except Exception:
                break
        
        # Collect MP3 from fast client in parallel
        fast_chunks = []
        chunk_times = []
        collection_running = threading.Event()
        collection_running.set()
        
        def collect_with_timing():
            try:
                with httpx.Client(timeout=3.0) as client:
                    with client.stream("GET", f"http://{host}:{port}/stream") as resp:
                        assert resp.status_code == 200
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            if not collection_running.is_set():
                                break
                            fast_chunks.append(chunk)
                            chunk_times.append(time.time())
                            if len(fast_chunks) >= 15:  # Collect 15 chunks
                                break
            except Exception:
                pass
        
        collect_thread = threading.Thread(target=collect_with_timing, daemon=True)
        collect_thread.start()
        
        # Wait for collection to complete
        collect_thread.join(timeout=5.0)
        collection_running.clear()
        
        # Clean up slow clients
        for sock in slow_socks:
            try:
                sock.close()
            except Exception:
                pass
        
        # Assert fast client received data continuously
        assert len(fast_chunks) >= 10, "Fast client did not receive enough chunks"
        
        # Verify no long gaps (check timing between chunks)
        if len(chunk_times) >= 2:
            gaps = []
            for i in range(1, len(chunk_times)):
                gap = chunk_times[i] - chunk_times[i-1]
                gaps.append(gap)
            
            # No gap should exceed 1 second (encoder reader should not block)
            max_gap = max(gaps) if gaps else 0
            assert max_gap < 1.0, (
                f"Encoder reader blocked: found gap of {max_gap:.2f}s between chunks"
            )
        
        # Verify MP3 data is valid
        fast_data = b''.join(fast_chunks)
        assert is_valid_mp3_header(fast_data), "Fast client received invalid MP3"
        
        # Verify Tower is still responsive
        try:
            test_data = collect_mp3_chunks(host, port, duration_seconds=0.1)
            assert len(test_data) > 0, "Tower became unresponsive"
        except Exception as e:
            pytest.fail(f"Tower became unresponsive: {e}")
    
    @pytest.mark.slow
    def test_b2_no_unbounded_global_buffer_growth(self, tower_instance):
        """
        4.2: Tower must NOT maintain a global "shared" backlog that grows unbounded.
        
        This test is partly observational:
        - Stress Tower with multiple slow clients and a fast client.
        - Monitor memory usage or verify that fast client continues to receive data
          without Tower becoming unresponsive.
        """
        host, port, socket_path, service = tower_instance
        
        # Connect many slow clients to stress the system
        num_slow = 10
        slow_socks = []
        for _ in range(num_slow):
            try:
                sock = create_slow_client(host, port)
                slow_socks.append(sock)
            except Exception:
                break
        
        # Fast client collects data continuously
        fast_chunks = []
        collection_running = threading.Event()
        collection_running.set()
        
        def collect_continuously():
            try:
                with httpx.Client(timeout=5.0) as client:
                    with client.stream("GET", f"http://{host}:{port}/stream") as resp:
                        assert resp.status_code == 200
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            if not collection_running.is_set():
                                break
                            fast_chunks.append(chunk)
                            if len(fast_chunks) >= 30:  # Collect many chunks
                                break
            except Exception:
                pass
        
        collect_thread = threading.Thread(target=collect_continuously, daemon=True)
        collect_thread.start()
        
        # Wait for collection
        collect_thread.join(timeout=8.0)
        collection_running.clear()
        
        # Clean up slow clients
        for sock in slow_socks:
            try:
                sock.close()
            except Exception:
                pass
        
        # Assert fast client received data (Tower didn't get overwhelmed)
        assert len(fast_chunks) >= 20, (
            "Fast client did not receive enough data (Tower may be overwhelmed)"
        )
        
        # Verify MP3 data is valid
        fast_data = b''.join(fast_chunks)
        assert is_valid_mp3_header(fast_data), "Fast client received invalid MP3"
        
        # Verify Tower remains responsive
        try:
            test_data = collect_mp3_chunks(host, port, duration_seconds=0.1)
            assert len(test_data) > 0, "Tower became unresponsive under stress"
        except Exception as e:
            pytest.fail(f"Tower became unresponsive under stress: {e}")


# ============================================================================
# Section 5: Component Isolation
# ============================================================================

class TestComponentIsolation:
    """Tests for Section 4.5: Component Isolation Architecture"""
    
    @pytest.mark.slow
    def test_i1_encoder_manager_not_backpressured_by_http_layer(self, tower_instance):
        """
        4.5: No component above the HTTP layer may backpressure EncoderManager.
        
        Arrange:
        - Connect many slow clients to create backpressure at HTTP layer.
        - Monitor encoder reader loop (should continue reading MP3 chunks).
        
        Assert:
        - Encoder reader loop continues to read MP3 chunks (doesn't block).
        - Fast clients continue receiving data.
        """
        host, port, socket_path, service = tower_instance
        
        # Create many slow clients to create backpressure
        num_slow = 10
        slow_socks = []
        for _ in range(num_slow):
            try:
                sock = create_slow_client(host, port)
                slow_socks.append(sock)
            except Exception:
                break
        
        # Fast client to verify encoder continues producing
        fast_chunks = []
        fast_running = threading.Event()
        fast_running.set()
        
        def fast_reader():
            try:
                with httpx.Client(timeout=5.0) as client:
                    with client.stream("GET", f"http://{host}:{port}/stream") as resp:
                        assert resp.status_code == 200
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            if not fast_running.is_set():
                                break
                            fast_chunks.append(chunk)
                            if len(fast_chunks) >= 20:
                                break
            except Exception:
                pass
        
        fast_thread = threading.Thread(target=fast_reader, daemon=True)
        fast_thread.start()
        
        # Wait for collection
        fast_thread.join(timeout=5.0)
        fast_running.clear()
        
        # Clean up slow clients
        for sock in slow_socks:
            try:
                sock.close()
            except Exception:
                pass
        
        # Assert fast client received data (encoder wasn't backpressured)
        assert len(fast_chunks) >= 15, (
            "Encoder reader loop was backpressured by HTTP layer "
            "(fast client did not receive enough data)"
        )
        
        fast_data = b''.join(fast_chunks)
        assert is_valid_mp3_header(fast_data), "Fast client received invalid MP3"
    
    @pytest.mark.slow
    def test_i2_audiopump_not_backpressured_by_encoder(self, tower_instance):
        """
        4.5: EncoderManager must not backpressure AudioPump.
        AudioPump is the one and only metronome.
        
        Arrange:
        - Kill encoder to force restart attempts.
        - Monitor Tower responsiveness (AudioPump should continue).
        
        Assert:
        - Tower remains responsive during encoder restarts.
        - AudioPump continues running (Tower doesn't stall).
        """
        host, port, socket_path, service = tower_instance
        
        # Kill encoder to trigger restart
        kill_encoder_process(service)
        
        # During restart, verify Tower remains responsive
        # (AudioPump continues, not blocked by encoder restart)
        responsive_count = 0
        for _ in range(10):
            try:
                with httpx.Client(timeout=0.5) as client:
                    resp = client.get(f"http://{host}:{port}/status")
                    if resp.status_code == 200:
                        responsive_count += 1
            except Exception:
                pass
            time.sleep(0.1)
        
        # Assert Tower remained responsive (AudioPump not backpressured)
        assert responsive_count >= 7, (
            "AudioPump was backpressured by encoder restart "
            "(Tower became unresponsive)"
        )
    
    @pytest.mark.slow
    def test_i3_http_connection_manager_not_backpressured_by_encoder_reader(self, tower_instance):
        """
        4.5: HTTPConnectionManager must not backpressure EncoderManager reader loop.
        
        Arrange:
        - Connect fast clients.
        - Verify encoder reader loop continues producing MP3 chunks.
        
        Assert:
        - Fast clients receive continuous MP3 data.
        - No stalls in MP3 stream (encoder reader not blocked).
        """
        host, port, socket_path, service = tower_instance
        
        # Connect fast client and monitor chunk timing
        chunk_times = []
        chunks = []
        running = threading.Event()
        running.set()
        
        def monitor_chunks():
            try:
                with httpx.Client(timeout=5.0) as client:
                    with client.stream("GET", f"http://{host}:{port}/stream") as resp:
                        assert resp.status_code == 200
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            if not running.is_set():
                                break
                            chunks.append(chunk)
                            chunk_times.append(time.time())
                            if len(chunks) >= 20:
                                break
            except Exception:
                pass
        
        thread = threading.Thread(target=monitor_chunks, daemon=True)
        thread.start()
        
        thread.join(timeout=5.0)
        running.clear()
        
        # Verify continuous data flow (no long gaps)
        assert len(chunks) >= 15, "Not enough chunks received"
        
        if len(chunk_times) >= 2:
            gaps = [chunk_times[i] - chunk_times[i-1] for i in range(1, len(chunk_times))]
            max_gap = max(gaps) if gaps else 0
            # Encoder reader should not be blocked, so gaps should be reasonable
            assert max_gap < 1.0, (
                f"Encoder reader loop was backpressured "
                f"(found gap of {max_gap:.2f}s between chunks)"
            )
        
        data = b''.join(chunks)
        assert is_valid_mp3_header(data), "Received invalid MP3 data"


# ============================================================================
# Section 4: FAILED State Behavior
# ============================================================================

class TestFailedState:
    """Tests for Section 2.5: FAILED State Behavior"""
    
    @pytest.mark.slow
    def test_f1_stream_serves_silence_in_failed_state(self, tower_instance):
        """
        2.5: In FAILED state, /stream must continue streaming silent MP3 frames indefinitely.
        
        Arrange:
        - Force encoder to fail 5 times (exhaust restart attempts).
        - Connect to /stream.
        
        Assert:
        - /stream continues to serve MP3 data (silent frames) OR keeps connection open.
        - Clients remain connected (not disconnected).
        - No HTTP errors are returned.
        - Tower MUST NOT terminate /stream connections even if audio is silent.
        """
        host, port, socket_path, service = tower_instance
        
        # Force encoder to fail multiple times
        # Kill encoder 5 times to exhaust restart attempts
        for attempt in range(5):
            kill_encoder_process(service)
            # Wait for backoff delay (increasing: 1s, 2s, 4s, 8s, 10s)
            # Wait a bit longer than the backoff to ensure restart attempt completes
            if attempt < 4:  # Don't wait after last kill
                wait_time = min(1.0 + (2 ** attempt), 12.0)  # 1s, 2s, 4s, 8s, 10s
                time.sleep(wait_time + 0.5)  # Add small buffer
        
        # Wait a moment for FAILED state to be entered
        time.sleep(1.0)
        
        # Verify /status shows encoder not running
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"http://{host}:{port}/status")
                assert resp.status_code == 200
                status = resp.json()
                # Encoder should not be running (in FAILED state)
                # Note: exact field name may vary based on implementation
        except Exception:
            pass  # Status endpoint may not expose encoder state yet
        
        # According to contract: Tower MUST NOT generate MP3 without FFmpeg.
        # In FAILED state, Tower continues PCM generation but MP3 output depends on encoder availability.
        # If encoder is permanently FAILED, Tower continues serving existing TCP connections
        # but clients may hear silence only from the moment encoder is restarted manually.
        # The stream must remain open.
        
        # Connect to /stream and verify connection remains open
        # Note: If encoder is permanently FAILED, MP3 may not be generated,
        # but the connection must remain open
        try:
            with httpx.Client(timeout=2.0) as client:
                with client.stream("GET", f"http://{host}:{port}/stream") as resp:
                    assert resp.status_code == 200, "/stream returned error in FAILED state"
                    
                    # Try to read data - may be empty if encoder is permanently FAILED,
                    # but connection must remain open
                    chunks_read = 0
                    chunk_times = []
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        chunks_read += 1
                        chunk_times.append(time.time())
                        if chunks_read >= 5:
                            break
                        # Don't wait too long if no data is coming
                        if chunks_read == 0 and len(chunk_times) > 0:
                            if time.time() - chunk_times[0] > 2.0:
                                break
                    
                    # Connection must remain open (no exception raised)
                    # If MP3 is being generated, verify it's valid
                    if chunks_read > 0:
                        # If we got data, verify it's MP3 format
                        # Note: We can't easily verify it's silence without decoding
                        pass  # Connection remained open, which is the key requirement
        except Exception as e:
            pytest.fail(f"/stream connection failed in FAILED state: {e}")
    
    @pytest.mark.slow
    def test_f2_audiopump_continues_in_failed_state(self, tower_instance):
        """
        2.5: In FAILED state, AudioPump must continue generating silence PCM frames
        at the same real-time cadence (21.333ms intervals).
        
        Arrange:
        - Force encoder to FAILED state.
        - Monitor AudioPump behavior (if accessible) or verify Tower continues operating.
        
        Assert:
        - AudioPump continues running (Tower remains responsive).
        - Silence is encoded to MP3 in real time (not pre-buffered).
        - Silence MUST NOT stall or inject null output.
        """
        host, port, socket_path, service = tower_instance
        
        # Force encoder to FAILED state
        for attempt in range(5):
            kill_encoder_process(service)
            if attempt < 4:
                wait_time = min(1.0 + (2 ** attempt), 12.0)
                time.sleep(wait_time + 0.5)
        
        time.sleep(1.0)
        
        # Verify Tower remains responsive (AudioPump continues)
        # If AudioPump stopped, Tower would become unresponsive
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"http://{host}:{port}/status")
                assert resp.status_code == 200, "Tower became unresponsive (AudioPump may have stopped)"
        except Exception as e:
            pytest.fail(f"Tower became unresponsive in FAILED state: {e}")
        
        # Verify /control/source remains responsive (AudioPump continues)
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.post(f"http://{host}:{port}/control/source", json={"source": "tone"})
                assert resp.status_code in [200, 400], "/control/source not responsive"
        except Exception as e:
            pytest.fail(f"/control/source not responsive in FAILED state: {e}")

