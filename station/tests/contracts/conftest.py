"""
Shared pytest fixtures for Station contract tests.

Contract tests use test doubles (fakes, stubs, mocks) to avoid real dependencies.
No environment variables, real files, or real directories are used.
"""

import pytest
import threading
import tempfile
import os
from unittest.mock import Mock
import numpy as np
from pathlib import Path

from station.tests.contracts.test_doubles import (
    FakeMediaLibrary,
    FakeRotationManager,
    FakeAssetDiscoveryManager,
    StubFFmpegDecoder,
    StubOutputSink,
    FakeDJStateStore,
    create_fake_audio_event,
    create_canonical_pcm_frame,
    create_partial_pcm_frame,
)

# Canonical PCM format constants (per Tower's NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md)
CANONICAL_FRAME_SIZE_SAMPLES = 1024
CANONICAL_SAMPLE_RATE = 48000
CANONICAL_CHANNELS = 2
CANONICAL_FRAME_BYTES = CANONICAL_FRAME_SIZE_SAMPLES * CANONICAL_CHANNELS * 2  # 4096
CANONICAL_PCM_CADENCE_MS = (CANONICAL_FRAME_SIZE_SAMPLES / CANONICAL_SAMPLE_RATE) * 1000  # 21.333ms


@pytest.fixture
def canonical_pcm_frame():
    """Create a canonical PCM frame (1024 samples, 2 channels, 4096 bytes)."""
    return create_canonical_pcm_frame()


@pytest.fixture
def partial_pcm_frame():
    """Create a partial PCM frame (512 samples, 2 channels, 2048 bytes)."""
    return create_partial_pcm_frame(512)


@pytest.fixture
def invalid_size_frame():
    """Create an invalid size frame (1152 samples, 2 channels, 4608 bytes - old MP3 format)."""
    return np.zeros((1152, CANONICAL_CHANNELS), dtype=np.int16)


@pytest.fixture
def fake_media_library():
    """Create a fake MediaLibrary with test data."""
    return FakeMediaLibrary(
        regular_tracks=["/fake/regular1.mp3", "/fake/regular2.mp3", "/fake/regular3.mp3"],
        holiday_tracks=["/fake/holiday1.mp3", "/fake/holiday2.mp3"]
    )


@pytest.fixture
def fake_rotation_manager(fake_media_library):
    """Create a fake RotationManager with deterministic output."""
    return FakeRotationManager(
        regular_tracks=fake_media_library.regular_tracks,
        holiday_tracks=fake_media_library.holiday_tracks
    )


@pytest.fixture
def fake_asset_discovery_manager():
    """Create a fake AssetDiscoveryManager with test data."""
    return FakeAssetDiscoveryManager(dj_path=Path("/fake/dj_path"), scan_interval_seconds=1)


@pytest.fixture
def fake_dj_state_store():
    """Create a fake DJStateStore."""
    return FakeDJStateStore(path="/fake/state.json")


@pytest.fixture
def stub_output_sink():
    """Create a stub output sink that records writes."""
    return StubOutputSink()


@pytest.fixture
def stub_decoder():
    """Create a stub decoder that outputs fixed frames."""
    return StubFFmpegDecoder("/fake/test.mp3")


@pytest.fixture
def fake_audio_event():
    """Create a fake AudioEvent for testing."""
    return create_fake_audio_event()


@pytest.fixture
def mock_dj_callback():
    """Create a mock DJ callback for testing."""
    callback = Mock()
    callback.on_segment_started = Mock()
    callback.on_segment_finished = Mock()
    callback.on_station_start = Mock()
    callback.on_station_stop = Mock()
    return callback


@pytest.fixture
def mock_output_sink():
    """Create a mock output sink for testing."""
    sink = Mock()
    sink.write = Mock()
    sink.close = Mock()
    return sink


@pytest.fixture(autouse=False)
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
