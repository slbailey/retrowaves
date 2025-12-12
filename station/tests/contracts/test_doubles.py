"""
Test doubles (fakes, stubs, mocks) for Station contract tests.

These provide minimal implementations that satisfy contract interfaces
without real dependencies (files, directories, environment variables, etc.).
"""

from typing import List, Optional, Dict
from pathlib import Path
from unittest.mock import Mock
import numpy as np

from station.broadcast_core.audio_event import AudioEvent


# Canonical PCM format constants
CANONICAL_FRAME_SIZE_SAMPLES = 1024
CANONICAL_SAMPLE_RATE = 48000
CANONICAL_CHANNELS = 2
CANONICAL_FRAME_BYTES = CANONICAL_FRAME_SIZE_SAMPLES * CANONICAL_CHANNELS * 2  # 4096


class FakeMediaLibrary:
    """Fake MediaLibrary that provides test data without file system access."""
    
    def __init__(self, regular_tracks: Optional[List[str]] = None, holiday_tracks: Optional[List[str]] = None):
        self.regular_tracks = regular_tracks or ["/fake/regular1.mp3", "/fake/regular2.mp3"]
        self.holiday_tracks = holiday_tracks or ["/fake/holiday1.mp3", "/fake/holiday2.mp3"]
        self.all_tracks = self.regular_tracks + self.holiday_tracks


class FakeRotationManager:
    """Fake RotationManager with deterministic output."""
    
    def __init__(self, regular_tracks: Optional[List[str]] = None, holiday_tracks: Optional[List[str]] = None):
        self._regular_tracks = regular_tracks or ["/fake/regular1.mp3", "/fake/regular2.mp3"]
        self._holiday_tracks = holiday_tracks or ["/fake/holiday1.mp3", "/fake/holiday2.mp3"]
        self.history: List[tuple] = []
        self.play_counts: Dict[str, int] = {}
        self.holiday_play_counts: Dict[str, int] = {}
        self.state_file: Optional[str] = None
        self._selection_index = 0
    
    def select_next_song(self) -> str:
        """Deterministically select next song (cycles through tracks)."""
        all_tracks = self._regular_tracks + self._holiday_tracks
        if not all_tracks:
            return "/fake/default.mp3"
        track = all_tracks[self._selection_index % len(all_tracks)]
        self._selection_index += 1
        return track
    
    def record_song_played(self, filepath: str) -> None:
        """Record that a song was played."""
        import time
        is_holiday = filepath in self._holiday_tracks
        self.history.append((filepath, time.time(), is_holiday))
        if is_holiday:
            self.holiday_play_counts[filepath] = self.holiday_play_counts.get(filepath, 0) + 1
        else:
            self.play_counts[filepath] = self.play_counts.get(filepath, 0) + 1
    
    def is_holiday_season(self) -> bool:
        """Fake holiday season detection."""
        return False
    
    def get_holiday_selection_probability(self) -> float:
        """Fake holiday probability."""
        return 0.0
    
    def get_last_played_songs(self, count: int = 10) -> List[str]:
        """Get last played songs."""
        return [h[0] for h in self.history[-count:]]
    
    def save_state(self) -> None:
        """Fake state save (no-op)."""
        pass
    
    def load_state(self) -> bool:
        """Fake state load (no-op)."""
        return False


