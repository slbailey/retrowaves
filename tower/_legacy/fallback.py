"""
Fallback PCM tone generator for Retrowaves Tower.

Generates continuous sine wave PCM audio in the canonical format.
"""

import math
import numpy as np
from typing import Iterator

from tower.config import TowerConfig


class ToneGenerator:
    """
    Generates continuous PCM tone frames.
    
    Produces sine wave audio at the configured frequency in the canonical
    PCM format: s16le, 48kHz, stereo, 1024 samples per frame.
    """
    
    def __init__(self, config: TowerConfig):
        """
        Initialize tone generator.
        
        Args:
            config: Tower configuration
        """
        self.config = config
        self.sample_rate = config.sample_rate
        self.channels = config.channels
        self.frame_size = config.frame_size
        self.frequency = config.tone_frequency
        
        # Pre-calculate frame period for real-time generation
        self.frame_period = self.frame_size / self.sample_rate  # ~21.3 ms
        
        # Phase accumulator for continuous tone generation
        self.phase = 0.0
        self.phase_increment = 2.0 * math.pi * self.frequency / self.sample_rate
    
    def generate_frame(self) -> bytes:
        """
        Generate a single PCM frame.
        
        Returns:
            bytes: PCM frame data (4096 bytes for 1024 samples × 2 channels × 2 bytes)
        """
        # Generate sample indices for this frame
        sample_indices = np.arange(self.frame_size) + (self.phase / self.phase_increment)
        
        # Generate sine wave samples
        samples = np.sin(self.phase_increment * np.arange(self.frame_size) + self.phase)
        
        # Update phase for next frame (continuous tone)
        self.phase += self.phase_increment * self.frame_size
        # Wrap phase to prevent overflow
        self.phase = self.phase % (2.0 * math.pi)
        
        # Scale to int16 range (-32768 to 32767)
        # Use 0.8 amplitude to avoid clipping
        samples_int16 = (samples * 0.8 * 32767).astype(np.int16)
        
        # Interleave for stereo (L, R, L, R, ...)
        stereo_samples = np.empty(self.frame_size * self.channels, dtype=np.int16)
        stereo_samples[0::2] = samples_int16  # Left channel
        stereo_samples[1::2] = samples_int16  # Right channel (same as left for mono tone)
        
        # Convert to bytes (little-endian, as required by s16le)
        return stereo_samples.tobytes()
    
    def frames(self) -> Iterator[bytes]:
        """
        Generate continuous PCM frames.
        
        Yields:
            bytes: PCM frame data
        """
        while True:
            yield self.generate_frame()

