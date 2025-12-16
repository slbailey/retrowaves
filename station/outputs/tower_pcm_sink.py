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

from station.outputs.base_sink import BaseSink
from station.outputs.tower_control import TowerControlClient

logger = logging.getLogger(__name__)

# Setup file handler for contract-compliant logging (LOG1, LOG2, LOG3, LOG4)
# Per contract: /var/log/retrowaves/station.log, non-blocking, rotation-tolerant
# OutputSink is implemented in TowerPCMSink
try:
    import logging.handlers
    # Use WatchedFileHandler for rotation tolerance (per LOG3)
    handler = logging.handlers.WatchedFileHandler('/var/log/retrowaves/station.log', mode='a')
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    # Wrap emit to handle write failures gracefully (per LOG4)
    original_emit = handler.emit
    def safe_emit(record):
        try:
            original_emit(record)
        except (IOError, OSError):
            # Logging failures degrade silently per contract LOG4
            pass
    handler.emit = safe_emit
    # Prevent duplicate handlers on module reload
    if not any(isinstance(h, logging.handlers.WatchedFileHandler)
               and getattr(h, 'baseFilename', None) == '/var/log/retrowaves/station.log'
               for h in logger.handlers):
        logger.addHandler(handler)
    logger.propagate = False  # Avoid duplicate logs
except Exception:
    # Logging must never crash component per LOG4
    # Catch all exceptions (including I/O errors) to prevent import-time failures
    pass


