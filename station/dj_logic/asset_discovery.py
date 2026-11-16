"""
Asset Discovery Manager for Appalachia Radio 3.2.

Scans the DJ asset tree and keeps an in-memory cache of intros, outros,
station IDs and lifecycle announcements. Runs at startup and hourly during
THINK windows (ADM1.1); DJEngine reads only from this cache (ADM2.1).

Two layouts are supported. The layout is detected per scan, so pointing
DJ_PATH back at an old tree is a complete rollback.

v2 layout (directory-categorized, per ADM1.2) — detected by `between-songs/`:

    <DJ_PATH>/
      between-songs/<song key>/Intro - ....mp3      song key == song filename stem
      between-songs/<song key>/Outro - ....mp3
      generic/Intro - ....mp3 | Outro - ....mp3     fallback when a song has none
      station-ids/legal/*.mp3                       one file == one ID
      station-ids/generic/*.mp3
      station-ids/sequences/<name>/*.mp3            one folder == one ID, played in filename order
      lifecycle/startup/*.mp3
      lifecycle/shutdown/*.mp3
      story/, archive/                              never scheduled

Legacy flat layout (pre-v2):
    <songroot>_intro*.mp3, <songroot>_outt?ro*.mp3, generic_intro*.mp3,
    generic_outt?ro*.mp3, ids/{legal,generic}/*.mp3,
    station_starting_up/*.mp3, station_shutting_down/*.mp3

Architecture 3.2 Reference:
- Section 3.2: on_segment_started (THINK) - scanning happens here
- Section 4.3: DJ Prep Window Behavior (THINK)
"""

import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# v2: role is the leading word of the filename ("Intro - ...", "Outro - ...").
# "Outtro" is accepted for parity with the legacy typo (ADM2.2).
_V2_INTRO = re.compile(r"^intro\b", re.IGNORECASE)
_V2_OUTRO = re.compile(r"^outt?ro\b", re.IGNORECASE)

# Legacy flat patterns.
_LEGACY_INTRO = re.compile(r"^(.+?)_intro.*\.mp3$", re.IGNORECASE)
_LEGACY_OUTRO = re.compile(r"^(.+?)_outt?ro.*\.mp3$", re.IGNORECASE)
_LEGACY_GENERIC_INTRO = re.compile(r"^generic_intro.*\.mp3$", re.IGNORECASE)
_LEGACY_GENERIC_OUTRO = re.compile(r"^generic_outt?ro.*\.mp3$", re.IGNORECASE)
_LEGACY_IGNORE = (
    re.compile(r"^JulieScene.*", re.IGNORECASE),
    re.compile(r"^CatherineScene.*", re.IGNORECASE),
    re.compile(r"^mus_radio_76_general_.*", re.IGNORECASE),
)


def _mp3s(directory: Path) -> List[str]:
    """Sorted .mp3 files directly inside directory (non-recursive, no hidden files)."""
    if not directory.is_dir():
        return []
    return sorted(
        str(p) for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() == ".mp3" and not p.name.startswith(".")
    )


