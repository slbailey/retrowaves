"""
HTTP connection manager for Retrowaves Tower.

Manages connected HTTP clients and broadcasts MP3 data to all of them.
Phase 4: Adds slow-client detection and per-client buffering.
"""

import logging
import queue
import select
import socket
import threading
import time
from typing import Dict, BinaryIO, Optional

logger = logging.getLogger(__name__)


class ClientInfo:
    """Information about a connected client."""
    
    def __init__(self, sock: socket.socket, wfile: BinaryIO, buffer_bytes: int):
        """
        Initialize client info.
        
        Args:
            sock: Raw socket for the HTTP connection
            wfile: Writable file-like object for the HTTP response (e.g., handler.wfile)
            buffer_bytes: Maximum buffer size in bytes (64KB default)
        """
        self.sock: socket.socket = sock
        self.wfile: BinaryIO = wfile
        # Phase 4: Per-client pending data buffer
        self.pending_data: bytearray = bytearray()
        self.dropped: bool = False
        self.lock = threading.Lock()
        self.buffer_bytes = buffer_bytes
        self.writer_thread: Optional[threading.Thread] = None


class HTTPConnectionManager:
    """
    Manages HTTP client connections and broadcasts MP3 data.
    
    Phase 4: Adds slow-client detection with timeouts and buffer limits.
    Thread-safe client list management. Broadcasts MP3 chunks to all
    connected clients without blocking the encoder reader thread.
    """
    
    def __init__(self, client_timeout_ms: int, client_buffer_bytes: int, test_mode: bool = False, force_slow_client_test: bool = False):
        """
        Initialize connection manager.
        
        Args:
            client_timeout_ms: Timeout in milliseconds for slow clients
            client_buffer_bytes: Maximum buffer size per client in bytes
            test_mode: Whether test mode is enabled (for deterministic behavior)
            force_slow_client_test: Whether to force slow client simulation in tests
        """
        # Map of client sockets to client info
        self._clients: Dict[socket.socket, ClientInfo] = {}
        self._lock = threading.Lock()
        self._client_timeout_ms = client_timeout_ms
        self._client_buffer_bytes = client_buffer_bytes
        self._test_mode = test_mode
        self._force_slow_client_test = force_slow_client_test
        self._shutdown = False
    
    def start(self) -> None:
        """
        Start connection manager.
        
        Phase 4: Per-client writer threads are spawned on add_client().
        This method is kept for backwards compatibility.
        """
        self._shutdown = False
    
    def add_client(self, sock: socket.socket, wfile: BinaryIO) -> None:
        """
        Add a client to the broadcast list and spawn writer thread.
        
        Args:
            sock: Raw socket for the HTTP connection
            wfile: Writable file-like object for the HTTP response.
        """
        try:
            with self._lock:
                client_info = ClientInfo(sock, wfile, self._client_buffer_bytes)
                self._clients[sock] = client_info
                
                # Spawn writer thread for this client
                writer_thread = threading.Thread(
                    target=self._client_writer_loop,
                    args=(sock, client_info),
                    daemon=True,
                    name=f"ClientWriter-{id(sock)}"
                )
                client_info.writer_thread = writer_thread
                writer_thread.start()
                
                logger.debug(f"Client connected (total: {len(self._clients)})")
        except Exception as e:
            logger.error(f"Error adding client: {e}", exc_info=True)
            raise
    
    def remove_client(self, sock: socket.socket) -> None:
        """
        Remove a client from the broadcast list.
        
        Args:
            sock: Client socket to remove
        """
        with self._lock:
            client_info = self._clients.pop(sock, None)
            remaining = len(self._clients)
        
        if client_info is not None:
            client_info.dropped = True
            # Clear pending data
            with client_info.lock:
                client_info.pending_data.clear()
            # Wait for writer thread to finish (with timeout)
            if client_info.writer_thread is not None:
                client_info.writer_thread.join(timeout=0.5)
            try:
                client_info.wfile.close()
            except Exception:
                pass
            try:
                client_info.sock.close()
            except Exception:
                pass
            logger.debug(f"Client disconnected (total: {remaining})")
    
    def broadcast(self, data: bytes) -> None:
        """
        Broadcast MP3 data to all connected clients by appending to per-client pending_data.
        
        This method is called by the encoder reader thread and must never block.
        It appends chunks to all client pending_data buffers. If buffer exceeds 64KB,
        the client is dropped (they're consuming too slowly).
        
        If broadcast to one client fails → drop that client, continue streaming others.
        The broadcast loop never terminates from exceptions unless shutdown.
        
        Args:
            data: MP3 data chunk to broadcast
        """
        if not data:
            return
        
        logger.debug(f"Broadcasting {len(data)} bytes to {len(self._clients)} clients")
        
        # Take a snapshot of current clients so we don't hold the lock
        # while performing buffer operations.
        with self._lock:
            clients = list(self._clients.items())
        
        dead_clients: list[socket.socket] = []
        
        for sock, client_info in clients:
            # Skip if already dropped
            if client_info.dropped:
                dead_clients.append(sock)
                continue
            
            # Phase 4: ONLY append to pending_data - never call send() here
            # The writer loop is the only place that calls sock.send()
            with client_info.lock:
                # Check if adding this chunk would exceed 64KB cap
                # (writer loop will also check and drop, but prevent unnecessary growth here)
                if len(client_info.pending_data) + len(data) > 65536:
                    # pending_data would exceed 64KB - drop client
                    # (writer loop will also catch this, but drop immediately here)
                    logger.debug(f"Client pending_data would exceed 64KB, dropping slow client")
                    dead_clients.append(sock)
                    continue
                
                try:
                    # Append chunk to pending_data (non-blocking, always succeeds)
                    client_info.pending_data.extend(data)
                except Exception as e:
                    # Any exception from this client - drop them and continue
                    # This ensures broadcast continues even if one client has issues
                    logger.debug(f"Error broadcasting to client (dropping): {e}")
                    dead_clients.append(sock)
                    continue
        
        # Remove any dead clients (outside the loop to avoid modifying dict during iteration)
        # This is done after all clients are processed to ensure broadcast continues
        if dead_clients:
            for sock in dead_clients:
                try:
                    self.remove_client(sock)
                except Exception as e:
                    # Even remove_client failures shouldn't stop broadcast
                    logger.debug(f"Error removing client: {e}")
    
    def _client_writer_loop(self, sock: socket.socket, client_info: ClientInfo) -> None:
        """
        Writer thread loop for a single client.
        
        Phase 4: This is the ONLY place that calls sock.send().
        Socket is already configured in blocking mode with timeout in the accept path.
        
        For each client with non-empty pending_data:
        - Try to send data using sock.send() (blocking with timeout)
        - If socket.timeout: client could not accept data within timeout -> drop
        - If OSError: fatal socket error -> drop
        - If sent > 0: remove sent bytes from pending_data
        - If pending_data becomes empty: clear slow-client timers
        - Enforce 64KB cap: if len(pending_data) > 65536, drop immediately
        
        Args:
            sock: Client socket (already configured with blocking mode and timeout)
            client_info: Client information
        """
        logger.debug(f"Client writer thread started for {sock}")
        
        try:
            while not self._shutdown and not client_info.dropped:
                # Get pending data to send
                data_to_send = None
                with client_info.lock:
                    if client_info.pending_data:
                        # Enforce 64KB cap: if pending_data exceeds limit, drop client immediately
                        if len(client_info.pending_data) > 65536:
                            logger.debug(f"Client pending_data exceeded 64KB ({len(client_info.pending_data)} bytes), dropping slow client")
                            break
                        
                        # Copy pending data to send (release lock quickly)
                        data_to_send = bytes(client_info.pending_data)
                
                if not data_to_send:
                    # No data - sleep briefly and continue
                    time.sleep(0.01)
                    continue
                
                # Attempt to send data (blocking with timeout)
                # Socket is already configured with timeout in accept path
                # Keep trying to send until buffer is full and send() blocks (then timeout)
                # Don't sleep between sends - keep trying to send until buffer fills
                try:
                    # Try to send data - if buffer is full, send() will block and timeout
                    # Keep sending continuously until buffer fills and send() blocks
                    # This ensures slow clients are detected when buffer fills and send() blocks
                    sent = sock.send(data_to_send)
                    
                    if sent == 0:
                        # Socket closed
                        raise BrokenPipeError("Socket closed during send")
                    
                    # Remove sent portion from pending_data
                    with client_info.lock:
                        # Remove the bytes we successfully sent
                        client_info.pending_data = client_info.pending_data[sent:]
                    
                    # Continue loop immediately to send more data (no sleep)
                    # If buffer fills, next send() will block and timeout
                    # This ensures we keep trying to send until buffer is full
                    continue
                    
                except socket.timeout:
                    # This client could not accept data within TOWER_CLIENT_TIMEOUT_MS
                    # -> treat as slow and drop immediately
                    logger.debug(f"Client send() timed out (could not accept data within {self._client_timeout_ms}ms), dropping slow client")
                    break
                    
                except OSError as e:
                    # Any other fatal socket error -> drop client
                    logger.debug(f"Client write failed (OSError): {e}, dropping client")
                    break
                    
                except (ConnectionResetError, BrokenPipeError) as e:
                    # Client disconnected - drop client
                    logger.debug(f"Client write failed: {e}, dropping client")
                    break
                    
                except Exception as e:
                    # Any other write error - drop client
                    logger.debug(f"Unexpected write error: {e}, dropping client")
                    break
        
        except Exception as e:
            logger.debug(f"Writer thread error: {e}")
        finally:
            # Mark as dropped - HTTP handler or broadcast() will remove client
            client_info.dropped = True
            logger.debug(f"Client writer thread stopped for {sock}")
    
    def get_client_queue(self, sock: socket.socket) -> Optional[queue.Queue]:
        """
        Get the queue for a specific client (for backwards compatibility).
        
        Phase 4: This method is kept for compatibility but returns None
        since we now use pending_data buffers instead of queues.
        
        Args:
            sock: Client socket
            
        Returns:
            None (queues no longer used)
        """
        # Phase 4: No longer using queues - return None for backwards compatibility
        return None
    
    def is_client_dropped(self, sock: socket.socket) -> bool:
        """
        Check if a client is dropped.
        
        Args:
            sock: Client socket
            
        Returns:
            True if client is dropped or not found, False otherwise
        """
        with self._lock:
            client_info = self._clients.get(sock)
            if client_info is None:
                return True
            return client_info.dropped
    
    def close_all(self) -> None:
        """Close all client connections."""
        self._shutdown = True
        
        with self._lock:
            clients = list(self._clients.items())
            self._clients.clear()
        
        for sock, client_info in clients:
            client_info.dropped = True
            # Clear pending data
            with client_info.lock:
                client_info.pending_data.clear()
            # Wait for writer thread to finish
            if client_info.writer_thread is not None:
                client_info.writer_thread.join(timeout=0.5)
            try:
                client_info.wfile.close()
            except Exception:
                pass
            try:
                client_info.sock.close()
            except Exception:
                pass
        
        logger.info("All client connections closed")
    
    def get_client_count(self) -> int:
        """
        Get current number of connected clients.
        
        Returns:
            int: Number of connected clients
        """
        with self._lock:
            return len(self._clients)
