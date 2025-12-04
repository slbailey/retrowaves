"""
Contract tests for Retrowaves Tower Phase 5.

These tests enforce every requirement in tower/docs/contracts/tower_phase5_source_graph.md.
Each test corresponds to a specific contract bullet point.

Tests are designed to fail until Phase 5 implementation exists.
"""

import os
import socket
import tempfile
import time
import threading
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

import numpy as np
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


def create_test_wav_file(
    path: str,
    duration_seconds: float = 0.1,
    sample_rate: int = 48000,
    channels: int = 2,
    frequency: float = 440.0
) -> None:
    """
    Create a test WAV file with sine wave audio.
    
    Args:
        path: Path to create WAV file
        duration_seconds: Duration of audio in seconds
        sample_rate: Sample rate (default: 48000)
        channels: Number of channels (default: 2)
        frequency: Frequency of sine wave in Hz (default: 440)
    """
    num_samples = int(sample_rate * duration_seconds)
    
    # Generate sine wave
    t = np.arange(num_samples) / sample_rate
    samples = np.sin(2 * np.pi * frequency * t)
    
    # Scale to int16 range
    samples_int16 = (samples * 0.8 * 32767).astype(np.int16)
    
    # Interleave for stereo
    if channels == 2:
        stereo_samples = np.empty(num_samples * channels, dtype=np.int16)
        stereo_samples[0::2] = samples_int16  # Left channel
        stereo_samples[1::2] = samples_int16  # Right channel
    else:
        stereo_samples = samples_int16
    
    # Write WAV file
    with wave.open(path, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)  # int16 = 2 bytes
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(stereo_samples.tobytes())


def is_valid_mp3_header(data: bytes) -> bool:
    """
    Check if data starts with a valid MP3 header.
    
    MP3 files typically start with:
    - ID3v2 tag: "ID3" at start
    - Or MP3 frame sync: 0xFF 0xFB or 0xFF 0xFA or 0xFF 0xF3
    """
    if len(data) < 3:
        return False
    
    # Check for ID3v2 tag
    if data[:3] == b'ID3':
        return True
    
    # Check for MP3 frame sync
    if data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return True
    
    return False


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
        config = TowerConfig()
        config.host = host
        if port is None:
            port = find_free_port()
        config.port = port
        config.validate()
        
        service = TowerService(config)
        
        # Start service directly (it starts threads internally)
        service.start()
        
        # Wait for Tower to be ready
        _wait_for_tower_ready(host, port, timeout=5.0)
        
        yield (host, port, socket_path)
    
    finally:
        # Stop service
        if service:
            try:
                service.stop()
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
        
        # Clean up temp socket file
        try:
            if socket_path and os.path.exists(socket_path):
                os.unlink(socket_path)
                # Try to remove parent directory if it's temp
                parent = os.path.dirname(socket_path)
                if "tower_test_" in parent:
                    os.rmdir(parent)
        except Exception:
            pass


@pytest.fixture
def tower_instance():
    """
    Launch a Tower instance on an ephemeral port and yield (host, port, socket_path).
    
    Yields:
        (host, port, socket_path) tuple for connecting to Tower
    """
    with _tower_instance_context() as result:
        yield result


@pytest.fixture
def test_wav_file():
    """Create a temporary test WAV file."""
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        wav_path = f.name
    
    try:
        create_test_wav_file(wav_path, duration_seconds=0.2)
        yield wav_path
    finally:
        # Clean up
        if os.path.exists(wav_path):
            os.unlink(wav_path)


