"""
Shared pytest fixtures for contract tests.
"""
import pytest
import threading
from unittest.mock import Mock

from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.encoder_manager import EncoderManager


@pytest.fixture
def components():
    """Create test components for AudioPump tests.
    
    Returns:
        tuple: (pcm_buffer, fallback, encoder_manager)
    """
    pcm_buffer = FrameRingBuffer(capacity=10)
    fallback = Mock()
    fallback.get_frame.return_value = b'\x00' * 4608  # 1152 samples * 2 channels * 2 bytes
    encoder_manager = Mock(spec=EncoderManager)
    # Per contract [A3], [A7]: AudioPump only calls next_frame(), not write_pcm() directly
    encoder_manager.next_frame = Mock()
    # write_pcm() is called internally by EncoderManager, not by AudioPump
    encoder_manager.write_pcm = Mock()
    return pcm_buffer, fallback, encoder_manager


@pytest.fixture(autouse=False)  # Set to True to enable automatic thread leak detection
def thread_leak_guard():
    """
    Optional fixture to detect thread leaks between tests.
    
    This ensures shutdown contracts are actually respected across tests.
    Enable by setting autouse=True or request it explicitly in tests.
    """
    before = set(t.ident for t in threading.enumerate())
    yield
    after = set(t.ident for t in threading.enumerate())
    leaked = after - before
    if leaked:
        leaked_threads = [t for t in threading.enumerate() if t.ident in leaked]
        thread_info = '\n'.join(f"  - {t.name} (daemon={t.daemon})" for t in leaked_threads)
        assert False, f"Thread leak detected — shutdown incomplete.\nLeaked threads:\n{thread_info}"



@pytest.fixture(autouse=True)
def isolated_tower_endpoints(monkeypatch, tmp_path):
    """Never let a test TowerService touch the production port or PCM socket.

    TowerService reads TOWER_PORT and TOWER_PCM_SOCKET_PATH at construction.
    Their defaults (:8005, /run/retrowaves/pcm.sock) are the LIVE tower's on the
    station VM: a test that bound them would either collide (EADDRINUSE) or,
    run as the service user, unlink and replace the live ingest socket.
    """
    from tower.tests.contracts._tower_harness import find_free_port
    monkeypatch.setenv("TOWER_HOST", "127.0.0.1")
    monkeypatch.setenv("TOWER_PORT", str(find_free_port()))
    monkeypatch.setenv("TOWER_PCM_SOCKET_PATH", str(tmp_path / "pcm.sock"))
