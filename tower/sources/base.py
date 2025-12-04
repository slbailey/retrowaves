"""
Base Source interface for Retrowaves Tower.

All audio sources must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import Iterator


class Source(ABC):
    """
    Base class for audio sources.
    
    All sources must produce PCM frames in canonical format:
    - Format: s16le (signed 16-bit little-endian)
    - Sample rate: 48000 Hz
    - Channels: 2 (stereo)
    - Frame size: 1024 samples per frame
    - Frame bytes: exactly 4096 bytes per frame
    """
    
    @abstractmethod
    def generate_frame(self) -> bytes:
        """
        Generate a single PCM frame.
        
        Returns:
            bytes: PCM frame data (exactly 4096 bytes)
        """
        pass
    
    def frames(self) -> Iterator[bytes]:
        """
        Generate continuous PCM frames.
        
        Yields:
            bytes: PCM frame data (exactly 4096 bytes per frame)
        """
        while True:
            yield self.generate_frame()
    
    def cleanup(self) -> None:
        """
        Clean up resources (file handles, etc.).
        
        Called when source is no longer needed.
        Subclasses should override if cleanup is needed.
        """
        pass