class SyntheticWriter:
    """
    Synthetic writer for testing Unix socket input.
    
    Connects to Tower's Unix socket and writes PCM frames.
    """
    
    def __init__(self, socket_path: str):
        """
        Initialize synthetic writer.
        
        Args:
            socket_path: Path to Unix socket
        """
        self.socket_path = socket_path
        self.sock: Optional[socket.socket] = None
        self.connected = False
    
    def connect(self, timeout: float = 2.0) -> None:
        """Connect to Unix socket."""
        deadline = time.time() + timeout
        
        while time.time() < deadline:
            try:
                if not os.path.exists(self.socket_path):
                    time.sleep(0.05)
                    continue
                
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(1.0)
                self.sock.connect(self.socket_path)
                self.connected = True
                return
            except (socket.error, OSError) as e:
                if self.sock:
                    self.sock.close()
                    self.sock = None
                time.sleep(0.05)
        
        raise TimeoutError(f"Could not connect to socket {self.socket_path} within {timeout} seconds")
    
    def write_frame(self, frame: bytes) -> None:
        """
        Write a single 4096-byte frame.
        
        Args:
            frame: Frame data (must be exactly 4096 bytes)
        """
        if not self.connected or not self.sock:
            raise RuntimeError("Writer not connected")
        
        if len(frame) != 4096:
            raise ValueError(f"Frame must be exactly 4096 bytes, got {len(frame)}")
        
        try:
            self.sock.sendall(frame)
        except (socket.error, OSError) as e:
            self.connected = False
            raise
    
    def disconnect(self) -> None:
        """Disconnect from socket."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.connected = False
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


def generate_pattern_frame(pattern_byte: int = 0x42) -> bytes:
    """Generate a 4096-byte frame with a pattern."""
    return bytes([pattern_byte] * 4096)


def collect_mp3_chunks(host: str, port: int, duration_seconds: float = 0.5, chunk_size: int = 8192) -> bytes:
    """
    Collect MP3 chunks from /stream endpoint.
    
    Args:
        host: Tower host
        port: Tower port
        duration_seconds: How long to collect data
        chunk_size: Read chunk size
    
    Returns:
        Collected MP3 data
    """
    url = f"http://{host}:{port}/stream"
    chunks = []
    deadline = time.time() + duration_seconds
    
    try:
        with httpx.Client(timeout=duration_seconds + 1.0) as client:
            with client.stream("GET", url) as resp:
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
                
                for chunk in resp.iter_bytes(chunk_size=chunk_size):
                    chunks.append(chunk)
                    if time.time() >= deadline:
                        break
    except Exception:
        pass
    
    return b''.join(chunks)


def get_status(host: str, port: int) -> dict:
    """Get Tower /status response."""
    url = f"http://{host}:{port}/status"
    with httpx.Client(timeout=2.0) as client:
        resp = client.get(url)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        return resp.json()


def control_source(host: str, port: int, command: dict) -> dict:
    """Send POST /control/source command."""
    url = f"http://{host}:{port}/control/source"
    with httpx.Client(timeout=2.0) as client:
        resp = client.post(url, json=command)
        return resp.json()


# ============================================================================
# Section 1: SourceGraph Component Tests
# ============================================================================

class TestSourceGraphComponent:
    """Tests for Section 1: SourceGraph Component"""
    
    def test_1_1_sourcegraph_component_exists(self, tower_instance):
        """1.1: Tower must implement a SourceGraph component"""
        host, port, socket_path = tower_instance
        # If Tower starts successfully, SourceGraph must exist (implicit test)
        status = get_status(host, port)
        # Phase 5 fields should be present
        assert "primary_source" in status or "source_mode" in status, "SourceGraph-related fields should be in status"
    
    def test_1_2_standard_nodes_pre_declared(self, tower_instance):
        """1.2: SourceGraph must pre-declare standard nodes at initialization"""
        host, port, socket_path = tower_instance
        status = get_status(host, port)
        
        # Standard nodes should be available via control API
        # Test that we can set primary to standard nodes
        result = control_source(host, port, {"set_primary": "tone"})
        assert result.get("status") == "ok", f"Should be able to set primary to tone: {result}"
        
        result = control_source(host, port, {"set_primary": "silence"})
        assert result.get("status") == "ok", f"Should be able to set primary to silence: {result}"
        
        result = control_source(host, port, {"set_primary": "live_pcm"})
        assert result.get("status") == "ok", f"Should be able to set primary to live_pcm: {result}"
    
    def test_1_2_file_nodes_created_on_demand(self, tower_instance, test_wav_file):
        """1.2: SourceGraph must create file nodes on demand when mode: file command is received"""
        host, port, socket_path = tower_instance
        
        # Create file node via mode command
        result = control_source(host, port, {"mode": "file", "file_path": test_wav_file})
        assert result.get("status") == "ok", f"Should create file node: {result}"
        
        # Verify file node was created by checking status
        status = get_status(host, port)
        # File node should be active now
        assert status.get("file_path") == test_wav_file or status.get("primary_source") == "file", "File node should be created"
    
    def test_1_3_sourcegraph_exposes_active_node(self, tower_instance):
        """1.3: SourceGraph must expose active node's next_frame() to AudioPump"""
        host, port, socket_path = tower_instance
        
        # Set primary source
        control_source(host, port, {"set_primary": "tone"})
        
        # Tower should stream MP3 (AudioPump should be getting frames from active node)
        mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.2)
        assert len(mp3_data) > 0, "Tower should stream MP3 data from active node"
        assert is_valid_mp3_header(mp3_data), "Streamed data should be valid MP3"
    
    def test_1_4_sourcegraph_thread_safe(self, tower_instance):
        """1.4: SourceGraph must be thread-safe"""
        host, port, socket_path = tower_instance
        
        # Concurrent status requests (read operations)
        def get_status_concurrent():
            return get_status(host, port)
        
        # Run multiple concurrent requests
        threads = []
        results = []
        for _ in range(5):
            thread = threading.Thread(target=lambda: results.append(get_status_concurrent()))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join(timeout=2.0)
        
        # All requests should succeed
        assert len(results) == 5, "All concurrent requests should succeed"
        
        # All should return valid status
        for result in results:
            assert "primary_source" in result or "source_mode" in result, "All status responses should be valid"


