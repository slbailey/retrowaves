"""
HTTP Connection Manager for Appalachia Radio 3.1.

Manages connected HTTP streaming clients and broadcasts MP3 data to them.
Includes backpressure protection with per-client ring buffers.
"""

import logging
import socket
import threading
from collections import deque
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ClientBuffer:
    """
    Per-client ring buffer for backpressure protection.
    
    Maintains a small buffer of MP3 frames. If buffer fills up,
    drops oldest frames to prevent blocking playout.
    """
    
    def __init__(self, max_size: int = 50):
        """
        Initialize client buffer.
        
        Args:
            max_size: Maximum number of frames to buffer (default: 50)
        """
        self.buffer: deque = deque(maxlen=max_size)
        self.lock = threading.Lock()
        self.dropped_frames = 0
        self.total_frames = 0
    
    def add_frame(self, frame: bytes) -> bool:
        """
        Add a frame to the buffer.
        
        If buffer is full, drops oldest frame and logs warning.
        
        Args:
            frame: MP3 frame bytes to add
            
        Returns:
            True if frame was added, False if dropped
        """
        with self.lock:
            self.total_frames += 1
            if len(self.buffer) >= self.buffer.maxlen:
                # Buffer full - drop oldest
                self.buffer.popleft()
                self.dropped_frames += 1
                return False
            
            self.buffer.append(frame)
            return True
    
    def get_all_frames(self) -> list[bytes]:
        """
        Get all frames from buffer and clear it.
        
        Returns:
            List of MP3 frame bytes
        """
        with self.lock:
            frames = list(self.buffer)
            self.buffer.clear()
            return frames
    
    def is_lagging(self) -> bool:
        """
        Check if client is lagging (dropping frames).
        
        Returns:
            True if client has dropped frames recently
        """
        return self.dropped_frames > 0


class HTTPConnectionManager:
    """
    Manages connected HTTP streaming clients with backpressure protection.
    
    Thread-safe connection management with broadcast capability.
    Each client has a ring buffer to prevent blocking playout.
    """
    
    def __init__(self, buffer_size: int = 50):
        """
        Initialize connection manager.
        
        Args:
            buffer_size: Maximum frames per client buffer (default: 50)
        """
        self.clients: Dict[socket.socket, Tuple[str, ClientBuffer]] = {}
        self.lock = threading.Lock()
        self.buffer_size = buffer_size
        logger.debug("HTTPConnectionManager initialized")
    
    def add_client(self, client_socket: socket.socket, address: str) -> None:
        """
        Add a client socket to the manager.
        
        Args:
            client_socket: Client socket to add
            address: Client IP address
        """
        with self.lock:
            self.clients[client_socket] = (address, ClientBuffer(max_size=self.buffer_size))
            logger.info(f"[STREAM] Client connected from {address} (total: {len(self.clients)})")
    
    def remove_client(self, client_socket: socket.socket, address: Optional[str] = None) -> None:
        """
        Remove a client socket from the manager.
        
        Args:
            client_socket: Client socket to remove
            address: Optional client address for logging
        """
        with self.lock:
            if client_socket in self.clients:
                client_addr, buffer = self.clients[client_socket]
                if buffer.dropped_frames > 0:
                    logger.warning(f"[STREAM] Client {client_addr} dropped {buffer.dropped_frames} frames")
                del self.clients[client_socket]
                logger.info(f"[STREAM] Client disconnected from {client_addr or address} (total: {len(self.clients)})")
    
    def broadcast(self, mp3_bytes: bytes) -> None:
        """
        Write MP3 frames to all connected sockets; drop dead ones.
        
        Uses per-client buffers to prevent backpressure. If a client's
        buffer is full, drops oldest frames and logs warning.
        
        This runs in the encoder reader thread, so blocking on sendall()
        is acceptable - it won't block the playout loop.
        
        Args:
            mp3_bytes: MP3 encoded audio data to broadcast
        """
        if not mp3_bytes:
            return
        
        dead_clients = []
        
        # Get snapshot of clients
        with self.lock:
            clients_to_write = list(self.clients.items())
        
        for client_socket, (address, buffer) in clients_to_write:
            try:
                # Add new frame to buffer (may drop oldest if full)
                was_dropped = not buffer.add_frame(mp3_bytes)
                
                if was_dropped:
                    # Client is lagging - log warning (only once per buffer cycle)
                    if buffer.dropped_frames == 1:  # First drop
                        logger.warning(f"[STREAM] Client {address} lagging, dropping frames")
                
                # Try to send all buffered frames
                frames_to_send = buffer.get_all_frames()
                for frame in frames_to_send:
                    try:
                        client_socket.sendall(frame)
                    except (socket.error, OSError, BrokenPipeError):
                        # Client disconnected during send
                        dead_clients.append(client_socket)
                        break
                
            except (socket.error, OSError, BrokenPipeError) as e:
                logger.debug(f"[STREAM] Client {address} write failed: {e}")
                dead_clients.append(client_socket)
            except Exception as e:
                logger.debug(f"[STREAM] Unexpected error writing to client {address}: {e}")
                dead_clients.append(client_socket)
        
        # Remove dead clients
        if dead_clients:
            with self.lock:
                for client in dead_clients:
                    if client in self.clients:
                        del self.clients[client]
                    try:
                        client.close()
                    except Exception:
                        pass
        
        if clients_to_write:
            logger.debug(f"[STREAM] Broadcasting {len(mp3_bytes)}-byte frame to {len(clients_to_write)} client(s)")
    
    def get_client_count(self) -> int:
        """
        Get number of connected clients.
        
        Returns:
            Number of active clients
        """
        with self.lock:
            return len(self.clients)
    
    def close_all(self) -> None:
        """Close all client connections."""
        with self.lock:
            for client_socket, (address, buffer) in self.clients.items():
                try:
                    client_socket.close()
                except Exception:
                    pass
            self.clients.clear()
        logger.info("[STREAM] All client connections closed")

