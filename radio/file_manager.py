"""File management utilities for reading music directories."""

import logging
import os
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

class FileManager:
    """Manages file operations for music directories."""
    
    def __init__(self, cache_ttl: float = 5.0):
        """
        Initialize the file manager.
        
        Args:
            cache_ttl: Time to live for directory cache in seconds (default: 5)
                      Lower TTL ensures new files are detected quickly
        """
        self.cache_ttl = cache_ttl
        # Cache: path -> (files, timestamp, dir_mtime)
        # dir_mtime tracks directory modification time to detect new files
        self._cache: dict[str, tuple[List[str], float, float]] = {}
    
    def _get_directory_mtime(self, directory: str) -> float:
        """
        Get directory modification time.
        
        Args:
            directory: Path to directory
            
        Returns:
            Modification time, or 0 if directory doesn't exist
        """
        try:
            return os.path.getmtime(directory)
        except OSError:
            return 0.0
    
    def get_mp3_files(self, directory: str, use_cache: bool = True, force_refresh: bool = False) -> List[str]:
        """
        Get all MP3 files from a directory.
        
        Args:
            directory: Path to directory
            use_cache: Whether to use cached results (default: True)
            force_refresh: Force refresh even if cache is valid (default: False)
            
        Returns:
            List of MP3 filenames (not full paths)
        """
        if not os.path.exists(directory):
            logger.debug(f"Directory does not exist: {directory}")
            return []
        
        current_time = time.time()
        current_mtime = self._get_directory_mtime(directory)
        
        # Check cache
        if use_cache and not force_refresh and directory in self._cache:
            files, timestamp, cached_mtime = self._cache[directory]
            
            # Check if cache is still valid:
            # 1. Time hasn't expired
            # 2. Directory hasn't been modified (new files would change mtime)
            if (current_time - timestamp < self.cache_ttl and 
                cached_mtime == current_mtime):
                return files
        
        # Cache expired or directory modified - refresh
        try:
            files = [f for f in os.listdir(directory) if f.endswith('.mp3')]
            
            # Update cache with current mtime
            self._cache[directory] = (files, current_time, current_mtime)
            
            logger.debug(f"Refreshed file list for {directory}: {len(files)} MP3 files")
            return files
        except OSError as e:
            logger.error(f"Error reading directory {directory}: {e}")
            return []
    
    def clear_cache(self) -> None:
        """Clear the directory cache."""
        self._cache.clear()
    
    def invalidate_cache(self, directory: str) -> None:
        """Invalidate cache for a specific directory."""
        self._cache.pop(directory, None)
    
    def refresh_all(self) -> None:
        """Force refresh all cached directories on next access."""
        self.clear_cache()