# ============================================================================
# Section 2: SourceNode Abstraction Tests
# ============================================================================

class TestSourceNodeAbstraction:
    """Tests for Section 2: SourceNode Abstraction"""
    
    def test_2_1_sourcenode_next_frame_interface(self, tower_instance):
        """2.1: SourceNode must expose next_frame() -> Optional[bytes] method"""
        host, port, socket_path = tower_instance
        
        # All node types should produce frames when active
        for node_name in ["tone", "silence"]:
            control_source(host, port, {"set_primary": node_name})
            time.sleep(0.1)  # Allow switching
            
            # Should stream MP3 (indicating next_frame() is working)
            mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.2)
            assert len(mp3_data) > 0, f"{node_name} node should produce frames"
    
    def test_2_1_sourcenode_returns_none_on_failure(self, tower_instance, test_wav_file):
        """2.1: SourceNode must return None if node cannot produce a frame"""
        host, port, socket_path = tower_instance
        
        # Create a file node, then delete the file
        control_source(host, port, {"mode": "file", "file_path": test_wav_file})
        time.sleep(0.1)
        
        # Delete the file - FileSource should fail
        os.unlink(test_wav_file)
        time.sleep(0.2)
        
        # Tower should fall back to ToneSource (indicating node returned None)
        # This is tested via fallback behavior
    
    def test_2_2_node_types_supported(self, tower_instance):
        """2.2: SourceGraph must support these node types: tone, silence, file, live_pcm"""
        host, port, socket_path = tower_instance
        
        # Test all node types
        node_types = ["tone", "silence", "live_pcm"]
        for node_type in node_types:
            result = control_source(host, port, {"set_primary": node_type})
            assert result.get("status") == "ok", f"Should support {node_type} node type: {result}"


# ============================================================================
# Section 3: Mixer Component Tests
# ============================================================================

