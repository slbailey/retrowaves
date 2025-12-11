"""
Fallback audio generator for Tower.

This module provides FallbackGenerator, which generates continuous PCM frames
for use when live audio is not available. The generator supports multiple
fallback sources with priority: File (MP3/WAV) → Tone (440Hz) → Silence.
"""

from __future__ import annotations

import logging
import math
import os
import struct
from typing import Optional

from tower.fallback.file_source import FileSource

logger = logging.getLogger(__name__)


# Audio format constants
SAMPLE_RATE = 48000  # Hz
CHANNELS = 2  # Stereo
FRAME_SIZE_SAMPLES = 1024  # Samples per frame (PCM cadence)
BYTES_PER_SAMPLE = 2  # s16le = 2 bytes per sample
FRAME_SIZE_BYTES = FRAME_SIZE_SAMPLES * CHANNELS * BYTES_PER_SAMPLE  # 4096 bytes

# Tone generation constants
TONE_FREQUENCY = 440.0  # Hz (A4 note)
PHASE_INCREMENT = 2.0 * math.pi * TONE_FREQUENCY / SAMPLE_RATE  # Radians per sample

# Audio amplitude (s16le range: -32768 to 32767)
# Use 80% of max amplitude to avoid clipping
AMPLITUDE = int(32767 * 0.8)


