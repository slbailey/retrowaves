import glob
import logging
import os
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MediaLibrary:
    """
    Filesystem-backed media library.
    
    Phase 1 requirements:
    - Read REGULAR_MUSIC_PATH and HOLIDAY_MUSIC_PATH from environment
    - Discover only .mp3 files (recursive)
    - Expose lists:
      - regular_tracks
      - holiday_tracks
      - all_tracks
    - Validate paths exist; raise RuntimeError if missing
    - No rotation/weighting/random choice logic
    """
    regular_tracks: List[str]
    holiday_tracks: List[str]
    all_tracks: List[str]

    @classmethod
    def from_env(cls, regular_env: str = "REGULAR_MUSIC_PATH", holiday_env: str = "HOLIDAY_MUSIC_PATH") -> "MediaLibrary":
        regular_path = os.getenv(regular_env)
        holiday_path = os.getenv(holiday_env)

        if not regular_path or not os.path.isdir(regular_path):
            raise RuntimeError(f"REGULAR_MUSIC_PATH is missing or not a directory: {regular_path!r}")
        if not holiday_path or not os.path.isdir(holiday_path):
            raise RuntimeError(f"HOLIDAY_MUSIC_PATH is missing or not a directory: {holiday_path!r}")

        def discover_mp3s(root: str) -> List[str]:
            pattern = os.path.join(root, "**", "*.mp3")
            return sorted(glob.glob(pattern, recursive=True))

        regular_tracks = discover_mp3s(regular_path)
        holiday_tracks = discover_mp3s(holiday_path)
        all_tracks = regular_tracks + holiday_tracks

        logger.info(
            f"[MediaLibrary] Discovered {len(regular_tracks)} regular tracks in {regular_path} "
            f"and {len(holiday_tracks)} holiday tracks in {holiday_path}"
        )

        return cls(regular_tracks=regular_tracks, holiday_tracks=holiday_tracks, all_tracks=all_tracks)