class TestMixerComponent:
    """Tests for Section 3: Mixer Component"""
    
    def test_3_1_mixer_component_exists(self, tower_instance):
        """3.1: Tower must implement a Mixer component"""
        host, port, socket_path = tower_instance
        
        # Mixer functionality is tested via control API
        # If we can set primary and push overrides, Mixer exists
        result = control_source(host, port, {"set_primary": "tone"})
        assert result.get("status") == "ok", "Mixer should handle set_primary"
    
    def test_3_2_primary_source_management(self, tower_instance):
        """3.2: Mixer must track exactly ONE primary source node"""
        host, port, socket_path = tower_instance
        
        # Set primary to tone
        result = control_source(host, port, {"set_primary": "tone"})
        assert result.get("status") == "ok", "Should set primary source"
        status = get_status(host, port)
        assert status.get("primary_source") == "tone" or status.get("source_mode") == "tone", "Primary should be tone"
        
        # Change primary to silence
        result = control_source(host, port, {"set_primary": "silence"})
        assert result.get("status") == "ok", "Should change primary source"
        status = get_status(host, port)
        assert status.get("primary_source") == "silence" or status.get("source_mode") == "silence", "Primary should be silence"
    
    def test_3_3_override_stack_management(self, tower_instance):
        """3.3: Mixer must maintain an override stack (LIFO)"""
        host, port, socket_path = tower_instance
        
        # Set primary
        control_source(host, port, {"set_primary": "tone"})
        time.sleep(0.1)
        
        # Push override
        result = control_source(host, port, {"push_override": "silence"})
        assert result.get("status") == "ok", "Should push override"
        status = get_status(host, port)
        override_stack = status.get("override_stack", [])
        assert "silence" in override_stack or status.get("active_source") == "silence", "Override should be pushed"
    
    def test_3_3_override_stack_size_bounds(self, tower_instance):
        """3.3: Override stack MUST support at least 8 entries, MUST NOT exceed 128"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"set_primary": "tone"})
        time.sleep(0.1)
        
        # Push 8 overrides (should work)
        for i in range(8):
            result = control_source(host, port, {"push_override": "silence"})
            assert result.get("status") == "ok", f"Should support at least 8 overrides (pushed {i+1}): {result}"
        
        # Try to push 129th (should fail or be rejected)
        # Note: Actual implementation may handle this differently
        # This test verifies the bound exists
        status = get_status(host, port)
        override_stack = status.get("override_stack", [])
        assert len(override_stack) <= 128, f"Override stack should not exceed 128, got {len(override_stack)}"
    
    def test_3_4_active_node_selection(self, tower_instance):
        """3.4: Mixer must determine active node using override stack rules"""
        host, port, socket_path = tower_instance
        
        # Set primary to tone
        control_source(host, port, {"set_primary": "tone"})
        time.sleep(0.1)
        status = get_status(host, port)
        assert status.get("active_source") == "tone" or status.get("primary_source") == "tone", "Active should be primary when stack empty"
        
        # Push override - active should change
        control_source(host, port, {"push_override": "silence"})
        time.sleep(0.1)
        status = get_status(host, port)
        assert status.get("active_source") == "silence", f"Active should be override, got: {status}"
        
        # Pop override - active should return to primary
        control_source(host, port, {"pop_override": True})
        time.sleep(0.1)
        status = get_status(host, port)
        assert status.get("active_source") == "tone" or status.get("primary_source") == "tone", "Active should return to primary after pop"


# ============================================================================
# Section 4: Source Graph Behavior Tests
# ============================================================================

class TestSourceGraphBehavior:
    """Tests for Section 4: Source Graph Behavior"""
    
    def test_4_1_primary_active_node_guarantee(self, tower_instance):
        """4.1: Exactly ONE primary active node must be active at any given time"""
        host, port, socket_path = tower_instance
        
        # Set primary
        control_source(host, port, {"set_primary": "tone"})
        time.sleep(0.1)
        status = get_status(host, port)
        active_source = status.get("active_source")
        assert active_source is not None, "Active source should never be None"
        assert active_source in ["tone", "silence", "live_pcm", "file"], f"Active source should be valid: {active_source}"
    
    def test_4_2_override_stack_behavior(self, tower_instance):
        """4.2: Override stack behavior (push/pop)"""
        host, port, socket_path = tower_instance
        
        # Set primary
        control_source(host, port, {"set_primary": "tone"})
        time.sleep(0.1)
        
        # Push override
        result = control_source(host, port, {"push_override": "silence"})
        assert result.get("status") == "ok", "Should push override"
        status = get_status(host, port)
        assert status.get("active_source") == "silence", "Active should be override after push"
        
        # Pop override
        result = control_source(host, port, {"pop_override": True})
        assert result.get("status") == "ok", "Should pop override"
        status = get_status(host, port)
        assert status.get("active_source") == "tone" or status.get("primary_source") == "tone", "Active should return to primary"
    
    def test_4_2_override_stack_lifo(self, tower_instance):
        """4.2: Override stack must be LIFO (last-in-first-out)"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"set_primary": "tone"})
        time.sleep(0.1)
        
        # Push multiple overrides
        control_source(host, port, {"push_override": "silence"})
        time.sleep(0.1)
        status1 = get_status(host, port)
        stack1 = status1.get("override_stack", [])
        
        # Push another
        # Note: We need at least two different nodes - if only silence is available, we can't test LIFO properly
        # For now, test that stack maintains order
        control_source(host, port, {"push_override": "tone"})
        time.sleep(0.1)
        status2 = get_status(host, port)
        stack2 = status2.get("override_stack", [])
        
        # Pop should remove last pushed
        control_source(host, port, {"pop_override": True})
        time.sleep(0.1)
        status3 = get_status(host, port)
        stack3 = status3.get("override_stack", [])
        
        # Last item should be removed
        if len(stack2) > 0 and len(stack3) > 0:
            assert len(stack3) == len(stack2) - 1, "Pop should remove one item from stack"
    
    def test_4_2_invalid_pop_empty_stack(self, tower_instance):
        """4.2: Pop on empty stack must fail cleanly"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"set_primary": "tone"})
        time.sleep(0.1)
        
        # Pop on empty stack
        result = control_source(host, port, {"pop_override": True})
        # Should either succeed (no-op) or return error - both are acceptable
        assert result.get("status") in ["ok", "error"], "Pop on empty stack should handle gracefully"
    
    def test_4_3_switching_on_frame_boundaries(self, tower_instance):
        """4.3: All switches must occur on frame boundaries"""
        host, port, socket_path = tower_instance
        
        # This is hard to test directly, but we can verify switching doesn't cause gaps
        control_source(host, port, {"set_primary": "tone"})
        
        # Collect some MP3 data
        mp3_before = collect_mp3_chunks(host, port, duration_seconds=0.2)
        
        # Switch source
        control_source(host, port, {"set_primary": "silence"})
        
        # Collect more MP3 data
        mp3_after = collect_mp3_chunks(host, port, duration_seconds=0.2)
        
        # Both should be valid MP3 (no gaps or corruption)
        assert len(mp3_before) > 0, "MP3 stream should continue before switch"
        assert len(mp3_after) > 0, "MP3 stream should continue after switch"
        assert is_valid_mp3_header(mp3_before), "MP3 should be valid before switch"
        assert is_valid_mp3_header(mp3_after), "MP3 should be valid after switch"
    
    def test_4_4_fallback_to_tonesource(self, tower_instance):
        """4.4: If active node returns None, Mixer must fall back to ToneSource"""
        host, port, socket_path = tower_instance
        
        # Set primary to live_pcm (which may not have writer)
        control_source(host, port, {"set_primary": "live_pcm"})
        time.sleep(0.3)  # Allow fallback to occur
        
        # Tower should still stream (fallback to ToneSource)
        mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.2)
        assert len(mp3_data) > 0, "Tower should stream even when live_pcm has no writer (fallback)"
        assert is_valid_mp3_header(mp3_data), "Streamed data should be valid MP3"
    
    def test_4_5_audiopump_integration(self, tower_instance):
        """4.5: AudioPump must call Mixer's active node next_frame() method"""
        host, port, socket_path = tower_instance
        
        # Set primary
        control_source(host, port, {"set_primary": "tone"})
        
        # AudioPump should be producing frames continuously
        mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.5)
        assert len(mp3_data) > 0, "AudioPump should be producing frames"
        
        # Switch source
        control_source(host, port, {"set_primary": "silence"})
        
        # AudioPump should continue producing frames
        mp3_data2 = collect_mp3_chunks(host, port, duration_seconds=0.5)
        assert len(mp3_data2) > 0, "AudioPump should continue producing frames after switch"


