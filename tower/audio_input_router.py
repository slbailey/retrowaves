"""
AudioInputRouter for Retrowaves Tower Phase 3.

Manages Unix domain socket connection from writer and provides PCM frames
to AudioPump with bounded queue and fallback behavior.
"""

import logging
import os
import queue
import socket
import threading
import time
from pathlib import Path
from typing import Optional

from tower.config import TowerConfig

logger = logging.getLogger(__name__)


class AudioInputRouter:
    """
    Router for audio input from Unix domain socket.
    
    Manages writer connection, reads PCM frames, and provides them
    to AudioPump via a bounded queue.
    """
    
    def __init__(self, config: TowerConfig, socket_path: str):
        """
        Initialize AudioInputRouter.
        
        Args:
            config: Tower configuration
            socket_path: Path to Unix domain socket
        """
        self.config = config
        self.socket_path = socket_path
        self.frame_bytes = config.frame_bytes  # 4096 bytes
        
        # Bounded queue of size 5
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=5)
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Connection state
        self._listener_socket: Optional[socket.socket] = None
        self._writer_socket: Optional[socket.socket] = None
        self._writer_connected = False
        self._reader_thread: Optional[threading.Thread] = None
        self._listener_thread: Optional[threading.Thread] = None
        
        # Shutdown flag
        self._shutdown = False
        
        # Watchdog state for long-running fallback
        self.last_frame_ts = time.monotonic()
        self.router_dead = False
        
        # Buffer for partial frames
        # Limit buffer size to prevent unbounded growth from misaligned data
        self._read_buffer = bytearray()
        self._max_buffer_size = 16384  # 16KB max buffer (4 frames worth)
        
        # Watchdog thread
        self._watchdog_thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        """Start AudioInputRouter (create socket and start listening)."""
        if self._listener_socket is not None:
            raise RuntimeError("AudioInputRouter already started")
        
        logger.info(f"Starting AudioInputRouter on socket: {self.socket_path}")
        
        # Clean up stale socket file if it exists
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
                logger.info(f"Removed stale socket file: {self.socket_path}")
            except OSError as e:
                logger.warning(f"Could not remove stale socket file: {e}")
        
        # Create directory if needed
        socket_dir = os.path.dirname(self.socket_path)
        if socket_dir and not os.path.exists(socket_dir):
            try:
                os.makedirs(socket_dir, exist_ok=True)
            except OSError as e:
                logger.error(f"Could not create socket directory: {e}")
                raise
        
        # Create Unix domain socket
        self._listener_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        
        try:
            # Bind to socket path
            self._listener_socket.bind(self.socket_path)
            # Listen for connections (backlog of 1)
            self._listener_socket.listen(1)
            logger.info(f"Unix socket listening on: {self.socket_path}")
        except OSError as e:
            logger.error(f"Failed to bind Unix socket: {e}")
            self._listener_socket.close()
            self._listener_socket = None
            raise
        
        # Start listener thread
        self._listener_thread = threading.Thread(
            target=self._listener_loop,
            daemon=False,
            name="AudioInputRouter-Listener"
        )
        self._listener_thread.start()
        
        # Start watchdog thread
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=False,
            name="AudioInputRouter-Watchdog"
        )
        self._watchdog_thread.start()
        
        logger.info("AudioInputRouter started")
    
    def stop(self) -> None:
        """Stop AudioInputRouter and clean up resources."""
        if self._shutdown:
            return
        
        logger.info("Stopping AudioInputRouter...")
        self._shutdown = True
        
        # Close writer socket
        with self._lock:
            if self._writer_socket:
                try:
                    self._writer_socket.close()
                except Exception:
                    pass
                self._writer_socket = None
            self._writer_connected = False
        
        # Close listener socket
        if self._listener_socket:
            try:
                self._listener_socket.close()
            except Exception:
                pass
            self._listener_socket = None
        
        # Wait for threads
        if self._listener_thread:
            self._listener_thread.join(timeout=2.0)
        
        if self._reader_thread:
            self._reader_thread.join(timeout=2.0)
        
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=2.0)
        
        # Clear queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        
        # Remove socket file
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
                logger.info(f"Removed socket file: {self.socket_path}")
        except OSError as e:
            logger.warning(f"Could not remove socket file: {e}")
        
        logger.info("AudioInputRouter stopped")
    
    def _listener_loop(self) -> None:
        """Listener thread: accepts writer connections."""
        logger.debug("AudioInputRouter listener thread started")
        
        try:
            while not self._shutdown:
                if not self._listener_socket:
                    break
                
                try:
                    # Accept connection (with timeout to allow shutdown check)
                    self._listener_socket.settimeout(0.5)
                    writer_sock, _ = self._listener_socket.accept()
                    
                    with self._lock:
                        # Reject if already connected
                        if self._writer_connected:
                            logger.warning("Writer already connected, rejecting new connection")
                            try:
                                writer_sock.close()
                            except Exception:
                                pass
                            continue
                        
                        # Accept new writer
                        if self._writer_socket:
                            # Close old socket (shouldn't happen, but be safe)
                            try:
                                self._writer_socket.close()
                            except Exception:
                                pass
                        
                        self._writer_socket = writer_sock
                        self._writer_connected = True
                        self._read_buffer = bytearray()  # Clear buffer on new connection
                        # Reset watchdog state on new connection
                        self.last_frame_ts = time.monotonic()
                        self.router_dead = False
                        
                        logger.info("Writer connected to AudioInputRouter")
                        
                        # Start reader thread if not already running
                        if self._reader_thread is None or not self._reader_thread.is_alive():
                            self._reader_thread = threading.Thread(
                                target=self._reader_loop,
                                daemon=False,
                                name="AudioInputRouter-Reader"
                            )
                            self._reader_thread.start()
                
                except socket.timeout:
                    # Timeout is expected - check shutdown flag
                    continue
                except OSError as e:
                    if not self._shutdown:
                        logger.error(f"Error accepting connection: {e}")
                    break
                except Exception as e:
                    logger.error(f"Unexpected error in listener loop: {e}")
                    break
        
        except Exception as e:
            logger.error(f"Listener thread error: {e}")
        finally:
            logger.debug("AudioInputRouter listener thread stopped")
    
    def _reader_loop(self) -> None:
        """Reader thread: reads frames from writer socket."""
        logger.debug("AudioInputRouter reader thread started")
        
        try:
            while not self._shutdown:
                with self._lock:
                    if not self._writer_connected or not self._writer_socket:
                        break
                    writer_sock = self._writer_socket
                
                try:
                    # Set socket timeout for non-blocking reads
                    writer_sock.settimeout(0.1)
                    
                    # Read data
                    data = writer_sock.recv(8192)  # Read up to 8KB at a time
                    
                    if not data:
                        # EOF - writer disconnected
                        logger.info("Writer disconnected (EOF)")
                        with self._lock:
                            self._handle_writer_disconnect()
                        break
                    
                    # Add to buffer and process complete frames
                    with self._lock:
                        # Limit buffer size to prevent unbounded growth
                        if len(self._read_buffer) + len(data) > self._max_buffer_size:
                            # Buffer too large - likely misaligned data
                            # Discard oldest data to make room (keep last frame worth)
                            excess = len(self._read_buffer) + len(data) - self._max_buffer_size
                            if excess < len(self._read_buffer):
                                self._read_buffer = self._read_buffer[excess:]
                            else:
                                # All buffer is excess - clear it
                                self._read_buffer = bytearray()
                            logger.warning(f"Buffer overflow, discarding {excess} bytes (misaligned data?)")
                        
                        self._read_buffer.extend(data)
                        self._process_buffer()
                        # Update last frame timestamp when processing buffer
                        # (frames are added to queue in _process_buffer)
                
                except socket.timeout:
                    # Timeout is OK - continue reading
                    continue
                except (OSError, ConnectionResetError, BrokenPipeError) as e:
                    # Writer disconnected or error
                    logger.info(f"Writer disconnected: {e}")
                    with self._lock:
                        self._handle_writer_disconnect()
                    break
                except Exception as e:
                    logger.error(f"Unexpected error reading from writer: {e}")
                    with self._lock:
                        self._handle_writer_disconnect()
                    break
        
        except Exception as e:
            logger.error(f"Reader thread error: {e}")
        finally:
            logger.debug("AudioInputRouter reader thread stopped")
    
    def _process_buffer(self) -> None:
        """
        Process buffer to extract complete 4096-byte frames.
        
        Must be called with lock held.
        """
        while len(self._read_buffer) >= self.frame_bytes:
            # Extract one complete frame
            frame = bytes(self._read_buffer[:self.frame_bytes])
            self._read_buffer = self._read_buffer[self.frame_bytes:]
            
            # Try to put frame in queue
            # Contract: On overflow, drop NEWEST frame (the one just received)
            # This means if queue is full, we discard the current frame
            try:
                if self._queue.full():
                    # Queue is full - drop newest frame (the one we just received)
                    logger.debug("Queue full, dropping newest frame")
                    continue
                
                # Add frame to queue (non-blocking)
                self._queue.put_nowait(frame)
                
                # Update last frame timestamp when a valid frame is queued
                self.last_frame_ts = time.monotonic()
                self.router_dead = False
            
            except queue.Full:
                # Should not happen (we check above), but be safe
                logger.warning("Queue full, dropping frame")
                continue
    
    def _handle_writer_disconnect(self) -> None:
        """
        Handle writer disconnection.
        
        Must be called with lock held.
        """
        if self._writer_socket:
            try:
                self._writer_socket.close()
            except Exception:
                pass
            self._writer_socket = None
        
        self._writer_connected = False
        self._read_buffer = bytearray()  # Clear buffer
        
        # Clear queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        
        logger.info("Writer disconnected, queue cleared")
    
    def pcm_available(self, grace_sec: float = 5.0) -> bool:
        """
        Check if PCM is available within grace period.
        
        Returns True if a frame was received within the grace period,
        indicating PCM source is still active (even if queue is temporarily empty).
        
        Args:
            grace_sec: Grace period in seconds (default: 5.0)
            
        Returns:
            True if PCM was received within grace period, False otherwise
        """
        with self._lock:
            if not self._writer_connected:
                return False
            
            elapsed = time.monotonic() - self.last_frame_ts
            return elapsed < grace_sec
    
    def _watchdog_loop(self) -> None:
        """
        Watchdog thread: monitors for idle timeout and resets router if needed.
        
        If no frames are received for ROUTER_IDLE_TIMEOUT_SEC, the router is marked
        as dead, the writer socket is closed, and the queue is cleared. This allows
        Tower to run indefinitely with tone fallback and automatically resume PCM
        when Station reconnects.
        """
        logger.debug("AudioInputRouter watchdog thread started")
        
        timeout_sec = self.config.router_idle_timeout_sec
        
        try:
            while not self._shutdown:
                time.sleep(5.0)  # Check every 5 seconds
                
                if self._shutdown:
                    break
                
                with self._lock:
                    # Only check if writer is connected
                    if not self._writer_connected:
                        continue
                    
                    # Check if idle timeout exceeded
                    now = time.monotonic()
                    idle_time = now - self.last_frame_ts
                    
                    if idle_time > timeout_sec:
                        # No PCM for timeout window - mark router as dead
                        logger.warning(
                            f"No PCM for {idle_time:.1f}s (timeout: {timeout_sec}s) — "
                            "dropping writer, waiting for reconnect"
                        )
                        
                        # Close active writer socket if any
                        if self._writer_socket:
                            try:
                                self._writer_socket.close()
                            except Exception:
                                pass
                            self._writer_socket = None
                        
                        # Clear queue completely
                        while not self._queue.empty():
                            try:
                                self._queue.get_nowait()
                            except queue.Empty:
                                break
                        
                        # Mark router as dead
                        self.router_dead = True
                        self._writer_connected = False
                        self._read_buffer = bytearray()
                        
                        # Continue listening for new writer without restarting Tower
                        logger.info("Router reset complete, waiting for Station reconnect")
        
        except Exception as e:
            logger.error(f"Watchdog thread error: {e}")
        finally:
            logger.debug("AudioInputRouter watchdog thread stopped")
    
    def get_next_frame(self, timeout_ms: float = 50.0) -> Optional[bytes]:
        """
        Get next frame from queue.
        
        Args:
            timeout_ms: Timeout in milliseconds
        
        Returns:
            bytes: Complete frame (4096 bytes) or None if timeout/no writer/router_dead
        """
        # Check if router is dead - if so, always return None to force fallback
        with self._lock:
            if self.router_dead:
                return None
        
        # Check if writer is connected
        with self._lock:
            if not self._writer_connected:
                return None
        
        # Try to get frame from queue with timeout
        try:
            timeout_seconds = timeout_ms / 1000.0
            frame = self._queue.get(timeout=timeout_seconds)
            # Update timestamp when frame is retrieved
            if frame:
                self.last_frame_ts = time.monotonic()
                self.router_dead = False
            return frame
        except queue.Empty:
            # Timeout - no frame available
            return None

