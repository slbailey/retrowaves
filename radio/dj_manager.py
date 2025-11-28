import logging
import os
from typing import List, Literal
from .constants import MAX_INTRO_FILES, MAX_OUTRO_FILES

logger = logging.getLogger(__name__)

class DJManager:
    """Manages DJ intro and outro files for songs."""
    
    def __init__(self, dj_path: str, cache_ttl: float = 5.0):
        """
        Initialize the DJ manager.
        
        Args:
            dj_path: Path to the DJ files directory
            cache_ttl: Time to live for directory cache in seconds (default: 5)
                      Lower TTL ensures new files are detected quickly
        """
        self.dj_path = dj_path
        self.cache_ttl = cache_ttl
        self._available_files: set[str] = set()
        self._cache_timestamp: float = 0.0
        self._cache_mtime: float = 0.0
    
    def _get_directory_mtime(self) -> float:
        """Get directory modification time."""
        try:
            return os.path.getmtime(self.dj_path)
        except OSError:
            return 0.0
    
    def _get_available_files(self) -> set[str]:
        """Get cached list of available files in DJ directory."""
        import time
        current_time = time.time()
        current_mtime = self._get_directory_mtime()
        
        if not os.path.exists(self.dj_path):
            return set()
        
        # Refresh cache if expired or directory modified
        if (current_time - self._cache_timestamp > self.cache_ttl or 
            current_mtime != self._cache_mtime):
            try:
                self._available_files = set(os.listdir(self.dj_path))
                self._cache_timestamp = current_time
                self._cache_mtime = current_mtime
                logger.debug(f"Refreshed DJ file list: {len(self._available_files)} files")
            except OSError as e:
                logger.error(f"Error reading DJ directory {self.dj_path}: {e}")
                return set()
        
        return self._available_files
    
    def invalidate_cache(self) -> None:
        """Force refresh of DJ file cache on next access."""
        self._cache_timestamp = 0.0
        self._cache_mtime = 0.0
    
    def _check_dj_files(self, mp3_file: str, file_type: Literal['intro', 'outro']) -> List[str]:
        """
        Check for existing intro or outro files for a given MP3 file.
        
        Args:
            mp3_file: Name of the MP3 file (e.g., "song.mp3")
            file_type: Either 'intro' or 'outro'
            
        Returns:
            List of file names that exist
        """
        available_files = self._get_available_files()
        if not available_files:
            return []
        
        base_name = mp3_file.rsplit('.', 1)[0]  # Remove extension
        max_files = MAX_INTRO_FILES if file_type == 'intro' else MAX_OUTRO_FILES
        
        # Generate possible file names
        possible_files = [f"{base_name}_{file_type}{i}.mp3" for i in range(1, max_files + 1)]
        possible_files.append(f"{base_name}_{file_type}.mp3")
        
        # Find files that actually exist
        found_files = [f for f in possible_files if f in available_files]
        
        if found_files:
            logger.debug(f"Found {len(found_files)} {file_type} file(s) for {mp3_file}")
        
        return found_files
    
    def check_intro_files(self, mp3_file: str) -> List[str]:
        """
        Check for existing intro files for a given MP3 file.
        
        Args:
            mp3_file: Name of the MP3 file (e.g., "song.mp3")
            
        Returns:
            List of intro file names that exist
        """
        return self._check_dj_files(mp3_file, 'intro')

    def check_outro_files(self, mp3_file: str) -> List[str]:
        """
        Check for existing outro files for a given MP3 file.
        
        Args:
            mp3_file: Name of the MP3 file (e.g., "song.mp3")
            
        Returns:
            List of outro file names that exist
        """
        return self._check_dj_files(mp3_file, 'outro')
