"""
Fallback audio generator for Tower.

This module provides FallbackGenerator, which generates continuous PCM frames
for use when live audio is not available. The generator produces a 440Hz sine
tone, with silence as a fallback if tone generation fails.
"""

from __future__ import annotations

import logging
import math
import struct
from typing import Optional

logger = logging.getLogger(__name__)


# Audio format constants
SAMPLE_RATE = 48000  # Hz
CHANNELS = 2  # Stereo
FRAME_SIZE_SAMPLES = 1152  # Samples per frame (MP3 frame size)
BYTES_PER_SAMPLE = 2  # s16le = 2 bytes per sample
FRAME_SIZE_BYTES = FRAME_SIZE_SAMPLES * CHANNELS * BYTES_PER_SAMPLE  # 4608 bytes

# Tone generation constants
TONE_FREQUENCY = 440.0  # Hz (A4 note)
PHASE_INCREMENT = 2.0 * math.pi * TONE_FREQUENCY / SAMPLE_RATE  # Radians per sample

# Audio amplitude (s16le range: -32768 to 32767)
# Use 80% of max amplitude to avoid clipping
AMPLITUDE = int(32767 * 0.8)


class FallbackGenerator:
    """
    Generates continuous PCM fallback audio frames.
    
    Produces a 440Hz sine tone in s16le stereo format at 48kHz.
    Uses a phase accumulator to ensure continuous waveform without pops.
    Falls back to silence if tone generation fails.
    
    Fallback Priority:
    1. Tone (440Hz sine wave)
    2. Silence (zeros) - only if tone generation fails
    
    Attributes:
        _phase: Current phase in radians (for continuous waveform)
        _use_tone: Whether to generate tone (False = silence)
    """
    
    def __init__(self) -> None:
        """
        Initialize fallback generator.
        
        Attempts to initialize tone generation. If initialization fails,
        falls back to silence mode.
        """
        self._phase: float = 0.0  # Phase accumulator (radians)
        self._use_tone: bool = True  # Try tone generation first
        
        # Validate constants
        try:
            # Verify frame size calculation
            expected_bytes = FRAME_SIZE_SAMPLES * CHANNELS * BYTES_PER_SAMPLE
            if expected_bytes != FRAME_SIZE_BYTES:
                raise ValueError(f"Frame size mismatch: {expected_bytes} != {FRAME_SIZE_BYTES}")
            
            # Verify phase increment is valid
            if not (0 < PHASE_INCREMENT < math.pi):
                raise ValueError(f"Invalid phase increment: {PHASE_INCREMENT}")
            
            logger.info(
                f"FallbackGenerator initialized: {TONE_FREQUENCY}Hz tone, "
                f"{FRAME_SIZE_SAMPLES} samples/frame, {FRAME_SIZE_BYTES} bytes/frame"
            )
        except Exception as e:
            logger.warning(f"FallbackGenerator initialization error, using silence: {e}")
            self._use_tone = False
    
    def get_frame(self) -> bytes:
        """
        Generate one PCM frame.
        
        Returns:
            bytes: PCM frame (4608 bytes for 1152 samples × 2 channels × 2 bytes)
                  Format: s16le, stereo, 48000Hz
                  
        Fallback Priority:
        1. Tone (440Hz sine wave) - if tone generation succeeds
        2. Silence (zeros) - if tone generation fails
        
        Uses phase accumulator to ensure continuous waveform without pops.
        """
        if self._use_tone:
            try:
                frame = self._generate_tone_frame()
                logger.debug(f"[GEN] Tone frame {len(frame)}")
                return frame
            except Exception as e:
                logger.warning(f"Tone generation failed, falling back to silence: {e}")
                self._use_tone = False
                # Fall through to silence
        
        # Generate silence frame
        frame = self._generate_silence_frame()
        logger.debug(f"[GEN] Tone frame {len(frame)}")
        return frame
    
    def _generate_tone_frame(self) -> bytes:
        """
        Generate one frame of 440Hz sine tone.
        
        Returns:
            bytes: PCM frame with sine wave data
        """
        frame_data = bytearray(FRAME_SIZE_BYTES)
        
        # Generate samples using phase accumulator
        for i in range(FRAME_SIZE_SAMPLES):
            # Calculate sample value from current phase
            sample_value = int(AMPLITUDE * math.sin(self._phase))
            
            # Pack as s16le (signed 16-bit little-endian)
            # Write to both left and right channels (stereo)
            sample_bytes = struct.pack('<h', sample_value)  # '<h' = little-endian signed short
            
            # Write to left channel
            offset = i * CHANNELS * BYTES_PER_SAMPLE
            frame_data[offset:offset + BYTES_PER_SAMPLE] = sample_bytes
            
            # Write to right channel (same value for stereo)
            frame_data[offset + BYTES_PER_SAMPLE:offset + BYTES_PER_SAMPLE * 2] = sample_bytes
            
            # Advance phase accumulator
            self._phase += PHASE_INCREMENT
            
            # Wrap phase to prevent overflow (keep in [0, 2π) range)
            if self._phase >= 2.0 * math.pi:
                self._phase -= 2.0 * math.pi
        
        return bytes(frame_data)
    
    def _generate_silence_frame(self) -> bytes:
        """
        Generate one frame of silence (zeros).
        
        Returns:
            bytes: PCM frame filled with zeros
        """
        return b'\x00' * FRAME_SIZE_BYTES