class FakeAssetDiscoveryManager:
    """Fake AssetDiscoveryManager that provides test data without file system access."""
    
    def __init__(self, dj_path: Optional[Path] = None, scan_interval_seconds: int = 3600):
        self.dj_path = dj_path or Path("/fake/dj_path")
        self.scan_interval_seconds = scan_interval_seconds
        self.last_scan_time: Optional[float] = None
        
        # Pre-populated fake caches
        self.intros_per_song: Dict[str, List[str]] = {
            "song1": ["/fake/intro1_song1.mp3"],
            "song2": ["/fake/intro1_song2.mp3"],
            "regular1": ["/fake/intro1_regular1.mp3"],  # Match fake rotation manager tracks
            "regular2": ["/fake/intro1_regular2.mp3"],
        }
        self.outtros_per_song: Dict[str, List[str]] = {
            "song1": ["/fake/outro1_song1.mp3"],
            "song2": ["/fake/outro1_song2.mp3"],
            "regular1": ["/fake/outro1_regular1.mp3"],
            "regular2": ["/fake/outro1_regular2.mp3"],
        }
        self.generic_intros: List[str] = ["/fake/generic_intro1.mp3"]
        self.generic_outros: List[str] = ["/fake/generic_outro1.mp3"]
        
        # Lifecycle announcement pools (per ASSET_DISCOVERY_MANAGER_CONTRACT ADM2.4)
        self.startup_announcements: List[str] = []
        self.shutdown_announcements: List[str] = []
        
        # Simulate initial scan
        import time
        self.last_scan_time = time.time()
    
    def maybe_rescan(self) -> None:
        """Fake rescan (updates timestamp only)."""
        import time
        now = time.time()
        if self.last_scan_time is None or (now - self.last_scan_time) >= self.scan_interval_seconds:
            self.last_scan_time = now
    
    def _scan(self) -> None:
        """Fake scan (updates timestamp only)."""
        import time
        self.last_scan_time = time.time()
    
    def _extract_songroot(self, song_path: str) -> Optional[str]:
        """Extract songroot from song path (fake implementation)."""
        # Extract basename without extension
        import os
        basename = os.path.basename(song_path)
        if basename.endswith('.mp3'):
            return basename[:-4]  # Remove .mp3 extension
        return basename
    
    def get_intros_for_song(self, song_path: str) -> List[str]:
        """Get intro paths for a specific song."""
        songroot = self._extract_songroot(song_path)
        if not songroot:
            return []
        return self.intros_per_song.get(songroot, [])
    
    def get_outtros_for_song(self, song_path: str) -> List[str]:
        """Get outro paths for a specific song."""
        songroot = self._extract_songroot(song_path)
        if not songroot:
            return []
        return self.outtros_per_song.get(songroot, [])
    
    def get_generic_outros(self) -> List[str]:
        """Get generic outro paths."""
        return self.generic_outros.copy()


class StubFFmpegDecoder:
    """Stub decoder that outputs fixed PCM frames without real file access."""
    
    def __init__(self, file_path: str, frame_size_samples: int = CANONICAL_FRAME_SIZE_SAMPLES):
        self.file_path = file_path
        self.frame_size_samples = frame_size_samples
        self._frame_count = 0
        self._max_frames = 10  # Generate 10 frames then stop
    
    def __iter__(self):
        return self
    
    def __next__(self):
        """Generate next PCM frame (fake data)."""
        if self._frame_count >= self._max_frames:
            raise StopIteration
        
        # Generate fake PCM frame (silence)
        frame = np.zeros((self.frame_size_samples, CANONICAL_CHANNELS), dtype=np.int16)
        self._frame_count += 1
        return frame
    
    def close(self) -> None:
        """Fake close (no-op)."""
        pass


class StubOutputSink:
    """Stub output sink that records writes without real I/O."""
    
    def __init__(self):
        self.written_frames: List[np.ndarray] = []
        self.write_count = 0
        self.closed = False
    
    def write(self, frame: np.ndarray) -> None:
        """Record frame write."""
        if self.closed:
            raise ValueError("Sink is closed")
        self.written_frames.append(frame.copy())
        self.write_count += 1
    
    def close(self) -> None:
        """Mark sink as closed."""
        self.closed = True
    
    def get_written_frame_count(self) -> int:
        """Get number of frames written."""
        return self.write_count
    
    def get_last_frame(self) -> Optional[np.ndarray]:
        """Get last written frame."""
        return self.written_frames[-1] if self.written_frames else None


class FakeDJStateStore:
    """Fake state store that stores state in memory."""
    
    def __init__(self, path: Optional[str] = None):
        self.path = path or "/fake/state.json"
        self._state: Optional[dict] = None
    
    def save(self, state: dict) -> None:
        """Save state to memory."""
        self._state = state.copy()
    
    def load(self) -> Optional[dict]:
        """Load state from memory."""
        return self._state.copy() if self._state else None


def create_fake_audio_event(file_path: str = "/fake/test.mp3", event_type: str = "song", gain: float = 0.0) -> AudioEvent:
    """Create a fake AudioEvent for testing."""
    return AudioEvent(path=file_path, type=event_type, gain=gain)


def create_canonical_pcm_frame() -> np.ndarray:
    """Create a canonical PCM frame (1024 samples, 2 channels, 4096 bytes)."""
    return np.zeros((CANONICAL_FRAME_SIZE_SAMPLES, CANONICAL_CHANNELS), dtype=np.int16)


def create_partial_pcm_frame(samples: int = 512) -> np.ndarray:
    """Create a partial PCM frame (for testing partial frame handling)."""
    return np.zeros((samples, CANONICAL_CHANNELS), dtype=np.int16)