class FallbackGenerator:
    """
    Generates continuous PCM fallback audio frames.
    
    Supports multiple fallback sources with priority order:
    1. File (MP3/WAV) - if TOWER_SILENCE_MP3_PATH is configured and file exists
    2. Tone (440Hz sine wave) - preferred fallback when file is unavailable
    3. Silence (zeros) - last resort if tone generation fails
    
    Per contract FP3: Priority order is File → Tone → Silence.
    
    Attributes:
        _file_source: Optional FileSource instance for file-based fallback
        _phase: Current phase in radians (for continuous waveform)
        _use_tone: Whether to generate tone (False = silence)
    """
    
    def __init__(self) -> None:
        """
        Initialize fallback generator.
        
        Checks for TOWER_SILENCE_MP3_PATH environment variable and attempts
        to create FileSource if path is set and file exists. Falls back to
        tone generation if file source is unavailable.
        """
        self._file_source: Optional[FileSource] = None
        self._phase: float = 0.0  # Phase accumulator (radians)
        self._use_tone: bool = True  # Try tone generation if file unavailable
        self._file_source_unavailable_count = 0  # Track consecutive unavailable checks
        
        # Per contract FP3.1: Try file-based fallback first
        file_path = os.getenv("TOWER_SILENCE_MP3_PATH")
        if file_path:
            try:
                self._file_source = FileSource(file_path)
                logger.info(f"FallbackGenerator initialized with file source: {file_path}")
                # File source available - don't use tone
                self._use_tone = False
            except Exception as e:
                logger.warning(f"File fallback unavailable ({file_path}), using tone: {e}")
                # File source failed - fall back to tone
                self._file_source = None
                self._use_tone = True
        else:
            logger.debug("TOWER_SILENCE_MP3_PATH not set, using tone fallback")
        
        # Validate constants for tone generation
        if self._use_tone:
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
        
        Per contract FP3: Priority order is File → Tone → Silence.
        
        Returns:
            bytes: PCM frame (4096 bytes for 1024 samples × 2 channels × 2 bytes)
                  Format: s16le, stereo, 48000Hz
                  
        Fallback Priority:
        1. File (MP3/WAV) - if TOWER_SILENCE_MP3_PATH is configured and available
        2. Tone (440Hz sine wave) - if file unavailable and tone generation succeeds
        3. Silence (zeros) - last resort if both file and tone fail
        """
        # Per contract FP3.1: Try file source first
        if self._file_source is not None:
            try:
                # Check if file source is actually producing frames BEFORE getting frame
                if not self._file_source.is_available():
                    # File source buffer is temporarily empty
                    # This should be rare with proper buffering, but can happen during startup
                    # or if FFmpeg is slow. Give it many chances before disabling.
                    self._file_source_unavailable_count += 1
                    
                    # Only disable after many consecutive unavailable checks
                    # With larger buffer, this should rarely happen
                    if self._file_source_unavailable_count > 100:  # ~2 seconds at 21.333ms per tick
                        logger.warning(f"File source not producing frames after {self._file_source_unavailable_count} checks, disabling and falling back to tone")
                        try:
                            self._file_source.close()
                        except Exception:
                            pass
                        self._file_source = None
                        self._use_tone = True
                        # Fall through to tone (don't return here, let tone handle it)
                    else:
                        # Buffer temporarily empty - this is a problem but don't spam logs
                        if self._file_source_unavailable_count % 10 == 0:  # Log every 10th occurrence
                            logger.debug(f"File source buffer temporarily empty (count={self._file_source_unavailable_count}), using tone temporarily")
                        # Fall through to tone for this tick
                else:
                    # File source is available (has frames pre-decoded) - get frame
                    self._file_source_unavailable_count = 0  # Reset counter on success
                    frame = self._file_source.next_frame()
                    
                    # With the new pre-decoded implementation, if FileSource is available
                    # and returns a frame, it's always valid (pre-decoded at startup).
                    # Silence frames are legitimate audio content, not errors.
                    # The is_available() check above is sufficient to determine if
                    # FileSource is working.
                    return frame
            except Exception as e:
                logger.warning(f"File source failed, falling back to tone: {e}")
                # File source failed - try to restart or fall back to tone
                try:
                    self._file_source.close()
                except Exception:
                    pass
                self._file_source = None
                self._use_tone = True
                # Fall through to tone
        
        # Per contract FP3.2: Try tone generator if file unavailable
        if self._use_tone:
            try:
                frame = self._generate_tone_frame()
                logger.debug(f"[GEN] Tone frame {len(frame)}")
                return frame
            except Exception as e:
                logger.warning(f"Tone generation failed, falling back to silence: {e}")
                self._use_tone = False
                # Fall through to silence
        
        # Per contract FP3.3: Last resort - silence
        frame = self._generate_silence_frame()
        logger.debug(f"[GEN] Silence frame {len(frame)}")
        return frame
    
    def next_frame(self) -> bytes:
        """
        Get next PCM frame per contract FP4.
        
        Per contract FP4: FallbackProvider MUST expose next_frame() -> bytes.
        This method delegates to get_frame() for backwards compatibility.
        
        Returns:
            bytes: PCM frame (4096 bytes) per contract FP2.1, FP4.1
        """
        return self.get_frame()
    
    def _generate_tone_frame(self) -> bytes:
        """
        Generate one frame of 440Hz sine tone.
        
        Maintains phase continuity across frames by updating the persistent phase
        accumulator once per frame (by step * 1024) rather than per sample.
        
        Returns:
            bytes: PCM frame with sine wave data
        """
        frame_data = bytearray(FRAME_SIZE_BYTES)
        
        # Use local phase variable starting from persistent phase accumulator
        # This ensures continuity: the persistent phase is only updated once per frame
        local_phase = self._phase
        
        # Generate samples using local phase (incremented per sample)
        for i in range(FRAME_SIZE_SAMPLES):
            # Calculate sample value from current local phase
            sample_value = int(AMPLITUDE * math.sin(local_phase))
            
            # Pack as s16le (signed 16-bit little-endian)
            # Write to both left and right channels (stereo)
            sample_bytes = struct.pack('<h', sample_value)  # '<h' = little-endian signed short
            
            # Write to left channel
            offset = i * CHANNELS * BYTES_PER_SAMPLE
            frame_data[offset:offset + BYTES_PER_SAMPLE] = sample_bytes
            
            # Write to right channel (same value for stereo)
            frame_data[offset + BYTES_PER_SAMPLE:offset + BYTES_PER_SAMPLE * 2] = sample_bytes
            
            # Advance local phase for next sample
            local_phase += PHASE_INCREMENT
        
        # Update persistent phase accumulator once per frame (by step * 1024)
        # This maintains phase continuity across frame boundaries
        PHASE_INCREMENT_PER_FRAME = PHASE_INCREMENT * FRAME_SIZE_SAMPLES
        self._phase += PHASE_INCREMENT_PER_FRAME
        
        # Wrap phase to prevent overflow (keep in [0, 2π) range)
        # Use modulo for numerically stable wrapping
        self._phase = self._phase % (2.0 * math.pi)
        
        return bytes(frame_data)
    
    def _generate_silence_frame(self) -> bytes:
        """
        Generate one frame of silence (zeros).
        
        Per contract FP3.3: Silence is the last resort fallback.
        
        Returns:
            bytes: PCM frame filled with zeros
        """
        return b'\x00' * FRAME_SIZE_BYTES
    
    def close(self) -> None:
        """
        Clean up resources.
        
        Closes file source if it exists. Safe to call multiple times.
        """
        if self._file_source is not None:
            try:
                self._file_source.close()
            except Exception as e:
                logger.warning(f"Error closing file source: {e}")
            self._file_source = None

