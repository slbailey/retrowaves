"""
Helper to generate silent MP3 frames for FAILED encoder state.
"""

import logging
from pathlib import Path
import subprocess

logger = logging.getLogger(__name__)


def generate_silent_mp3_chunk(config, chunk_size: int = 8192) -> bytes:
    """
    Generate a silent MP3 chunk.
    
    If TOWER_SILENCE_MP3_PATH is configured, reads from that file.
    Otherwise, generates silence using FFmpeg.
    
    Args:
        config: TowerConfig instance
        chunk_size: Desired chunk size in bytes
        
    Returns:
        bytes: Silent MP3 data
    """
    # If silence MP3 path is configured, use that file
    if config.silence_mp3_path:
        try:
            silence_path = Path(config.silence_mp3_path)
            if not silence_path.exists():
                logger.warning(f"Silence MP3 path does not exist: {config.silence_mp3_path}, generating internally")
            else:
                with open(silence_path, "rb") as f:
                    data = f.read(chunk_size)
                    if len(data) >= chunk_size:
                        return data[:chunk_size]
                    # If file is smaller than chunk_size, pad with zeros
                    return data + b'\x00' * (chunk_size - len(data))
        except Exception as e:
            logger.warning(f"Error reading silence MP3 from {config.silence_mp3_path}: {e}, generating internally")
    
    # Generate silence using FFmpeg
    try:
        # Use FFmpeg to generate silent MP3
        # Generate enough silence to fill the chunk
        # At 128kbps, 8192 bytes ≈ 0.5 seconds of audio
        duration_seconds = (chunk_size * 8) / (128 * 1000)  # Rough estimate
        
        cmd = [
            "ffmpeg",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t", str(duration_seconds),
            "-f", "mp3",
            "-b:a", config.bitrate,
            "-acodec", "libmp3lame",
            "pipe:1"
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        
        output, stderr = process.communicate(timeout=5.0)
        
        if process.returncode != 0:
            logger.warning(f"Failed to generate silent MP3: {stderr.decode()}")
            # Fallback: return minimal MP3 header
            return _minimal_mp3_header()
        
        if len(output) < chunk_size:
            # Pad with zeros if needed (MP3 decoder will handle it)
            output += b'\x00' * (chunk_size - len(output))
        
        return output[:chunk_size]
        
    except Exception as e:
        logger.warning(f"Error generating silent MP3: {e}")
        # Fallback: return minimal MP3 header
        return _minimal_mp3_header()


def _minimal_mp3_header() -> bytes:
    """
    Generate a minimal MP3 frame header for silence.
    
    This is a fallback if FFmpeg fails.
    """
    # Minimal MP3 sync frame (11 bytes header + some data)
    # This is a very basic MP3 frame that decoders can handle
    header = bytes([
        0xFF, 0xFB, 0x94, 0x00,  # MP3 sync + header
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00
    ])
    
    # Pad to reasonable size
    return header + b'\x00' * (8192 - len(header))