class TowerPCMSink(BaseSink):
    """
    PCM socket sink that connects to Tower's Unix domain socket.
    
    Writes 1024-sample 16-bit PCM frames at 48kHz continuously to Tower.
    Architecture: PlayoutEngine → Mixer → TowerPCMSink → Tower Unix Socket
    """
    
    def __init__(self, socket_path: str = "/var/run/retrowaves/pcm.sock", 
                 sample_rate: int = 48000, channels: int = 2, frame_size: int = 1024,
                 tower_control: Optional[TowerControlClient] = None):
        """
        Initialize Tower PCM sink.
        
        Args:
            socket_path: Path to Tower's Unix domain socket
            sample_rate: Audio sample rate (default: 48000)
            channels: Number of audio channels (default: 2)
            frame_size: Samples per frame (default: 1024)
            tower_control: Optional TowerControlClient for buffer status queries and event emission
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
        self._connection_start_time: Optional[float] = None
        self._total_connections = 0
        self._total_disconnections = 0
        
        # Internal byte buffer for framing PCM data correctly
        # Accumulates bytes until we have complete 4096-byte frames
        self._buffer = bytearray()
        
        # Frame statistics (for close() logging only)
        self._frames_sent = 0
        
        # Track last write time to detect track transitions (gaps > 1 second)
        self._last_write_time: Optional[float] = None
        self._track_transition_threshold = 1.0  # 1 second gap = track transition
        
        # OS3.1: Buffer health monitoring for underflow detection
        # OS3.2: Buffer health monitoring for overflow detection
        self._tower_control = tower_control
        self._last_buffer_check_time = 0.0
        self._buffer_check_interval = 0.1  # Check buffer status every 100ms (non-blocking)
        self._last_buffer_depth: Optional[int] = None  # Track previous depth to detect transitions
        self._last_buffer_at_capacity = False  # Track if buffer was at capacity to detect overflow transitions
        
        logger.info(f"TowerPCMSink initialized (socket={socket_path}, frame_size={frame_size} samples, frame_bytes={self.frame_bytes})")
    
    def write_unpaced(self, frame: np.ndarray) -> None:
        """
        Write PCM frame to Tower's Unix socket without pacing (burst mode).
        
        ARCHITECTURAL NOTE: This method is equivalent to write() - Station never paces.
        Station pushes frames as fast as decoder produces them. Tower owns all timing.
        
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
                f"[PCM] Invalid frame size: {frame.size} samples, "
                f"expected {expected_samples} samples. Dropping frame."
            )
            return
        
        # Convert numpy array to bytes (s16le format) and append to buffer
        try:
            pcm_bytes = frame.astype(np.int16).tobytes()
            self._buffer.extend(pcm_bytes)
        except Exception as e:
            logger.error(f"[PCM] Error converting frame to bytes: {e}")
            return
        
        # OS3.1: Check buffer status periodically for underflow detection
        self._check_buffer_health()
        
        # Send exactly ONE complete frame if available (no pacing - push immediately)
        if len(self._buffer) >= self.frame_bytes:
            # Extract exactly one complete frame
            frame_bytes = bytes(self._buffer[:self.frame_bytes])
            self._buffer = self._buffer[self.frame_bytes:]
            
            # Send complete frame to socket immediately (non-blocking)
            # ARCHITECTURAL INVARIANT: Station must NEVER block Tower.
            # If socket buffer is full, drop frame silently (drop-oldest semantics).
            try:
                if self._socket:
                    # Non-blocking send: if buffer is full, drop frame
                    try:
                        self._socket.sendall(frame_bytes)
                        self._frames_sent += 1
                    except BlockingIOError:
                        # Socket buffer full - drop frame (Tower is not reading fast enough)
                        # This is expected behavior: Station never blocks, Tower handles pacing
                        pass
            except BrokenPipeError:
                if self._connection_start_time:
                    connection_duration = time.time() - self._connection_start_time
                    logger.warning(
                        f"[PCM] Socket broken pipe - Tower may have disconnected "
                        f"(connection duration: {connection_duration:.1f}s)"
                    )
                else:
                    logger.warning("[PCM] Socket broken pipe - Tower may have disconnected")
                self._total_disconnections += 1
                self._connected = False
                self._socket = None
                self._connection_start_time = None
                return
            except OSError as e:
                if self._connection_start_time:
                    connection_duration = time.time() - self._connection_start_time
                    logger.warning(
                        f"[PCM] Socket error: {e} "
                        f"(connection duration: {connection_duration:.1f}s)"
                    )
                else:
                    logger.warning(f"[PCM] Socket error: {e}")
                self._total_disconnections += 1
                self._connected = False
                if self._socket:
                    try:
                        self._socket.close()
                    except Exception:
                        pass
                    self._socket = None
                self._connection_start_time = None
                return
            except Exception as e:
                if self._connection_start_time:
                    connection_duration = time.time() - self._connection_start_time
                    logger.error(
                        f"[PCM] Unexpected error writing to socket: {e} "
                        f"(connection duration: {connection_duration:.1f}s)"
                    )
                else:
                    logger.error(f"[PCM] Unexpected error writing to socket: {e}")
                self._total_disconnections += 1
                self._connected = False
                if self._socket:
                    try:
                        self._socket.close()
                    except Exception:
                        pass
                    self._socket = None
                self._connection_start_time = None
                return
    
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
            
            # Connect to Tower's socket (blocking connect for Unix sockets)
            sock.connect(self.socket_path)
            
            # ARCHITECTURAL INVARIANT: Station must NEVER block Tower.
            # Set socket to non-blocking mode to prevent stalls.
            # If socket buffer is full, we drop frames (drop-oldest semantics).
            sock.setblocking(False)
            
            self._socket = sock
            self._connected = True
            self._connection_start_time = time.time()
            self._total_connections += 1
            logger.debug(
                f"[TOWER] Connected to Tower socket: {self.socket_path} "
                f"(connection #{self._total_connections}, "
                f"previous disconnections: {self._total_disconnections})"
            )
            return True
            
        except FileNotFoundError:
            # Log only on first few attempts to avoid spam
            if not hasattr(self, '_socket_not_found_log_count'):
                self._socket_not_found_log_count = 0
            self._socket_not_found_log_count += 1
            if self._socket_not_found_log_count <= 3:
                logger.warning(
                    f"[TOWER] Tower socket not found: {self.socket_path} "
                    f"(Tower may not be running). Will retry connection."
                )
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
        Write PCM frame to Tower's Unix socket with proper framing.
        
        Maintains internal byte buffer and only sends complete 4096-byte frames.
        On track transitions (gaps > 1 second), discards remaining buffer.
        Station handles real-time pacing, so no sleeps here.
        
        Args:
            frame: numpy array containing PCM audio data (must be 1024 samples, 2 channels, s16le)
        """
        now = time.time()
        
        # Detect track transitions: if gap > 1 second, discard buffer
        # Note: Tower's grace period is 5 seconds, so we discard buffer on transitions
        # to prevent sending stale data from previous track
        track_transition = False
        if self._last_write_time is not None:
            gap = now - self._last_write_time
            if gap > self._track_transition_threshold:
                # Track transition detected - discard remaining buffer
                track_transition = True
                if len(self._buffer) > 0:
                    logger.debug(f"[PCM] Track transition detected (gap={gap:.2f}s), discarding {len(self._buffer)} bytes from buffer")
                    self._buffer.clear()
        self._last_write_time = now
        
        # If this is a track transition, immediately send a silence frame to keep Tower's grace period alive
        # This prevents tone blips during track changes
        if track_transition:
            silence_frame = np.zeros((self.frame_size, self.channels), dtype=np.int16)
            # Send silence frame immediately (bypasses buffer to ensure immediate delivery)
            try:
                silence_bytes = silence_frame.astype(np.int16).tobytes()
                if self._connected and self._socket:
                    self._socket.sendall(silence_bytes)
                    logger.debug(f"[PCM] Sent immediate silence frame after track transition to keep Tower grace period alive")
            except Exception as e:
                logger.debug(f"[PCM] Could not send silence frame after transition: {e}")
        
        # Ensure we're connected
        if not self._connected:
            if not self._connect():
                # Not connected and can't reconnect - drop frame silently
                return
        
        # Validate frame size
        expected_samples = self.frame_size * self.channels
        if frame.size != expected_samples:
            logger.warning(
                f"[PCM] Invalid frame size: {frame.size} samples, "
                f"expected {expected_samples} samples. Dropping frame."
            )
            return
        
        # Convert numpy array to bytes (s16le format) and append to buffer
        try:
            pcm_bytes = frame.astype(np.int16).tobytes()
            self._buffer.extend(pcm_bytes)
        except Exception as e:
            logger.error(f"[PCM] Error converting frame to bytes: {e}")
            return
        
        # OS3.1: Check buffer status periodically for underflow detection
        self._check_buffer_health()
        
        # Extract and send complete 4096-byte frames from buffer
        # NEVER send partial frames - if <4096 remain, wait for next decode cycle
        # ARCHITECTURAL INVARIANT: Station pushes frames as fast as decoder produces them.
        # No pacing, no throttling, no timing logic. Tower owns all timing.
        
        # Send exactly ONE frame if available (no pacing - engine handles timing)
        if len(self._buffer) >= self.frame_bytes:
            # Extract exactly one complete frame
            frame_bytes = bytes(self._buffer[:self.frame_bytes])
            self._buffer = self._buffer[self.frame_bytes:]
            
            # Send complete frame to socket immediately (non-blocking)
            # ARCHITECTURAL INVARIANT: Station must NEVER block Tower.
            # If socket buffer is full, drop frame silently (drop-oldest semantics).
            # Station pushes frames as fast as decoder produces them - no pacing here.
            try:
                if self._socket:
                    # Non-blocking send: if buffer is full, drop frame
                    try:
                        self._socket.sendall(frame_bytes)
                        self._frames_sent += 1
                    except BlockingIOError:
                        # Socket buffer full - drop frame (Tower is not reading fast enough)
                        # This is expected behavior: Station never blocks, Tower handles pacing
                        pass
            except BrokenPipeError:
                if self._connection_start_time:
                    connection_duration = time.time() - self._connection_start_time
                    logger.warning(
                        f"[PCM] Socket broken pipe - Tower may have disconnected "
                        f"(connection duration: {connection_duration:.1f}s)"
                    )
                else:
                    logger.warning("[PCM] Socket broken pipe - Tower may have disconnected")
                self._total_disconnections += 1
                self._connected = False
                self._socket = None
                self._connection_start_time = None
                return
            except OSError as e:
                if self._connection_start_time:
                    connection_duration = time.time() - self._connection_start_time
                    logger.warning(
                        f"[PCM] Socket error: {e} "
                        f"(connection duration: {connection_duration:.1f}s)"
                    )
                else:
                    logger.warning(f"[PCM] Socket error: {e}")
                self._total_disconnections += 1
                self._connected = False
                if self._socket:
                    try:
                        self._socket.close()
                    except Exception:
                        pass
                    self._socket = None
                self._connection_start_time = None
                return
            except Exception as e:
                if self._connection_start_time:
                    connection_duration = time.time() - self._connection_start_time
                    logger.error(
                        f"[PCM] Unexpected error writing to socket: {e} "
                        f"(connection duration: {connection_duration:.1f}s)"
                    )
                else:
                    logger.error(f"[PCM] Unexpected error writing to socket: {e}")
                self._total_disconnections += 1
                self._connected = False
                if self._socket:
                    try:
                        self._socket.close()
                    except Exception:
                        pass
                    self._socket = None
                self._connection_start_time = None
                return
    
    def _check_buffer_health(self) -> None:
        """
        OS3.1: Check Tower buffer status periodically and emit underflow event on transition.
        OS3.2: Check Tower buffer status periodically and emit overflow event when overflow occurs.
        
        This method is called from the output thread during frame writes.
        It checks buffer status at intervals (not every frame) to detect underflow and overflow transitions.
        """
        if not self._tower_control:
            return
        
        # Rate limit buffer checks to avoid excessive HTTP requests
        now = time.monotonic()
        if now - self._last_buffer_check_time < self._buffer_check_interval:
            return
        
        self._last_buffer_check_time = now
        
        # Query Tower's buffer status (non-blocking with short timeout)
        try:
            buffer_data = self._tower_control.get_buffer()
            if buffer_data is None:
                return
            
            # Extract buffer depth and capacity
            buffer_depth = buffer_data.get("count", 0)
            buffer_capacity = buffer_data.get("capacity", 0)
            buffer_at_capacity = (buffer_capacity > 0 and buffer_depth >= buffer_capacity)
            
            # OS3.1: Detect transition to underflow (depth = 0)
            # Only emit on transition from non-zero to zero, not continuously
            if buffer_depth == 0 and self._last_buffer_depth is not None and self._last_buffer_depth > 0:
                # Transition detected: buffer went from non-zero to zero
                # Emit underflow event (Station-local only)
                logger.warning(f"[BUFFER] Underflow detected: buffer_depth={buffer_depth} frames_dropped=0")
            
            # OS3.2: Detect transition to overflow (buffer at capacity)
            # Emit when buffer transitions to capacity (overflow condition detected)
            # Only emit on transition, not continuously while at capacity
            if buffer_at_capacity and not self._last_buffer_at_capacity:
                # Transition detected: buffer reached capacity (overflow condition)
                # When buffer is at capacity, frames are being dropped
                # Emit overflow event (Station-local only)
                logger.warning(f"[BUFFER] Overflow detected: buffer_depth={buffer_depth} frames_dropped=1")
            
            # Update last known buffer state for transition detection
            self._last_buffer_depth = buffer_depth
            self._last_buffer_at_capacity = buffer_at_capacity
            
        except Exception as e:
            # Non-blocking: silently ignore buffer check failures
            logger.debug(f"Error checking buffer health: {e}")
    
    def close(self) -> None:
        """Close the socket connection to Tower."""
        # On close, discard remaining buffer (don't flush partial frames)
        if len(self._buffer) > 0:
            logger.debug(f"[PCM] Closing sink, discarding {len(self._buffer)} bytes from buffer")
            self._buffer.clear()
        
        if self._connection_start_time:
            connection_duration = time.time() - self._connection_start_time
            logger.info(
                f"[PCM] Closing Tower PCM socket connection "
                f"(connection duration: {connection_duration:.1f}s, "
                f"total connections: {self._total_connections}, "
                f"total disconnections: {self._total_disconnections}, "
                f"total frames sent: {self._frames_sent})"
            )
        else:
            logger.info(f"[PCM] Closing Tower PCM socket connection (total frames sent: {self._frames_sent})")
        self._connected = False
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        self._connection_start_time = None
        logger.info("[PCM] Tower PCM socket closed")