class AssetDiscoveryManager:
    """
    Manages discovery and caching of DJ assets.

    Cached (all replaced atomically at the end of each scan, ADM2.1):
    - intros_per_song / outtros_per_song: song key -> [paths]
    - generic_intros / generic_outros: [paths]
    - legal_ids / generic_ids: [[paths]] — each entry is one ID, which may be a
      multi-file sequence that must air in order
    - startup_announcements / shutdown_announcements: [paths]
    """

    def __init__(self, dj_path: Path, scan_interval_seconds: int = 3600):
        """
        Initialize asset discovery manager.

        Args:
            dj_path: Path to DJ assets directory
            scan_interval_seconds: How often to rescan (default: 3600 = 1 hour)
        """
        self.dj_path = Path(dj_path)
        self.scan_interval_seconds = scan_interval_seconds
        self.last_scan_time: Optional[float] = None
        self.layout: str = "none"

        self.intros_per_song: Dict[str, List[str]] = {}
        self.outtros_per_song: Dict[str, List[str]] = {}
        self.generic_intros: List[str] = []
        self.generic_outros: List[str] = []
        self.legal_ids: List[List[str]] = []
        self.generic_ids: List[List[str]] = []

        # Lifecycle announcement pools (per ADM2.4)
        self.startup_announcements: List[str] = []
        self.shutdown_announcements: List[str] = []

        self._scan()

    def maybe_rescan(self) -> None:
        """
        Rescan directories if enough time has passed.

        Should be called during THINK phase (on_segment_started).
        Only scans once per hour to avoid blocking.
        """
        now = time.time()
        if self.last_scan_time is None or (now - self.last_scan_time) >= self.scan_interval_seconds:
            self._scan()

    # ------------------------------------------------------------------ scanning

    def _empty(self) -> dict:
        return {
            "layout": "none",
            "intros_per_song": {},
            "outtros_per_song": {},
            "generic_intros": [],
            "generic_outros": [],
            "legal_ids": [],
            "generic_ids": [],
            "startup_announcements": [],
            "shutdown_announcements": [],
        }

    def _scan(self) -> None:
        """Scan DJ_PATH, build a fresh cache, then swap it in atomically."""
        logger.info("[ASSET SCAN] Scanning DJ assets...")
        if not self.dj_path.exists():
            logger.warning(f"[ASSET SCAN] DJ path does not exist: {self.dj_path}")
            self._apply(self._empty())
            self.last_scan_time = time.time()
            return

        if (self.dj_path / "between-songs").is_dir():
            cache = self._scan_v2()
        else:
            cache = self._scan_legacy()
        self._apply(cache)
        self.last_scan_time = time.time()
        self._log_summary()

    def _apply(self, cache: dict) -> None:
        for key, value in cache.items():
            setattr(self, key, value)

    def _scan_v2(self) -> dict:
        root = self.dj_path
        cache = self._empty()
        cache["layout"] = "v2"

        songs_dir = root / "between-songs"
        for song_dir in sorted(p for p in songs_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
            for path in _mp3s(song_dir):
                name = Path(path).name
                if _V2_INTRO.match(name):
                    cache["intros_per_song"].setdefault(song_dir.name, []).append(path)
                elif _V2_OUTRO.match(name):
                    cache["outtros_per_song"].setdefault(song_dir.name, []).append(path)
                else:
                    logger.warning(f"[ASSET SCAN] Unrecognized clip (expected 'Intro - ' or 'Outro - '): {path}")

        for path in _mp3s(root / "generic"):
            name = Path(path).name
            if _V2_INTRO.match(name):
                cache["generic_intros"].append(path)
            elif _V2_OUTRO.match(name):
                cache["generic_outros"].append(path)

        ids_root = root / "station-ids"
        cache["legal_ids"] = [[p] for p in _mp3s(ids_root / "legal")]
        cache["generic_ids"] = [[p] for p in _mp3s(ids_root / "generic")]
        sequences = ids_root / "sequences"
        if sequences.is_dir():
            for seq_dir in sorted(p for p in sequences.iterdir() if p.is_dir() and not p.name.startswith(".")):
                parts = _mp3s(seq_dir)
                if parts:
                    cache["generic_ids"].append(parts)

        cache["startup_announcements"] = _mp3s(root / "lifecycle" / "startup")
        cache["shutdown_announcements"] = _mp3s(root / "lifecycle" / "shutdown")
        return cache

    def _scan_legacy(self) -> dict:
        root = self.dj_path
        cache = self._empty()
        cache["layout"] = "legacy"

        cache["startup_announcements"] = _mp3s(root / "station_starting_up")
        cache["shutdown_announcements"] = _mp3s(root / "station_shutting_down")
        cache["legal_ids"] = [[p] for p in _mp3s(root / "ids" / "legal")]
        cache["generic_ids"] = [[p] for p in _mp3s(root / "ids" / "generic")]

        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            here = Path(dirpath)
            if here.name in ("station_starting_up", "station_shutting_down") or "ids" in here.relative_to(root).parts:
                continue
            for filename in sorted(files):
                if not filename.lower().endswith(".mp3"):
                    continue
                full_path = os.path.join(dirpath, filename)
                if _LEGACY_GENERIC_INTRO.match(filename):
                    cache["generic_intros"].append(full_path)
                    continue
                if _LEGACY_GENERIC_OUTRO.match(filename):
                    cache["generic_outros"].append(full_path)
                    continue
                m = _LEGACY_INTRO.match(filename)
                if m and m.group(1).lower() != "generic":
                    cache["intros_per_song"].setdefault(m.group(1), []).append(full_path)
                    continue
                m = _LEGACY_OUTRO.match(filename)
                if m and m.group(1).lower() != "generic":
                    cache["outtros_per_song"].setdefault(m.group(1), []).append(full_path)
                    continue
                if any(p.match(filename) for p in _LEGACY_IGNORE):
                    continue
        return cache

    def _log_summary(self) -> None:
        intros = sum(len(v) for v in self.intros_per_song.values())
        outtros = sum(len(v) for v in self.outtros_per_song.values())
        sequences = sum(1 for entry in self.generic_ids if len(entry) > 1)
        logger.info(
            f"[ASSET SCAN] layout={self.layout}: "
            f"{intros} per-song intros ({len(self.intros_per_song)} songs), "
            f"{outtros} per-song outtros ({len(self.outtros_per_song)} songs), "
            f"{len(self.generic_intros)} generic intros, "
            f"{len(self.generic_outros)} generic outros, "
            f"{len(self.legal_ids)} legal IDs, "
            f"{len(self.generic_ids)} generic IDs ({sequences} sequences), "
            f"{len(self.startup_announcements)} startup announcements, "
            f"{len(self.shutdown_announcements)} shutdown announcements."
        )

    # ------------------------------------------------------------------ lookups

    def get_intros_for_song(self, song_path: str) -> List[str]:
        """Intro paths for a song (empty if none)."""
        songroot = self._extract_songroot(song_path)
        return self.intros_per_song.get(songroot, []) if songroot else []

    def get_outtros_for_song(self, song_path: str) -> List[str]:
        """Outro paths for a song (empty if none)."""
        songroot = self._extract_songroot(song_path)
        return self.outtros_per_song.get(songroot, []) if songroot else []

    def get_generic_outros(self) -> List[str]:
        """Generic outro paths."""
        return self.generic_outros

    def get_station_ids(self, legal: bool) -> List[List[str]]:
        """Cached station IDs; each entry is an ordered list of paths (len > 1 = sequence)."""
        return self.legal_ids if legal else self.generic_ids

    def _extract_songroot(self, song_path: str) -> Optional[str]:
        """
        Song key = song filename without extension.

        /mnt/.../music/regular/Ink Spots - Maybe.mp3 -> "Ink Spots - Maybe"
        """
        try:
            return Path(song_path).stem
        except Exception as e:
            logger.debug(f"[ASSET SCAN] Could not extract songroot from {song_path}: {e}")
            return None
