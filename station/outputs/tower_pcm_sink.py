"""
PCM Socket Sink for Retrowaves Station.

Connects to Tower's AudioInputRouter Unix socket and writes PCM frames continuously.
This replaces the internal HTTP streaming and MP3 encoding in Station.
"""

import logging
import os
import socket
import time
from typing import Optional

import numpy as np

from outputs.base_sink import BaseSink

logger = logging.getLogger(__name__)


class TowerPCMSink(BaseSink):
    """
    PCM socket sink that connects to Tower's Unix domain socket.
    
    Writes 1024-sample 16-bit PCM frames at 48kHz continuously to Tower.
    Architecture: PlayoutEngine → Mixer → TowerPCMSink → Tower Unix Socket
    """
    
    def __init__(self, socket_path: str = "/var/run/retrowaves/pcm.sock", 
                 sample_rate: int = 48000, channels: int = 2, frame_size: int = 1024):
        """
        Initialize Tower PCM sink.
        
        Args:
            socket_path: Path to Tower's Unix domain socket
            sample_rate: Audio sample rate (default: 48000)
            channels: Number of audio channels (default: 2)
            frame_size: Samples per frame (default: 1024)
        """
        self.socket_path = socket_path
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_size = frame_size
        self.frame_bytes = frame_size * channels * 2  # 1024 * 2 * 2 = 4096 bytes
        
        self._socket: Optional[socket.socket] = None
        self._connected = False
        self._reconnect_delay = 1.0  # Seconds to wait before reconnecting
        self._last_reconnect_attempt = 0.0
        
        logger.info(f"TowerPCMSink initialized (socket={socket_path})")
    
    def _connect(self) -> bool:
        """
        Connect to Tower's Unix socket.
        
        Returns:
            True if connected successfully, False otherwise
        """
        if self._connected and self._socket:
            return True
        
        # Rate limit reconnection attempts
        now = time.time()
        if now - self._last_reconnect_attempt < self._reconnect_delay:
            return False
        
        self._last_reconnect_attempt = now
        
        try:
            # Close existing socket if any
            if self._socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None
            
            # Create Unix domain socket
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            
            # Connect to Tower's socket
            sock.connect(self.socket_path)
            
            self._socket = sock
            self._connected = True
            logger.info(f"[TOWER] Connected to Tower socket: {self.socket_path}")
            return True
            
        except FileNotFoundError:
            logger.debug(f"[TOWER] Tower socket not found: {self.socket_path} (Tower may not be running)")
            return False
        except ConnectionRefusedError:
            logger.debug(f"[TOWER] Tower socket connection refused: {self.socket_path}")
            return False
        except OSError as e:
            logger.debug(f"[TOWER] Failed to connect to Tower socket: {e}")
            return False
        except Exception as e:
            logger.warning(f"[TOWER] Unexpected error connecting to Tower: {e}")
            return False
    
    def write(self, frame: np.ndarray) -> None:
        """
        Write PCM frame to Tower's Unix socket.
        
        Non-blocking: attempts to reconnect if disconnected.
        
        Args:
            frame: numpy array containing PCM audio data (must be 1024 samples, 2 channels, s16le)
        """
        # Ensure we're connected
        if not self._connected:
            if not self._connect():
                # Not connected and can't reconnect - drop frame silently
                return
        
        # Validate frame size
        expected_samples = self.frame_size * self.channels
        if frame.size != expected_samples:
            logger.warning(
                f"[TOWER] Invalid frame size: {frame.size} samples, "
                f"expected {expected_samples} samples. Dropping frame."
            )
            return
        
        # Convert numpy array to bytes (s16le format)
        try:
            pcm_bytes = frame.astype(np.int16).tobytes()
        except Exception as e:
            logger.error(f"[TOWER] Error converting frame to bytes: {e}")
            return
        
        # Write to socket
        try:
            if self._socket:
                self._socket.sendall(pcm_bytes)
        except BrokenPipeError:
            logger.warning("[TOWER] Socket broken pipe - Tower may have disconnected")
            self._connected = False
            self._socket = None
        except OSError as e:
            logger.warning(f"[TOWER] Socket error: {e}")
            self._connected = False
            if self._socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None
        except Exception as e:
            logger.error(f"[TOWER] Unexpected error writing to socket: {e}")
            self._connected = False
            if self._socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None
    
    def close(self) -> None:
        """Close the socket connection to Tower."""
        logger.info("[TOWER] Closing Tower PCM socket connection")
        self._connected = False
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        logger.info("[TOWER] Tower PCM socket closed")

