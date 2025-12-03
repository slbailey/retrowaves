"""
Asset Discovery Manager for Appalachia Radio 3.2.

Scans DJ asset directories to discover intros and outros based on naming conventions.
Runs hourly scans during THINK windows to maintain an in-memory cache.

Phase 9: Hourly asset discovery system.

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


class AssetDiscoveryManager:
    """
    Manages discovery and caching of intro/outro assets.
    
    Scans DJ_PATH directory tree to find:
    - Per-song intros: <songroot>_intro*.mp3
    - Per-song outros: <songroot>_outtro*.mp3
    - Generic intros: generic_intro*.mp3
    
    Maintains in-memory maps for fast access during THINK phase.
    Only scans once per hour (configurable).
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
        
        # In-memory caches (built during scan)
        self.intros_per_song: Dict[str, List[str]] = {}  # songroot -> [list of intro paths]
        self.outtros_per_song: Dict[str, List[str]] = {}  # songroot -> [list of outro paths]
        self.generic_intros: List[str] = []  # list of generic intro paths
        self.generic_outros: List[str] = []  # list of generic outro paths
        
        # Perform initial scan
        self._scan()
    
    def maybe_rescan(self) -> None:
        """
        Rescan directories if enough time has passed.
        
        Should be called during THINK phase (on_segment_started).
        Only scans once per hour to avoid blocking.
        """
        now = time.time()
        
        # First scan or enough time has passed
        if self.last_scan_time is None or (now - self.last_scan_time) >= self.scan_interval_seconds:
            self._scan()
    
    def _scan(self) -> None:
        """
        Scan DJ_PATH directory tree for intro/outro assets.
        
        Discovers:
        - Per-song intros: <songroot>_intro*.mp3
        - Per-song outros: <songroot>_outt?ro*.mp3 (matches both _outro and _outtro)
        - Generic intros: generic_intro*.mp3
        - Generic outros: generic_outt?ro*.mp3 (matches both generic_outro and generic_outtro)
        
        Ignores:
        - JulieScene*.mp3
        - CatherineScene*.mp3
        - mus_radio_76_general_*
        - Anything not matching patterns
        - Non-.mp3 files
        """
        logger.info("[ASSET SCAN] Scanning intros/outtros...")
        
        # Clear previous results
        self.intros_per_song.clear()
        self.outtros_per_song.clear()
        self.generic_intros.clear()
        self.generic_outros.clear()
        
        if not self.dj_path.exists():
            logger.warning(f"[ASSET SCAN] DJ path does not exist: {self.dj_path}")
            self.last_scan_time = time.time()
            return
        
        # Patterns to match
        # Note: Accept both _outro (canonical) and _outtro (historical typo) for compatibility
        intro_pattern = re.compile(r'^(.+?)_intro.*\.mp3$', re.IGNORECASE)
        outro_pattern = re.compile(r'^(.+?)_outt?ro.*\.mp3$', re.IGNORECASE)  # Matches both _outro and _outtro
        generic_intro_pattern = re.compile(r'^generic_intro.*\.mp3$', re.IGNORECASE)
        generic_outro_pattern = re.compile(r'^generic_outt?ro.*\.mp3$', re.IGNORECASE)  # Matches both generic_outro and generic_outtro
        
        # Patterns to ignore
        ignore_patterns = [
            re.compile(r'^JulieScene.*', re.IGNORECASE),
            re.compile(r'^CatherineScene.*', re.IGNORECASE),
            re.compile(r'^mus_radio_76_general_.*', re.IGNORECASE),
        ]
        
        def should_ignore(filename: str) -> bool:
            """Check if file should be ignored."""
            for pattern in ignore_patterns:
                if pattern.match(filename):
                    return True
            return False
        
        # Walk the directory tree
        for root, dirs, files in os.walk(self.dj_path):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for filename in files:
                # Only process .mp3 files
                if not filename.lower().endswith('.mp3'):
                    continue
                
                full_path = os.path.join(root, filename)
                
                # Check for generic intros FIRST (before per-song patterns and ignore patterns)
                if generic_intro_pattern.match(filename):
                    self.generic_intros.append(full_path)
                    continue
                
                # Check for generic outros (before per-song patterns and ignore patterns)
                if generic_outro_pattern.match(filename):
                    self.generic_outros.append(full_path)
                    continue
                
                # Check for per-song intros (before ignore patterns - intros/outros should never be ignored)
                intro_match = intro_pattern.match(filename)
                if intro_match:
                    songroot = intro_match.group(1)
                    # Skip if it's actually a generic intro (shouldn't happen, but safety check)
                    if songroot.lower() != "generic":
                        if songroot not in self.intros_per_song:
                            self.intros_per_song[songroot] = []
                        self.intros_per_song[songroot].append(full_path)
                    continue
                
                # Check for per-song outros (before ignore patterns - intros/outros should never be ignored)
                outro_match = outro_pattern.match(filename)
                if outro_match:
                    songroot = outro_match.group(1)
                    # Skip if it's actually a generic outro (shouldn't happen, but safety check)
                    if songroot.lower() != "generic":
                        if songroot not in self.outtros_per_song:
                            self.outtros_per_song[songroot] = []
                        self.outtros_per_song[songroot].append(full_path)
                    continue
                
                # Skip ignored files (only after we've checked for intro/outro patterns)
                if should_ignore(filename):
                    continue
        
        # Update scan time
        self.last_scan_time = time.time()
        
        # Log results
        total_per_song_intros = sum(len(v) for v in self.intros_per_song.values())
        total_per_song_outtros = sum(len(v) for v in self.outtros_per_song.values())
        unique_songs_with_intros = len(self.intros_per_song)
        unique_songs_with_outtros = len(self.outtros_per_song)
        logger.info(
            f"[ASSET SCAN] Found {total_per_song_intros} per-song intros "
            f"({unique_songs_with_intros} unique songs), "
            f"{total_per_song_outtros} per-song outtros "
            f"({unique_songs_with_outtros} unique songs), "
            f"{len(self.generic_intros)} generic intros, "
            f"{len(self.generic_outros)} generic outros."
        )
        
        # Debug: log a few examples if we found any
        if total_per_song_intros > 0:
            example_intros = list(self.intros_per_song.items())[:3]
            logger.debug(f"[ASSET SCAN] Example per-song intros: {example_intros}")
        if total_per_song_outtros > 0:
            example_outtros = list(self.outtros_per_song.items())[:3]
            logger.debug(f"[ASSET SCAN] Example per-song outtros: {example_outtros}")
    
    def get_intros_for_song(self, song_path: str) -> List[str]:
        """
        Get intro paths for a specific song.
        
        Args:
            song_path: Full path to the song file
            
        Returns:
            List of intro file paths (empty if none found)
        """
        # Extract songroot from song path
        songroot = self._extract_songroot(song_path)
        if not songroot:
            return []
        
        return self.intros_per_song.get(songroot, [])
    
    def get_outtros_for_song(self, song_path: str) -> List[str]:
        """
        Get outro paths for a specific song.
        
        Args:
            song_path: Full path to the song file
            
        Returns:
            List of outro file paths (empty if none found)
        """
        # Extract songroot from song path
        songroot = self._extract_songroot(song_path)
        if not songroot:
            return []
        
        return self.outtros_per_song.get(songroot, [])
    
    def get_generic_outros(self) -> List[str]:
        """
        Get generic outro paths.
        
        Returns:
            List of generic outro file paths (empty if none found)
        """
        return self.generic_outros
    
    def _extract_songroot(self, song_path: str) -> Optional[str]:
        """
        Extract songroot from song path.
        
        Given: /mnt/.../songs/Foo_Bar.mp3
        Returns: Foo_Bar
        
        Args:
            song_path: Full path to song file
            
        Returns:
            Songroot (filename without extension) or None
        """
        try:
            path_obj = Path(song_path)
            # Get filename without extension
            songroot = path_obj.stem
            return songroot
        except Exception as e:
            logger.debug(f"[ASSET SCAN] Could not extract songroot from {song_path}: {e}")
            return None

