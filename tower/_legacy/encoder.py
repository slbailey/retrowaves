"""
FFmpeg encoder wrapper for Retrowaves Tower.

Manages FFmpeg subprocess with stdin/stdout pipes for PCM-to-MP3 encoding.
"""

import os
import subprocess
import logging
from typing import Optional, BinaryIO

from tower.config import TowerConfig


logger = logging.getLogger(__name__)


class Encoder:
    """
    FFmpeg encoder process wrapper.
    
    Launches FFmpeg with the canonical command and provides access to
    stdin (for PCM input) and stdout (for MP3 output).
    """
    
    def __init__(self, config: TowerConfig):
        """
        Initialize encoder (does not start FFmpeg yet).
        
        Args:
            config: Tower configuration
        """
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.stdin: Optional[BinaryIO] = None
        self.stdout: Optional[BinaryIO] = None
    
    def start(self) -> None:
        """
        Start FFmpeg encoder process.
        
        Raises:
            RuntimeError: If FFmpeg fails to start
        """
        if self.process is not None:
            raise RuntimeError("Encoder already started")
        
        # Canonical FFmpeg command
        cmd = [
            "ffmpeg",
            "-f", "s16le",           # Input format: signed 16-bit little-endian PCM
            "-ar", str(self.config.sample_rate),  # Sample rate: 48000 Hz
            "-ac", str(self.config.channels),    # Channels: 2 (stereo)
            "-i", "pipe:0",          # Input from stdin
            "-f", "mp3",              # Output format: MP3
            "-b:a", self.config.bitrate,  # Bitrate: 128k
            "-acodec", "libmp3lame",  # MP3 encoder: LAME
            "pipe:1"                  # Output to stdout
        ]
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0  # Unbuffered for real-time streaming
            )
            self.stdin = self.process.stdin
            self.stdout = self.process.stdout
            
            # CRITICAL: Set stdin to non-blocking mode for fire-and-forget writes
            # Tower must never wait for FFmpeg - only fire-and-forget PCM frames
            # This ensures AudioPump timing remains intact even if FFmpeg buffer fills
            try:
                # Python 3.7+ has os.set_blocking()
                if hasattr(os, 'set_blocking'):
                    os.set_blocking(self.stdin.fileno(), False)
                else:
                    # Fallback for older Python: use fcntl (Unix only)
                    import fcntl
                    flags = fcntl.fcntl(self.stdin.fileno(), fcntl.F_GETFL)
                    fcntl.fcntl(self.stdin.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)
                logger.debug("Encoder stdin set to non-blocking mode")
            except (OSError, AttributeError, ImportError) as e:
                # If setting non-blocking fails (e.g., Windows), log warning but continue
                # On Windows, subprocess pipes may not support non-blocking mode
                logger.warning(f"Could not set encoder stdin to non-blocking: {e}. "
                             "Writes may block briefly on some systems.")
            
            # Note: stdout is left in blocking mode
            # A dedicated drain thread continuously reads from stdout and pushes to a queue
            # This prevents stdout reads from blocking the broadcast loop
            # Architecture: FFmpeg stdout → drain thread → MP3 queue → get_chunk() → HTTP clients
            
            logger.info("FFmpeg encoder started")
        except FileNotFoundError:
            raise RuntimeError("FFmpeg not found. Please install FFmpeg.")
        except Exception as e:
            raise RuntimeError(f"Failed to start FFmpeg: {e}")
    
    def is_running(self) -> bool:
        """
        Check if encoder process is running.
        
        Returns:
            bool: True if process is running, False otherwise
        """
        if self.process is None:
            return False
        return self.process.poll() is None
    
    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop FFmpeg encoder process.
        
        Args:
            timeout: Maximum time to wait for process to terminate
        """
        if self.process is None:
            return
        
        # Close stdin to signal EOF
        if self.stdin:
            try:
                self.stdin.close()
            except Exception:
                pass
        
        # Wait for process to terminate
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Force kill if it doesn't terminate
            logger.warning("FFmpeg did not terminate gracefully, forcing kill")
            self.process.kill()
            self.process.wait()
        
        # Close stdout
        if self.stdout:
            try:
                self.stdout.close()
            except Exception:
                pass
        
        self.process = None
        self.stdin = None
        self.stdout = None
        
        logger.info("FFmpeg encoder stopped")

