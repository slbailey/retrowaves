"""
HTTP connection manager for Retrowaves Tower.

Manages connected HTTP clients and broadcasts MP3 data to all of them.
Phase 4: Adds slow-client detection and per-client buffering.
"""

import logging
import select
import socket
import threading
import time
from typing import Dict, BinaryIO

logger = logging.getLogger(__name__)


class ClientInfo:
    """Information about a connected client."""
    
    def __init__(self, sock: socket.socket, wfile: BinaryIO):
        """
        Initialize client info.
        
        Args:
            sock: Raw socket for the HTTP connection
            wfile: Writable file-like object for the HTTP response (e.g., handler.wfile)
        """
        self.sock: socket.socket = sock
        self.wfile: BinaryIO = wfile
        # Simple in-memory buffer of pending bytes for this client
        self.buffer = bytearray()
        self.dropped: bool = False
        self.lock = threading.Lock()


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
    
    def start(self) -> None:
        """
        Start connection manager.
        
        Phase 4 slow-client handling uses blocking writes with timing;
        no background threads or socket configuration are required.
        """
        # No-op kept for backwards compatibility with earlier phases.
        return
    
    def add_client(self, sock: socket.socket, wfile: BinaryIO) -> None:
        """
        Add a client to the broadcast list.
        
        Args:
            sock: Raw socket for the HTTP connection
            wfile: Writable file-like object for the HTTP response.
        """
        try:
            with self._lock:
                self._clients[sock] = ClientInfo(sock, wfile)
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
            with client_info.lock:
                client_info.buffer.clear()
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
        Broadcast MP3 data to all connected clients.
        
        Slow-client detection uses select.select() to check if file descriptors
        are writable before attempting blocking writes, preventing hangs on dead connections.
        
        Args:
            data: MP3 data chunk to broadcast
        """
        if not data:
            return
        
        logger.debug(f"Broadcasting {len(data)} bytes to {len(self._clients)} clients")
        
        # Take a snapshot of current clients so we don't hold the lock
        # while performing blocking I/O.
        with self._lock:
            clients = list(self._clients.items())
        
        timeout_sec = self._client_timeout_ms / 1000.0
        dead_clients: list[socket.socket] = []
        
        for sock, client_info in clients:
            # Skip if already dropped
            if client_info.dropped:
                dead_clients.append(sock)
                continue
            
            # Check buffer and prepare data to write
            with client_info.lock:
                current_buffer_size = len(client_info.buffer)
                # If buffer already exceeds limit, drop before writing
                if current_buffer_size > self._client_buffer_bytes:
                    dead_clients.append(sock)
                    continue
                
                # Check if adding new data would exceed limit
                if current_buffer_size + len(data) > self._client_buffer_bytes:
                    dead_clients.append(sock)
                    continue
                
                # Append new data to buffer
                client_info.buffer.extend(data)
                # Write the entire buffer (including any previously buffered data)
                chunk = bytes(client_info.buffer)
            
            # Simulate slow clients in test mode if requested
            if self._test_mode and self._force_slow_client_test:
                # Intentional delay to push duration over timeout threshold
                time.sleep(timeout_sec * 1.1)
            
            # MUST check writable + exceptional fds
            try:
                ready_r, ready_w, ready_e = select.select(
                    [], 
                    [client_info.sock], 
                    [client_info.sock], 
                    timeout_sec
                )
            except Exception:
                # Select failed - drop client
                self.remove_client(sock)
                continue
            
            # If socket is closed, select returns it in ready_e
            # If socket is not writable (timeout), ready_w is empty
            # Also check that our specific socket is in the writable set
            if ready_e or not ready_w or client_info.sock not in ready_w:
                if ready_e:
                    logger.debug(f"Client socket in exceptional set, dropping")
                elif not ready_w:
                    logger.debug(f"Client socket not writable (timeout), dropping")
                elif client_info.sock not in ready_w:
                    logger.debug(f"Client socket not in writable set, dropping")
                self.remove_client(sock)
                continue
            
            # Socket is writable - proceed with write
            try:
                bytes_written = client_info.wfile.write(chunk)
                client_info.wfile.flush()
                logger.debug(f"Wrote {bytes_written} bytes to client")
            except Exception as e:
                # Write/flush failed - drop client
                logger.debug(f"Write/flush failed for client: {e}")
                dead_clients.append(sock)
                continue
            
            # Clear buffer after a successful write
            with client_info.lock:
                client_info.buffer.clear()
        
        # Remove any dead clients
        if dead_clients:
            for sock in dead_clients:
                self.remove_client(sock)
    
    def close_all(self) -> None:
        """Close all client connections."""
        with self._lock:
            clients = list(self._clients.items())
            self._clients.clear()
        
        for sock, client_info in clients:
            client_info.dropped = True
            with client_info.lock:
                client_info.buffer.clear()
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
