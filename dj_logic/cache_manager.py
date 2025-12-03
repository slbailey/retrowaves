"""
Cache Manager for Appalachia Radio 3.1.

Manages cached audio assets (intros, outros, station IDs, talk bits)
and provides deterministic access to concrete MP3 files.

All generation functions are instant stubs that track files.
Later, ElevenLabs integration will slot in here.

Architecture 3.1 Reference:
- Section 2.5: Intros, Outros, Station IDs, and Talk Are Discrete MP3s
- Section 4.5: Deterministic Use of Cached Assets
"""

import logging
import os
import random
from pathlib import Path
from typing import Optional, List, Set

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Manages cached audio assets for the DJ.
    
    Provides deterministic access to concrete MP3 files that must
    exist before they are used. All DJ audio is pre-generated and
    cached before use.
    
    Tracks file existence in-memory for fast lookups.
    Generation functions are instant stubs (ElevenLabs will integrate later).
    
    Architecture 3.1 Reference: Section 4.5
    """
    
    def __init__(self, cache_root: Optional[Path] = None):
        """
        Initialize cache manager.
        
        Args:
            cache_root: Root directory for cached assets (default: cache/)
        """
        self.cache_root = cache_root or Path("cache")
        
        # Directory structure
        self.intros_root = self.cache_root / "intros"
        self.personality_intros_root = self.intros_root / "personality"
        self.generic_intros_root = self.intros_root / "generic"
        
        self.outros_root = self.cache_root / "outros"
        self.personality_outros_root = self.outros_root / "personality"
        self.generic_outros_root = self.outros_root / "generic"
        
        self.station_ids_root = self.cache_root / "station_ids"
        self.legal_ids_root = self.station_ids_root / "legal"
        self.generic_ids_root = self.station_ids_root / "generic"
        
        self.talk_bits_root = self.cache_root / "talk_bits"
        
        # In-memory file registry: tracks which files "exist"
        self._file_registry: Set[Path] = set()
        
        # Initialize cache directories and scan for existing files
        self._initialize_cache_structure()
        self._scan_existing_files()
        
        logger.info(f"CacheManager initialized: {len(self._file_registry)} files tracked")
    
    def _initialize_cache_structure(self) -> None:
        """Create cache directory structure if it doesn't exist."""
        directories = [
            self.personality_intros_root,
            self.generic_intros_root,
            self.personality_outros_root,
            self.generic_outros_root,
            self.legal_ids_root,
            self.generic_ids_root,
            self.talk_bits_root,
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    def _scan_existing_files(self) -> None:
        """Scan cache directories for existing MP3 files."""
        self._file_registry.clear()
        
        # Scan all cache directories
        for directory in [
            self.personality_intros_root,
            self.generic_intros_root,
            self.personality_outros_root,
            self.generic_outros_root,
            self.legal_ids_root,
            self.generic_ids_root,
            self.talk_bits_root,
        ]:
            if directory.exists():
                for file_path in directory.glob("*.mp3"):
                    self._file_registry.add(file_path)
        
        logger.debug(f"Scanned {len(self._file_registry)} existing files in cache")
    
    def exists(self, filepath: Path) -> bool:
        """
        Check if a cached file exists.
        
        Args:
            filepath: Path to check (can be Path object or string)
            
        Returns:
            True if file exists in registry
        """
        path = Path(filepath) if isinstance(filepath, str) else filepath
        
        # Check in-memory registry first (fast)
        if path in self._file_registry:
            return True
        
        # Also check filesystem (for robustness)
        if path.exists() and path.is_file():
            # Add to registry if found on disk
            self._file_registry.add(path)
            return True
        
        return False
    
    def _register_file(self, filepath: Path) -> None:
        """
        Register a file as existing in the cache.
        
        Args:
            filepath: Path to register
        """
        self._file_registry.add(filepath)
        logger.debug(f"[CACHE] Registered file: {filepath}")
    
    def get_intro_path(self, song_id: str, intro_type: str = "personality") -> Optional[Path]:
        """
        Get path to cached intro MP3 for a song.
        
        Args:
            song_id: ID or filepath of the song
            intro_type: Type of intro ("personality" or "generic")
            
        Returns:
            Path to intro file, or None if not cached
        """
        song_name = Path(song_id).stem
        
        if intro_type == "personality":
            intro_path = self.personality_intros_root / f"{song_name}_intro.mp3"
        else:
            intro_path = self.generic_intros_root / f"generic_intro_{song_name}.mp3"
        
        if self.exists(intro_path):
            return intro_path
        
        return None
    
    def get_outro_path(self, song_id: str, outro_type: str = "personality") -> Optional[Path]:
        """
        Get path to cached outro MP3 for a song.
        
        Args:
            song_id: ID or filepath of the song
            outro_type: Type of outro ("personality" or "generic")
            
        Returns:
            Path to outro file, or None if not cached
        """
        song_name = Path(song_id).stem
        
        if outro_type == "personality":
            outro_path = self.personality_outros_root / f"{song_name}_outro.mp3"
        else:
            outro_path = self.generic_outros_root / f"generic_outro_{song_name}.mp3"
        
        if self.exists(outro_path):
            return outro_path
        
        return None
    
    def get_station_id_path(self, id_type: str = "generic") -> Optional[Path]:
        """
        Get path to cached station ID MP3.
        
        Args:
            id_type: Type of ID ("legal" or "generic")
            
        Returns:
            Path to station ID file, or None if not cached
        """
        if id_type == "legal":
            # Get any legal ID
            legal_ids = list(self.generic_ids_root.glob("legal_id_*.mp3"))
            if not legal_ids:
                legal_ids = list(self.legal_ids_root.glob("*.mp3"))
            if legal_ids:
                return random.choice(legal_ids)
            return None
        else:
            # Get any generic ID
            generic_ids = list(self.generic_ids_root.glob("generic_id_*.mp3"))
            if not generic_ids:
                generic_ids = list(self.generic_ids_root.glob("*.mp3"))
            if generic_ids:
                return random.choice(generic_ids)
            return None
    
    def list_available_intros(self, song_id: Optional[str] = None) -> List[Path]:
        """
        List available intro files.
        
        Args:
            song_id: Optional song ID to filter by (for personality intros)
            
        Returns:
            List of paths to available intro files
        """
        if song_id:
            # Return personality intro for specific song if exists
            intro = self.get_intro_path(song_id, "personality")
            return [intro] if intro else []
        
        # Return all available intros from registry
        all_intros = [
            path for path in self._file_registry
            if path.parent in (self.personality_intros_root, self.generic_intros_root)
            and path.suffix == ".mp3"
        ]
        
        # Also check filesystem for any additional files
        for directory in [self.personality_intros_root, self.generic_intros_root]:
            if directory.exists():
                for file_path in directory.glob("*.mp3"):
                    if file_path not in self._file_registry:
                        self._register_file(file_path)
                        all_intros.append(file_path)
        
        return all_intros
    
    def list_available_outros(self, song_id: Optional[str] = None) -> List[Path]:
        """
        List available outro files.
        
        Args:
            song_id: Optional song ID to filter by (for personality outros)
            
        Returns:
            List of paths to available outro files
        """
        if song_id:
            # Return personality outro for specific song if exists
            outro = self.get_outro_path(song_id, "personality")
            return [outro] if outro else []
        
        # Return all available outros from registry
        all_outros = [
            path for path in self._file_registry
            if path.parent in (self.personality_outros_root, self.generic_outros_root)
            and path.suffix == ".mp3"
        ]
        
        # Also check filesystem for any additional files
        for directory in [self.personality_outros_root, self.generic_outros_root]:
            if directory.exists():
                for file_path in directory.glob("*.mp3"):
                    if file_path not in self._file_registry:
                        self._register_file(file_path)
                        all_outros.append(file_path)
        
        return all_outros
    
    def list_available_station_ids(self, id_type: Optional[str] = None) -> List[Path]:
        """
        List available station ID files.
        
        Args:
            id_type: Optional ID type to filter by ("legal" or "generic")
            
        Returns:
            List of paths to available station ID files
        """
        if id_type == "legal":
            target_dirs = [self.legal_ids_root]
        elif id_type == "generic":
            target_dirs = [self.generic_ids_root]
        else:
            target_dirs = [self.legal_ids_root, self.generic_ids_root]
        
        # Return all available IDs from registry
        all_ids = [
            path for path in self._file_registry
            if path.parent in target_dirs
            and path.suffix == ".mp3"
        ]
        
        # Also check filesystem for any additional files
        for directory in target_dirs:
            if directory.exists():
                for file_path in directory.glob("*.mp3"):
                    if file_path not in self._file_registry:
                        self._register_file(file_path)
                        all_ids.append(file_path)
        
        return all_ids
    
    def list_available_generic_intros(self) -> List[Path]:
        """
        List available generic intro files.
        
        Returns:
            List of paths to generic intro files
        """
        # Check registry for tracked files in generic intros directory
        available = [
            path for path in self._file_registry
            if path.parent == self.generic_intros_root and path.suffix == ".mp3"
        ]
        
        # Also check filesystem for any additional files
        if self.generic_intros_root.exists():
            for file_path in self.generic_intros_root.glob("*.mp3"):
                if file_path not in self._file_registry:
                    self._register_file(file_path)
                    available.append(file_path)
        
        return available
    
    def list_available_generic_outros(self) -> List[Path]:
        """
        List available generic outro files.
        
        Returns:
            List of paths to generic outro files
        """
        # Check registry for tracked files in generic outros directory
        available = [
            path for path in self._file_registry
            if path.parent == self.generic_outros_root and path.suffix == ".mp3"
        ]
        
        # Also check filesystem for any additional files
        if self.generic_outros_root.exists():
            for file_path in self.generic_outros_root.glob("*.mp3"):
                if file_path not in self._file_registry:
                    self._register_file(file_path)
                    available.append(file_path)
        
        return available
    
    def get_generic_intro(self) -> Optional[Path]:
        """
        Get a random generic intro from available pool.
        
        Returns:
            Path to generic intro, or None if none available
        """
        available = self.list_available_generic_intros()
        if available:
            return random.choice(available)
        return None
    
    def get_generic_outro(self) -> Optional[Path]:
        """
        Get a random generic outro from available pool.
        
        Returns:
            Path to generic outro, or None if none available
        """
        available = self.list_available_generic_outros()
        if available:
            return random.choice(available)
        return None
    
    def verify_file_exists(self, filepath: Path) -> bool:
        """
        Verify that a cached file exists.
        
        Architecture 3.1 Reference: Section 4.3 (Step 4)
        
        Args:
            filepath: Path to verify
            
        Returns:
            True if file exists and is accessible
        """
        return self.exists(filepath)
    
    def get_fallback_intro(self) -> Optional[Path]:
        """
        Get a safe fallback generic intro (always available).
        
        Returns:
            Path to fallback intro, or None if no fallback exists
        """
        # Try to get any generic intro
        generic = self.get_generic_intro()
        if generic:
            return generic
        
        # Fallback: return path that should exist (even if not generated yet)
        fallback = self.generic_intros_root / "generic_intro_001.mp3"
        logger.warning(f"[CACHE] Using fallback intro path: {fallback}")
        return fallback
    
    def get_fallback_outro(self) -> Optional[Path]:
        """
        Get a safe fallback generic outro (always available).
        
        Returns:
            Path to fallback outro, or None if no fallback exists
        """
        # Try to get any generic outro
        generic = self.get_generic_outro()
        if generic:
            return generic
        
        # Fallback: return path that should exist (even if not generated yet)
        fallback = self.generic_outros_root / "generic_outro_001.mp3"
        logger.warning(f"[CACHE] Using fallback outro path: {fallback}")
        return fallback
    
    # ===== Generation Functions (Called by Ticklers) =====
    # These are instant stubs - ElevenLabs will slot in here later
    
    def generate_intro(self, song_id: str) -> Path:
        """
        Generate an intro for a song (instant stub).
        
        Called by ticklers. Creates a personality intro for the song.
        This is an instant stub - ElevenLabs integration will slot in here later.
        
        Args:
            song_id: Filepath or ID of the song
            
        Returns:
            Path to generated intro file
        """
        song_name = Path(song_id).stem
        intro_path = self.personality_intros_root / f"{song_name}_intro.mp3"
        
        logger.info(f"[CACHE] [STUB] Generating intro for: {song_id}")
        logger.info(f"[CACHE] [STUB] → Intro path: {intro_path}")
        
        # Instant stub: just register the file as existing
        self._register_file(intro_path)
        
        logger.info(f"[CACHE] ✓ Intro 'generated' (stub): {intro_path}")
        return intro_path
    
    def generate_outro(self, song_id: str) -> Path:
        """
        Generate an outro for a song (instant stub).
        
        Called by ticklers. Creates a personality outro for the song.
        This is an instant stub - ElevenLabs integration will slot in here later.
        
        Args:
            song_id: Filepath or ID of the song
            
        Returns:
            Path to generated outro file
        """
        song_name = Path(song_id).stem
        outro_path = self.personality_outros_root / f"{song_name}_outro.mp3"
        
        logger.info(f"[CACHE] [STUB] Generating outro for: {song_id}")
        logger.info(f"[CACHE] [STUB] → Outro path: {outro_path}")
        
        # Instant stub: just register the file as existing
        self._register_file(outro_path)
        
        logger.info(f"[CACHE] ✓ Outro 'generated' (stub): {outro_path}")
        return outro_path
    
    def refill_generic_intros(self, count: int = 5) -> List[Path]:
        """
        Refill generic intro pool (instant stub).
        
        Called by ticklers. Generates multiple generic intros.
        This is an instant stub - ElevenLabs integration will slot in here later.
        
        Args:
            count: Number of generic intros to generate
            
        Returns:
            List of paths to generated generic intro files
        """
        logger.info(f"[CACHE] [STUB] Refilling generic intro pool ({count} intros)")
        
        generated_paths = []
        
        # Find next available slot
        existing = self.list_available_generic_intros()
        existing_numbers = set()
        for path in existing:
            # Extract number from filename like "generic_intro_001.mp3"
            try:
                parts = path.stem.split("_")
                if len(parts) >= 3 and parts[2].isdigit():
                    existing_numbers.add(int(parts[2]))
            except:
                pass
        
        next_number = 1
        while next_number in existing_numbers:
            next_number += 1
        
        # Generate count new generic intros
        for i in range(count):
            intro_number = next_number + i
            intro_path = self.generic_intros_root / f"generic_intro_{intro_number:03d}.mp3"
            
            logger.info(f"[CACHE] [STUB] → Generating generic intro {i+1}/{count}: {intro_path}")
            
            # Instant stub: just register the file as existing
            self._register_file(intro_path)
            generated_paths.append(intro_path)
        
        logger.info(f"[CACHE] ✓ Generic intro pool refilled: {len(generated_paths)} intros")
        return generated_paths
    
    def refresh_registry(self) -> None:
        """
        Refresh the file registry by rescanning cache directories.
        
        Useful after external changes to the cache.
        """
        self._scan_existing_files()
        logger.debug(f"[CACHE] Registry refreshed: {len(self._file_registry)} files")