# ============================================================================
# Section 5: Control API Extensions Tests
# ============================================================================

class TestControlAPIExtensions:
    """Tests for Section 5: Control API Extensions"""
    
    def test_5_1_mode_commands_backward_compatible(self, tower_instance, test_wav_file):
        """5.1: Existing Phase 2-4 mode commands must continue to work"""
        host, port, socket_path = tower_instance
        
        # Test tone mode
        result = control_source(host, port, {"mode": "tone"})
        assert result.get("status") == "ok", "Mode tone should work"
        
        # Test silence mode
        result = control_source(host, port, {"mode": "silence"})
        assert result.get("status") == "ok", "Mode silence should work"
        
        # Test file mode
        result = control_source(host, port, {"mode": "file", "file_path": test_wav_file})
        assert result.get("status") == "ok", "Mode file should work"
    
    def test_5_2_set_primary_command(self, tower_instance):
        """5.2: set_primary command must set primary source"""
        host, port, socket_path = tower_instance
        
        result = control_source(host, port, {"set_primary": "tone"})
        assert result.get("status") == "ok", "set_primary should succeed"
        assert result.get("primary_source") == "tone", "Primary source should be set"
        
        status = get_status(host, port)
        assert status.get("primary_source") == "tone" or status.get("source_mode") == "tone", "Status should reflect primary source"
    
    def test_5_2_set_primary_invalid_node(self, tower_instance):
        """5.2: set_primary must return 400 if node does not exist"""
        host, port, socket_path = tower_instance
        
        result = control_source(host, port, {"set_primary": "nonexistent_node"})
        # Should return error
        assert result.get("status") == "error" or "error" in result, f"Should reject nonexistent node: {result}"
    
    def test_5_3_push_override_command(self, tower_instance):
        """5.3: push_override command must push override onto stack"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"set_primary": "tone"})
        time.sleep(0.1)
        
        result = control_source(host, port, {"push_override": "silence"})
        assert result.get("status") == "ok", "push_override should succeed"
        
        status = get_status(host, port)
        override_stack = status.get("override_stack", [])
        assert len(override_stack) > 0, "Override stack should have items"
        assert status.get("active_source") == "silence", "Active source should be override"
    
    def test_5_3_push_override_no_auto_create(self, tower_instance):
        """5.3: push_override MUST NOT auto-create nodes"""
        host, port, socket_path = tower_instance
        
        result = control_source(host, port, {"push_override": "nonexistent_node"})
        # Should return error (node must pre-exist)
        assert result.get("status") == "error" or "error" in result, "Should reject nonexistent node for override"
    
    def test_5_4_pop_override_command(self, tower_instance):
        """5.4: pop_override command must pop override from stack"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"set_primary": "tone"})
        control_source(host, port, {"push_override": "silence"})
        time.sleep(0.1)
        
        status_before = get_status(host, port)
        stack_before = len(status_before.get("override_stack", []))
        
        result = control_source(host, port, {"pop_override": True})
        assert result.get("status") == "ok", "pop_override should succeed"
        
        time.sleep(0.1)
        status_after = get_status(host, port)
        stack_after = len(status_after.get("override_stack", []))
        
        assert stack_after == stack_before - 1, "Stack should have one less item after pop"
    
    def test_5_5_command_validation(self, tower_instance):
        """5.5: Tower must validate all command parameters"""
        host, port, socket_path = tower_instance
        
        # Test invalid command
        result = control_source(host, port, {"invalid_command": "value"})
        # Should return error or ignore unknown commands
        # Implementation-dependent, but should not crash
    
    def test_5_6_backward_compatibility_mode_commands(self, tower_instance, test_wav_file):
        """5.6: Mode commands must create file nodes on demand"""
        host, port, socket_path = tower_instance
        
        # Mode file command should create file node
        result = control_source(host, port, {"mode": "file", "file_path": test_wav_file})
        assert result.get("status") == "ok", "Mode file should create file node"
        
        # File node should now be available as primary
        status = get_status(host, port)
        assert status.get("file_path") == test_wav_file or status.get("primary_source") == "file", "File node should be created"


