"""
FileSource for Retrowaves Tower.

Reads PCM data from WAV files with endless looping.
"""

import logging
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from tower.config import TowerConfig
from tower.sources.base import Source

logger = logging.getLogger(__name__)


class FileSource(Source):
    """
    Reads PCM data from a WAV file with endless looping.
    
    Supports WAV files matching canonical format:
    - Format: s16le (signed 16-bit little-endian)
    - Sample rate: 48000 Hz
    - Channels: 2 (stereo)
    
    Rejects WAV files that do not match canonical format.
    Minimal audio glitches at loop boundaries are acceptable.
    """
    
    def __init__(self, config: TowerConfig, file_path: str):
        """
        Initialize file source.
        
        Args:
            config: Tower configuration
            file_path: Path to WAV file
            
        Raises:
            FileNotFoundError: If file does not exist
            ValueError: If WAV file format does not match canonical format
        """
        self.config = config
        self.file_path = Path(file_path)
        self.frame_size = config.frame_size
        self.channels = config.channels
        self.sample_rate = config.sample_rate
        self.frame_bytes = config.frame_bytes
        
        # Validate file exists
        if not self.file_path.exists():
            raise FileNotFoundError(f"WAV file not found: {file_path}")
        
        # Open and validate WAV file
        self._wav_file: Optional[wave.Wave_read] = None
        self._wav_data: Optional[bytes] = None
        self._wav_position = 0
        
        self._load_wav_file()
    
    def _load_wav_file(self) -> None:
        """Load and validate WAV file."""
        try:
            wav = wave.open(str(self.file_path), 'rb')
            
            # Validate format matches canonical format
            if wav.getnchannels() != self.channels:
                wav.close()
                raise ValueError(
                    f"WAV file has {wav.getnchannels()} channels, "
                    f"expected {self.channels} (stereo)"
                )
            
            if wav.getframerate() != self.sample_rate:
                wav.close()
                raise ValueError(
                    f"WAV file has sample rate {wav.getframerate()} Hz, "
                    f"expected {self.sample_rate} Hz"
                )
            
            if wav.getsampwidth() != 2:  # s16le = 2 bytes per sample
                wav.close()
                raise ValueError(
                    f"WAV file has sample width {wav.getsampwidth()} bytes, "
                    f"expected 2 bytes (s16le)"
                )
            
            # Read all frames into memory for looping
            # This is acceptable for Phase 2 (files should be reasonably sized)
            self._wav_data = wav.readframes(wav.getnframes())
            wav.close()
            
            if not self._wav_data:
                raise ValueError(f"WAV file is empty: {self.file_path}")
            
            logger.info(f"Loaded WAV file: {self.file_path} ({len(self._wav_data)} bytes)")
            
        except wave.Error as e:
            raise ValueError(f"Invalid WAV file: {self.file_path}: {e}")
        except Exception as e:
            if isinstance(e, (FileNotFoundError, ValueError)):
                raise
            raise ValueError(f"Error loading WAV file: {self.file_path}: {e}")
    
    def generate_frame(self) -> bytes:
        """
        Generate a single PCM frame from WAV file.
        
        Returns:
            bytes: PCM frame data (exactly 4096 bytes)
        """
        if not self._wav_data:
            # Fallback to silence if WAV data is not available
            return np.zeros(self.frame_bytes, dtype=np.int16).tobytes()
        
        # Extract frame from WAV data
        frame_start = self._wav_position
        frame_end = frame_start + self.frame_bytes
        
        if frame_end <= len(self._wav_data):
            # Normal case: read frame from current position
            frame = self._wav_data[frame_start:frame_end]
            self._wav_position = frame_end
        else:
            # Loop case: need to wrap around
            # Read remaining data from current position
            remaining = len(self._wav_data) - frame_start
            frame_part1 = self._wav_data[frame_start:]
            
            # Read from beginning to complete frame
            needed = self.frame_bytes - remaining
            frame_part2 = self._wav_data[:needed]
            
            # Combine parts
            frame = frame_part1 + frame_part2
            self._wav_position = needed
            
            # Minimal glitches at loop boundaries are acceptable
        
        # Ensure frame is exactly frame_bytes
        if len(frame) < self.frame_bytes:
            # Pad with zeros if needed (shouldn't happen with valid WAV)
            frame += b'\x00' * (self.frame_bytes - len(frame))
        elif len(frame) > self.frame_bytes:
            # Truncate if needed (shouldn't happen)
            frame = frame[:self.frame_bytes]
        
        return frame
    
    def cleanup(self) -> None:
        """Clean up file resources."""
        if self._wav_file:
            try:
                self._wav_file.close()
            except Exception:
                pass
            self._wav_file = None
        self._wav_data = None

