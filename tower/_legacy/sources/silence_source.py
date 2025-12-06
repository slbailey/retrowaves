"""
SilenceSource for Retrowaves Tower.

Generates continuous PCM frames containing all zeros.
"""

import numpy as np

from tower.config import TowerConfig
from tower.sources.base import Source


class SilenceSource(Source):
    """
    Generates continuous PCM frames containing all zeros.
    
    Produces frames in canonical format: s16le, 48kHz, stereo, 1024 samples per frame.
    """
    
    def __init__(self, config: TowerConfig):
        """
        Initialize silence source.
        
        Args:
            config: Tower configuration
        """
        self.config = config
        self.frame_size = config.frame_size
        self.channels = config.channels
        
        # Pre-allocate zero frame for efficiency
        # 4096 bytes = 1024 samples × 2 channels × 2 bytes per sample
        self._zero_frame = np.zeros(
            self.frame_size * self.channels,
            dtype=np.int16
        ).tobytes()
    
    def generate_frame(self) -> bytes:
        """
        Generate a single PCM frame containing all zeros.
        
        Returns:
            bytes: PCM frame data (4096 bytes, all zeros)
        """
        return self._zero_frame