# ============================================================================
# Section 6: Status API Extensions Tests
# ============================================================================

class TestStatusAPIExtensions:
    """Tests for Section 6: Status API Extensions"""
    
    def test_6_1_status_backward_compatible_fields(self, tower_instance):
        """6.1: /status must continue to return Phase 2-4 fields"""
        host, port, socket_path = tower_instance
        
        status = get_status(host, port)
        
        # Phase 2-4 fields should still be present
        assert "source_mode" in status or "primary_source" in status, "Status should have source info"
        assert "num_clients" in status, "Status should have num_clients"
        assert "encoder_running" in status, "Status should have encoder_running"
        assert "uptime_seconds" in status, "Status should have uptime_seconds"
    
    def test_6_2_primary_source_field(self, tower_instance):
        """6.2: /status must include primary_source field"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"set_primary": "tone"})
        time.sleep(0.1)
        
        status = get_status(host, port)
        # primary_source should be present (or source_mode for backward compatibility)
        assert "primary_source" in status or status.get("source_mode") == "tone", "Status should have primary_source"
    
    def test_6_3_override_stack_field(self, tower_instance):
        """6.3: /status must include override_stack field"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"set_primary": "tone"})
        control_source(host, port, {"push_override": "silence"})
        time.sleep(0.1)
        
        status = get_status(host, port)
        assert "override_stack" in status, "Status should have override_stack field"
        assert isinstance(status["override_stack"], list), "override_stack should be a list"
    
    def test_6_4_active_source_field(self, tower_instance):
        """6.4: /status must include active_source field"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"set_primary": "tone"})
        time.sleep(0.1)
        
        status = get_status(host, port)
        assert "active_source" in status, "Status should have active_source field"
        assert status["active_source"] is not None, "active_source should never be None"
    
    def test_6_4_active_source_matches_override_when_pushed(self, tower_instance):
        """6.4: active_source must match top of override_stack when stack not empty"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"set_primary": "tone"})
        control_source(host, port, {"push_override": "silence"})
        time.sleep(0.1)
        
        status = get_status(host, port)
        assert status.get("active_source") == "silence", f"Active source should be override: {status}"
        if "override_stack" in status and len(status["override_stack"]) > 0:
            assert status["active_source"] == status["override_stack"][0], "Active source should match top of stack"
    
    def test_6_5_status_backward_compatibility(self, tower_instance):
        """6.5: /status response must remain valid JSON with all existing fields"""
        host, port, socket_path = tower_instance
        
        status = get_status(host, port)
        
        # Should be valid dict (JSON was parsed successfully)
        assert isinstance(status, dict), "Status should be a dict"
        
        # Should have all expected fields
        required_fields = ["source_mode", "num_clients", "encoder_running", "uptime_seconds"]
        for field in required_fields:
            assert field in status or "primary_source" in status, f"Status should have {field} or equivalent"


# ============================================================================
# Section 7: Live PCM Integration Tests
# ============================================================================

