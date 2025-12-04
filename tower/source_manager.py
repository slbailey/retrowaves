"""
SourceManager for Retrowaves Tower.

Thread-safe management of audio sources with switching capability.
"""

import logging
import threading
from pathlib import Path
from typing import Optional

from tower.config import TowerConfig
from tower.sources import Source, SourceMode, ToneSource, SilenceSource, FileSource

logger = logging.getLogger(__name__)


class SourceManager:
    """
    Thread-safe manager for audio sources.
    
    Manages current source mode and active Source instance.
    Provides thread-safe source switching.
    """
    
    def __init__(self, config: TowerConfig, default_mode: Optional[SourceMode] = None, default_file_path: Optional[str] = None):
        """
        Initialize source manager.
        
        Args:
            config: Tower configuration
            default_mode: Default source mode (defaults to SourceMode.TONE)
            default_file_path: Default file path for FILE mode (required if default_mode is FILE)
            
        Raises:
            ValueError: If default_mode is FILE but default_file_path is not provided or invalid
            FileNotFoundError: If default_file_path does not exist
        """
        self.config = config
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        
        # Current state
        self._current_mode: SourceMode = SourceMode.TONE
        self._current_source: Optional[Source] = None
        self._current_file_path: Optional[str] = None
        
        # Initialize with default source
        if default_mode is None:
            default_mode = SourceMode.TONE
        
        self._switch_source_internal(default_mode, default_file_path)
        logger.info(f"SourceManager initialized with mode: {self._current_mode.value}")
    
    def get_current_mode(self) -> SourceMode:
        """
        Get current source mode.
        
        Returns:
            SourceMode: Current source mode
        """
        with self._lock:
            return self._current_mode
    
    def get_current_file_path(self) -> Optional[str]:
        """
        Get current file path (if mode is FILE).
        
        Returns:
            Optional[str]: Current file path or None
        """
        with self._lock:
            return self._current_file_path
    
    def get_current_source(self) -> Source:
        """
        Get current source instance.
        
        Thread-safe. Returns the current source, which may change
        between calls if switching occurs.
        
        Returns:
            Source: Current source instance
        """
        with self._lock:
            if self._current_source is None:
                # Fallback to tone if source is None (shouldn't happen)
                logger.warning("Current source is None, falling back to tone")
                self._switch_source_internal(SourceMode.TONE, None)
            return self._current_source
    
    def switch_source(self, mode: SourceMode, file_path: Optional[str] = None) -> None:
        """
        Switch to a new source.
        
        Thread-safe. Switches source atomically.
        Minimal audio glitches may occur during switch.
        
        Args:
            mode: Target source mode
            file_path: File path for FILE mode (required if mode is FILE)
            
        Raises:
            ValueError: If mode is FILE but file_path is not provided or invalid
            FileNotFoundError: If file_path does not exist
        """
        with self._lock:
            self._switch_source_internal(mode, file_path)
    
    def _switch_source_internal(self, mode: SourceMode, file_path: Optional[str] = None) -> None:
        """
        Internal source switching (must be called with lock held).
        
        Args:
            mode: Target source mode
            file_path: File path for FILE mode (required if mode is FILE)
            
        Raises:
            ValueError: If mode is FILE but file_path is not provided or invalid
            FileNotFoundError: If file_path does not exist
        """
        # Validate file_path for FILE mode
        if mode == SourceMode.FILE:
            if not file_path:
                raise ValueError("file_path is required for FILE mode")
            if not Path(file_path).exists():
                raise FileNotFoundError(f"WAV file not found: {file_path}")
        elif file_path is not None:
            raise ValueError(f"file_path should not be provided for mode {mode.value}")
        
        # Clean up old source
        old_source = self._current_source
        if old_source:
            try:
                old_source.cleanup()
            except Exception as e:
                logger.warning(f"Error cleaning up old source: {e}")
        
        # Create new source
        try:
            if mode == SourceMode.TONE:
                new_source = ToneSource(self.config)
                new_file_path = None
            elif mode == SourceMode.SILENCE:
                new_source = SilenceSource(self.config)
                new_file_path = None
            elif mode == SourceMode.FILE:
                new_source = FileSource(self.config, file_path)
                new_file_path = file_path
            else:
                raise ValueError(f"Unknown source mode: {mode}")
            
            # Update state atomically
            self._current_mode = mode
            self._current_source = new_source
            self._current_file_path = new_file_path
            
            logger.info(f"Switched to source mode: {mode.value}" + (f" (file: {file_path})" if file_path else ""))
            
        except Exception as e:
            logger.error(f"Failed to switch source to {mode.value}: {e}")
            # Keep old source if switch failed
            if old_source:
                self._current_source = old_source
            raise
    
    def cleanup(self) -> None:
        """Clean up all resources."""
        with self._lock:
            if self._current_source:
                try:
                    self._current_source.cleanup()
                except Exception as e:
                    logger.warning(f"Error cleaning up source: {e}")
                self._current_source = None

