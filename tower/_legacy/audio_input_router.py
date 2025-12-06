"""
AudioInputRouter for Retrowaves Tower Phase 3.

Manages Unix domain socket connection from writer and provides PCM frames
to AudioPump with bounded queue and fallback behavior.
"""

import errno
import logging
import os
import socket
import threading
import time
from pathlib import Path
from typing import Optional

from tower.audio.ring_buffer import RingBuffer
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
        
        # Ring buffer with configurable size (default 50 frames)
        # push() never blocks - if full, drops newest frame and increments counter
        # pop() returns frame or None if empty
        buffer_size = getattr(config, 'router_buffer_size', 50)  # Default: 50 frames
        self._queue = RingBuffer(size=buffer_size)
        
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
        
        # Monitoring: track queue stats for debugging
        self._last_queue_log_time = time.monotonic()
        self._queue_log_interval = 5.0  # Log queue stats every 5 seconds
        self._max_queue_size_seen = 0
        self._max_buffer_size_seen = 0
        
        # Ring buffer monitoring: log fill level every 10 seconds
        self._last_ring_buffer_log_time = time.monotonic()
        self._ring_buffer_log_interval = 10.0  # Log ring buffer fill every 10 seconds
    
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
        with self._lock:
            self._queue.clear()
        
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
                        
                        # Set socket to non-blocking for fast reads
                        writer_sock.setblocking(False)
                        
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
        """
        Reader thread: reads frames from writer socket.
        
        CRITICAL: Only closes writer socket when recv() returns 0 bytes (EOF) or
        raises BrokenPipeError/ConnectionResetError. All other errors are handled
        gracefully without closing the socket, ensuring writer never sees BrokenPipeError
        during normal operation, overflow, or fallback scenarios.
        """
        logger.debug("AudioInputRouter reader thread started")
        
        try:
            while not self._shutdown:
                # Get socket reference without holding lock during read
                with self._lock:
                    if not self._writer_connected or not self._writer_socket:
                        break
                    writer_sock = self._writer_socket
                
                try:
                    # Read data (non-blocking - socket is set to non-blocking)
                    # CRITICAL: Only recv() returning 0 or raising BrokenPipeError/ConnectionResetError
                    # indicates actual disconnect. All other errors are transient and should not close socket.
                    data = writer_sock.recv(8192)  # Read up to 8KB at a time (2 frames)
                    
                    if not data:
                        # EOF - writer disconnected (recv() returned 0 bytes)
                        # This is the ONLY reliable indicator of disconnect
                        logger.debug("Writer disconnected (EOF from recv())")
                        try:
                            with self._lock:
                                self._handle_writer_disconnect()
                        except Exception:
                            # Ignore any errors during disconnect handling
                            pass
                        break
                    
                    # Process data while holding lock (minimal time)
                    with self._lock:
                        # Limit buffer size to prevent unbounded growth
                        # If buffer is getting too large, it's likely because frames aren't being consumed
                        # fast enough. Instead of discarding data (which causes pops), we should
                        # process frames more aggressively to drain the buffer.
                        if len(self._read_buffer) + len(data) > self._max_buffer_size:
                            # Buffer too large - process existing frames first to drain buffer
                            # This prevents buffer growth while maintaining frame alignment
                            logger.warning(
                                f"Buffer getting large ({len(self._read_buffer)} + {len(data)} bytes), "
                                f"processing frames to drain buffer"
                            )
                            # Process existing buffer first to extract frames
                            self._process_buffer()
                            # If still too large after processing, we have a real problem
                            # Only then discard excess (but align to frame boundary to avoid pops)
                            if len(self._read_buffer) + len(data) > self._max_buffer_size:
                                excess = (len(self._read_buffer) + len(data) - self._max_buffer_size)
                                # Align discard to frame boundary to prevent misalignment
                                excess_aligned = (excess // self.frame_bytes) * self.frame_bytes
                                if excess_aligned > 0 and excess_aligned < len(self._read_buffer):
                                    self._read_buffer = self._read_buffer[excess_aligned:]
                                    logger.warning(f"Buffer still too large, discarding {excess_aligned} bytes (aligned to frame boundary)")
                                elif excess_aligned >= len(self._read_buffer):
                                    # Clear buffer but keep partial frame alignment
                                    partial = len(self._read_buffer) % self.frame_bytes
                                    self._read_buffer = self._read_buffer[-partial:] if partial > 0 else bytearray()
                                    logger.warning(f"Buffer cleared, preserving {partial} bytes for alignment")
                        
                        self._read_buffer.extend(data)
                        self._process_buffer()
                        # Update last frame timestamp when processing buffer
                        # (frames are added to queue in _process_buffer)
                        
                        # Periodic queue monitoring (every 5 seconds)
                        # Only log when queue is within 1 frame of max to reduce log noise
                        now = time.monotonic()
                        if now - self._last_queue_log_time >= self._queue_log_interval:
                            queue_size = len(self._queue)
                            queue_maxsize = self._queue.size
                            buffer_size = len(self._read_buffer)
                            self._max_queue_size_seen = max(self._max_queue_size_seen, queue_size)
                            self._max_buffer_size_seen = max(self._max_buffer_size_seen, buffer_size)
                            
                            # Only log if queue is within 1 frame of max (queue_size >= maxsize - 1)
                            if queue_size >= queue_maxsize - 1:
                                frames_dropped = self._queue.frames_dropped
                                logger.info(
                                    f"[QUEUE_MONITOR] Queue: {queue_size}/{queue_maxsize} frames, "
                                    f"Buffer: {buffer_size}/{self._max_buffer_size} bytes, "
                                    f"Frames dropped: {frames_dropped}, "
                                    f"Max queue seen: {self._max_queue_size_seen}, "
                                    f"Max buffer seen: {self._max_buffer_size_seen}"
                                )
                            self._last_queue_log_time = now
                
                except BlockingIOError:
                    # No data available - socket is non-blocking, so this is expected
                    # This is NOT a disconnect - just continue reading
                    # Use select() with very short timeout instead of sleep to check for data
                    # This reduces latency compared to fixed sleep
                    import select
                    try:
                        ready, _, _ = select.select([writer_sock], [], [], 0.0001)  # 100us timeout
                        if not ready:
                            # Still no data, tiny sleep to avoid CPU spinning
                            time.sleep(0.0005)  # 500us sleep - much less than frame period (21.3ms)
                    except (ValueError, OSError, BrokenPipeError) as e:
                        # select() error - this is NOT necessarily a disconnect
                        # BrokenPipeError from select() can be transient
                        # Only check if writer was explicitly disconnected by another thread
                        # Do NOT close socket here - let recv() determine if socket is actually closed
                        with self._lock:
                            if not self._writer_connected or not self._writer_socket:
                                # Writer was disconnected by another thread (e.g., watchdog or shutdown)
                                break
                        # Continue reading - socket might still be valid
                        time.sleep(0.0005)  # 500us sleep
                    continue
                except (BrokenPipeError, ConnectionResetError) as e:
                    # These errors from recv() indicate actual disconnect
                    # BrokenPipeError/ConnectionResetError from recv() means the peer closed the connection
                    logger.debug(f"Writer disconnected: {e}")
                    try:
                        with self._lock:
                            self._handle_writer_disconnect()
                    except Exception:
                        # Ignore any errors during disconnect handling
                        pass
                    break
                except OSError as e:
                    # OSError from recv() - check error code to determine if it's a disconnect
                    # Many OSErrors are transient and do NOT indicate disconnect
                    # Only treat as disconnect if it's a clear connection error
                    errno = getattr(e, 'errno', None)
                    if errno in (errno.EBADF, errno.ENOTSOCK):
                        # Socket is invalid - treat as disconnect
                        logger.debug(f"Socket invalid (errno={errno}): {e}")
                        try:
                            with self._lock:
                                self._handle_writer_disconnect()
                        except Exception:
                            pass
                        break
                    else:
                        # Transient OSError - log but continue reading
                        # Do NOT close socket - writer is still connected
                        logger.debug(f"Transient socket error (errno={errno}), continuing: {e}")
                        time.sleep(0.001)  # Brief sleep before retry
                        continue
                except Exception as e:
                    # Unexpected error - log but do NOT close socket
                    # Many exceptions are transient and don't indicate disconnect
                    logger.warning(f"Unexpected error reading from writer (continuing): {e}")
                    # Continue reading - socket might still be valid
                    time.sleep(0.001)  # Brief sleep before retry
                    continue
        
        except Exception as e:
            # Catch any remaining exceptions to prevent them from bubbling up
            logger.debug(f"Reader thread error (handled): {e}")
        finally:
            # Ensure clean shutdown - handle disconnect if still connected
            # This only runs when thread is stopping (shutdown or actual disconnect)
            try:
                with self._lock:
                    if self._writer_connected:
                        self._handle_writer_disconnect()
            except Exception:
                # Ignore errors during final cleanup
                pass
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
            
            # Validate frame size (defensive check)
            if len(frame) != self.frame_bytes:
                logger.error(
                    f"Internal error: extracted frame size {len(frame)} bytes, "
                    f"expected {self.frame_bytes} bytes. Discarding frame."
                )
                continue
            
            # Add frame to ring buffer
            # push() never blocks - if buffer is full, drops newest frame and increments counter
            # This ensures writer never blocks and we preserve older frames
            self._queue.push(frame)
            
            # Log drops occasionally to reduce noise (every 100 drops)
            frames_dropped = self._queue.frames_dropped
            if frames_dropped > 0 and frames_dropped % 100 == 0:
                logger.debug(
                    f"Ring buffer full, dropped newest frame (total dropped: {frames_dropped})"
                )
            
            # Update last frame timestamp when a valid frame is queued
            self.last_frame_ts = time.monotonic()
            self.router_dead = False
    
    def _handle_writer_disconnect(self) -> None:
        """
        Handle writer disconnection gracefully.
        
        Stops consuming, clears queue, returns to idle state.
        Never raises exceptions - all errors are swallowed.
        
        Must be called with lock held.
        """
        try:
            # Close writer socket (ignore all errors)
            if self._writer_socket:
                try:
                    self._writer_socket.close()
                except (BrokenPipeError, OSError, Exception):
                    # All socket close errors are normal during disconnect
                    pass
                self._writer_socket = None
            
            # Return to idle state
            self._writer_connected = False
            
            # Clear read buffer
            try:
                self._read_buffer = bytearray()
            except Exception:
                pass
            
            # Clear queue (stop consuming)
            try:
                self._queue.clear()
            except Exception:
                pass
            
            logger.debug("Writer disconnected, returned to idle state")
        except Exception:
            # Never bubble up - disconnect is normal, not fatal
            # Ensure we're in idle state even if something went wrong
            try:
                self._writer_socket = None
                self._writer_connected = False
                self._read_buffer = bytearray()
            except Exception:
                pass
    
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
        Watchdog thread: monitors for idle timeout and marks router as dead if needed.
        
        CRITICAL: This thread does NOT close the writer socket. The socket is only
        closed when the writer actually disconnects (detected by recv() returning 0
        or raising BrokenPipeError/ConnectionResetError in the reader thread).
        
        If no frames are received for ROUTER_IDLE_TIMEOUT_SEC, the router is marked
        as dead (for fallback purposes), but the writer socket remains open. This
        allows Tower to run indefinitely with tone fallback while keeping the writer
        connection alive. The writer can continue writing without seeing BrokenPipeError.
        """
        logger.debug("AudioInputRouter watchdog thread started")
        
        timeout_sec = self.config.router_idle_timeout_sec
        
        try:
            while not self._shutdown:
                time.sleep(5.0)  # Check every 5 seconds
                
                if self._shutdown:
                    break
                
                now = time.monotonic()
                
                # Log ring buffer fill level every 10 seconds
                if now - self._last_ring_buffer_log_time >= self._ring_buffer_log_interval:
                    with self._lock:
                        queue_stats = self._queue.get_stats()
                        queue_size = queue_stats["count"]
                        queue_maxsize = queue_stats["size"]
                        queue_utilization = queue_stats["utilization"]
                        frames_dropped = queue_stats["frames_dropped"]
                        
                        logger.info(
                            f"[RING_BUFFER] Fill: {queue_size}/{queue_maxsize} frames "
                            f"({queue_utilization*100:.1f}% full), "
                            f"dropped: {frames_dropped} frames"
                        )
                    
                    self._last_ring_buffer_log_time = now
                
                with self._lock:
                    # Only check if writer is connected
                    if not self._writer_connected:
                        continue
                    
                    # Check if idle timeout exceeded
                    idle_time = now - self.last_frame_ts
                    
                    if idle_time > timeout_sec:
                        # No PCM for timeout window - mark router as dead for fallback
                        # BUT do NOT close the writer socket - writer may still be connected
                        # and trying to write. Only the reader thread can determine actual disconnect.
                        logger.warning(
                            f"No PCM for {idle_time:.1f}s (timeout: {timeout_sec}s) — "
                            "marking router as dead for fallback (socket remains open)"
                        )
                        
                        # Mark router as dead (triggers fallback in AudioPump)
                        # Do NOT close socket - writer connection remains alive
                        self.router_dead = True
                        
                        # Clear queue (stop consuming, but don't close connection)
                        self._queue.clear()
                        
                        # Continue listening for new writer without restarting Tower
                        # Writer socket remains open - reader thread will detect actual disconnect
                        logger.info("Router marked as dead, waiting for frames or reconnect")
        
        except Exception as e:
            logger.error(f"Watchdog thread error: {e}")
        finally:
            logger.debug("AudioInputRouter watchdog thread stopped")
    
    def get_next_frame(self, timeout_ms: float = 50.0) -> Optional[bytes]:
        """
        Get next frame from ring buffer.
        
        Optimized: Uses popleft() if buffer has frames (non-blocking),
        only uses timeout if buffer is empty.
        
        Args:
            timeout_ms: Timeout in milliseconds (only used if buffer is empty)
        
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
        
        # Try non-blocking pop first (if buffer has frames, returns immediately)
        with self._lock:
            frame = self._queue.pop()
            
            if frame is not None:
                # Validate frame size before returning (defensive check)
                if len(frame) != self.frame_bytes:
                    logger.error(
                        f"Invalid frame size in buffer: {len(frame)} bytes, "
                        f"expected {self.frame_bytes} bytes. Discarding frame."
                    )
                    # Return None to trigger fallback
                    return None
                
                # Update timestamp when frame is retrieved
                self.last_frame_ts = time.monotonic()
                self.router_dead = False
                return frame
        
        # Buffer is empty - wait briefly for new frame (with timeout)
        # RingBuffer.pop() is non-blocking, so we poll with sleep
        # CRITICAL: Keep timeout very short to avoid delaying AudioPump loop
        # AudioPump must maintain exactly 21.333ms frame period
        timeout_seconds = timeout_ms / 1000.0
        start_time = time.monotonic()
        poll_interval = 0.0005  # 500us polling interval (reduced from 1ms to minimize overhead)
        
        # Only poll if timeout is reasonable (don't waste time if timeout is very short)
        if timeout_seconds > 0.001:  # Only poll if timeout > 1ms
            while (time.monotonic() - start_time) < timeout_seconds:
                with self._lock:
                    frame = self._queue.pop()
                    
                    if frame is not None:
                        # Validate frame size before returning (defensive check)
                        if len(frame) != self.frame_bytes:
                            logger.error(
                                f"Invalid frame size in buffer: {len(frame)} bytes, "
                                f"expected {self.frame_bytes} bytes. Discarding frame."
                            )
                            # Return None to trigger fallback
                            return None
                        
                        # Update timestamp when frame is retrieved
                        self.last_frame_ts = time.monotonic()
                        self.router_dead = False
                        return frame
                
                # Brief sleep before next poll (reduced to minimize overhead)
                remaining = timeout_seconds - (time.monotonic() - start_time)
                if remaining > 0:
                    time.sleep(min(poll_interval, remaining))
        
        # Timeout - no frame available
        return None
    
    def get_queue_stats(self) -> dict:
        """
        Get current ring buffer and read buffer statistics for monitoring.
        
        Returns:
            dict with buffer size, and drop statistics
        """
        with self._lock:
            queue_stats = self._queue.get_stats()
            return {
                "queue_size": queue_stats["count"],
                "queue_maxsize": queue_stats["size"],
                "queue_utilization": queue_stats["utilization"],
                "buffer_size": len(self._read_buffer),
                "buffer_maxsize": self._max_buffer_size,
                "buffer_utilization": len(self._read_buffer) / self._max_buffer_size if self._max_buffer_size > 0 else 0.0,
                "total_frames_dropped": queue_stats["frames_dropped"],
                "max_queue_size_seen": self._max_queue_size_seen,
                "max_buffer_size_seen": self._max_buffer_size_seen,
                "writer_connected": self._writer_connected,
                "router_dead": self.router_dead,
            }