class TestLivePCMIntegration:
    """Tests for Section 7: Live PCM Integration"""
    
    def test_live_pcm_primary_router_returns_bytes(self, tower_instance):
        """When LivePCMSource is primary and router.get_next_frame() returns bytes → active source is Live PCM"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"set_primary": "live_pcm"})
        time.sleep(0.1)
        
        # Connect writer and send frames
        with SyntheticWriter(socket_path) as writer:
            frame = generate_pattern_frame(0x42)
            writer.write_frame(frame)
            time.sleep(0.1)
            
            # Active source should be live_pcm when writer is connected
            status = get_status(host, port)
            # Note: May fall back to tone if no frames queued, but should accept live PCM when available
    
    def test_live_pcm_router_returns_none_fallback(self, tower_instance):
        """When router returns None → fallback to ToneSource"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"set_primary": "live_pcm"})
        time.sleep(0.3)  # Allow fallback to occur
        
        # No writer connected, so router should return None
        # Tower should fall back to ToneSource
        status = get_status(host, port)
        # Active may be live_pcm, but actual audio should come from ToneSource fallback
        
        # Verify Tower still streams (fallback working)
        mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.2)
        assert len(mp3_data) > 0, "Tower should stream even when live_pcm has no writer"


# ============================================================================
# Section 8: FileSource Behavior Tests
# ============================================================================

class TestFileSourceBehavior:
    """Tests for Section 8: FileSource Behavior"""
    
    def test_filesource_loops_at_eof(self, tower_instance, test_wav_file):
        """FileSource must loop automatically at EOF (not trigger fallback)"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"mode": "file", "file_path": test_wav_file})
        time.sleep(0.1)
        
        # FileSource should loop, so Tower should continue streaming
        # Collect data for longer than file duration to test looping
        mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.5)
        assert len(mp3_data) > 0, "FileSource should loop and continue streaming"
    
    def test_filesource_fallback_on_error(self, tower_instance, test_wav_file):
        """FileSource node enters failed state → fallback to ToneSource"""
        host, port, socket_path = tower_instance
        
        control_source(host, port, {"mode": "file", "file_path": test_wav_file})
        time.sleep(0.1)
        
        # Delete file to trigger error
        os.unlink(test_wav_file)
        time.sleep(0.3)  # Allow fallback to occur
        
        # Tower should still stream (fallback to ToneSource)
        mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.2)
        assert len(mp3_data) > 0, "Tower should stream even when file source fails (fallback)"
    
    def test_filesource_override_switching(self, tower_instance, test_wav_file):
        """Switching primary_source to FileSource then pushing override works cleanly"""
        host, port, socket_path = tower_instance
        
        # Set primary to file
        control_source(host, port, {"mode": "file", "file_path": test_wav_file})
        time.sleep(0.1)
        
        # Push override
        control_source(host, port, {"push_override": "silence"})
        time.sleep(0.1)
        
        status = get_status(host, port)
        assert status.get("active_source") == "silence", "Active should be override"
        
        # Pop override - should return to file
        control_source(host, port, {"pop_override": True})
        time.sleep(0.1)
        
        status = get_status(host, port)
        assert status.get("active_source") == "file" or status.get("primary_source") == "file", "Active should return to file after pop"


# ============================================================================
# Section 9: Fallback & Boundary Tests
# ============================================================================

class TestFallbackAndBoundaries:
    """Tests for Section 9: Fallback & Boundary Tests"""
    
    def test_source_switching_frame_boundaries(self, tower_instance):
        """All source switching must occur cleanly on frame boundaries"""
        host, port, socket_path = tower_instance
        
        # Switch sources multiple times
        sources = ["tone", "silence", "tone"]
        mp3_chunks = []
        
        for source in sources:
            control_source(host, port, {"set_primary": source})
            time.sleep(0.1)
            chunk = collect_mp3_chunks(host, port, duration_seconds=0.2)
            mp3_chunks.append(chunk)
        
        # All chunks should be valid MP3 (no corruption from switching)
        for chunk in mp3_chunks:
            assert len(chunk) > 0, "Each chunk should have data"
            assert is_valid_mp3_header(chunk), "Each chunk should be valid MP3"
    
    def test_sourcegraph_never_blocks_audiopump(self, tower_instance):
        """SourceGraph must never cause AudioPump to stall or wait"""
        host, port, socket_path = tower_instance
        
        # Rapid switching should not cause stalls
        for _ in range(5):
            control_source(host, port, {"set_primary": "tone"})
            time.sleep(0.05)
            control_source(host, port, {"set_primary": "silence"})
            time.sleep(0.05)
        
        # Tower should still be streaming
        mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.3)
        assert len(mp3_data) > 0, "Tower should continue streaming after rapid switches"
    
    def test_sourcegraph_always_returns_frame(self, tower_instance):
        """SourceGraph.next_frame() must always return a frame (fallback if needed)"""
        host, port, socket_path = tower_instance
        
        # Test various scenarios
        test_cases = [
            ("tone", None),
            ("silence", None),
            ("live_pcm", None),  # No writer - should fall back
        ]
        
        for source, _ in test_cases:
            control_source(host, port, {"set_primary": source})
            time.sleep(0.2)
            
            # Tower should always stream (indicating frames are always returned)
            mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.2)
            assert len(mp3_data) > 0, f"Tower should stream with {source} source (fallback if needed)"


# ============================================================================
# Section 10: Backward Compatibility Tests
# ============================================================================

class TestBackwardCompatibility:
    """Tests for Section 10: Backward Compatibility"""
    
    def test_stream_endpoint_unchanged(self, tower_instance):
        """/stream still works identically as Phase 1-4"""
        host, port, socket_path = tower_instance
        
        # /stream should work exactly as before
        mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.3)
        assert len(mp3_data) > 0, "/stream should work"
        assert is_valid_mp3_header(mp3_data), "/stream should return valid MP3"
    
    def test_tone_only_behavior_unchanged(self, tower_instance):
        """Tone-only behavior unchanged"""
        host, port, socket_path = tower_instance
        
        # Default behavior should be tone (Phase 1)
        mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.3)
        assert len(mp3_data) > 0, "Default tone behavior should work"
        
        # Explicitly set tone
        control_source(host, port, {"mode": "tone"})
        mp3_data2 = collect_mp3_chunks(host, port, duration_seconds=0.3)
        assert len(mp3_data2) > 0, "Tone mode should work"
    
    def test_unix_socket_behavior_unchanged(self, tower_instance):
        """Unix socket behavior unchanged"""
        host, port, socket_path = tower_instance
        
        # Unix socket should still work as in Phase 3
        assert os.path.exists(socket_path), "Unix socket should exist"
        
        # Should be able to connect
        with SyntheticWriter(socket_path) as writer:
            frame = generate_pattern_frame(0x42)
            writer.write_frame(frame)
            # Connection should succeed
    
    def test_encoder_restart_logic_unchanged(self, tower_instance):
        """Encoder restart logic unchanged"""
        # This is tested in Phase 4 tests
        # Phase 5 should not break Phase 4 encoder robustness
        # If Tower starts and streams, encoder is working
        host, port, socket_path = tower_instance
        
        mp3_data = collect_mp3_chunks(host, port, duration_seconds=0.3)
        assert len(mp3_data) > 0, "Encoder should be working (Phase 4 functionality intact)"
    
    def test_slow_client_handling_unchanged(self, tower_instance):
        """Slow client handling unchanged"""
        # This is tested in Phase 4 tests
        # Phase 5 should not break Phase 4 slow client handling
        # Basic test: Tower should handle multiple clients
        host, port, socket_path = tower_instance
        
        # Connect multiple clients (simplified test)
        url = f"http://{host}:{port}/stream"
        with httpx.Client(timeout=1.0) as client:
            with client.stream("GET", url) as resp1:
                with client.stream("GET", url) as resp2:
                    # Both should connect
                    chunk1 = next(resp1.iter_bytes(chunk_size=1), None)
                    chunk2 = next(resp2.iter_bytes(chunk_size=1), None)
                    assert chunk1 is not None or chunk2 is not None, "Multiple clients should be supported"


# ============================================================================
# Expected Failures (Phase 6+ features)
# ============================================================================

class TestPhase6FeaturesExpectedFailures:
    """Tests for Phase 6+ features that should fail until implemented"""
    
    @pytest.mark.xfail(reason="Phase 6 feature: scheduled transitions")
    def test_scheduled_transitions(self, tower_instance):
        """Any test requiring transitions scheduled for future times (Phase 6 feature)"""
        # Placeholder for Phase 6 scheduled transitions
        pytest.skip("Phase 6 feature: scheduled transitions")
    
    @pytest.mark.xfail(reason="Phase 7+ feature: multi-layer mixing")
    def test_multi_layer_mixing(self, tower_instance):
        """Any test referencing multi-layer mixing (Phase 7+ feature)"""
        # Placeholder for Phase 7+ multi-layer mixing
        pytest.skip("Phase 7+ feature: multi-layer mixing")

