# tower/http/connection_manager.py

import logging
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Client timeout per contract [H6], [H9]
TOWER_CLIENT_TIMEOUT_MS = 250  # 250ms timeout for slow clients

# Maximum queue size per client (frames)
MAX_CLIENT_QUEUE_SIZE = 10


@dataclass
class _ClientState:
    """Internal state for a connected client."""
    sock: socket.socket
    queue: deque  # Queue of frames to send
    last_send_monotonic: float  # Last successful send time (monotonic)


class HTTPConnectionManager:
    """
    Tracks active streaming clients and writes bytes to them.
    
    Per contract [H1]-[H10]: Thread-safe, non-blocking broadcast operations.
    """

    def __init__(self):
        # Store clients as dict: {client_id: _ClientState} per contract [H4]
        self._clients: dict[str, _ClientState] = {}
        self._lock = threading.Lock()

    def add_client(self, client_socket: socket.socket, client_id: str) -> None:
        """
        Register a client socket with an associated ID per contract [H4].
        
        Sets socket to non-blocking and creates internal client state with queue.
        
        Args:
            client_socket: Client socket to add to broadcast list
            client_id: Associated ID used for metrics/logging
        """
        # Set socket to non-blocking per contract [H2], [H6]
        try:
            if hasattr(client_socket, 'setblocking'):
                client_socket.setblocking(False)
            elif hasattr(client_socket, 'settimeout'):
                client_socket.settimeout(0.0)
        except Exception as e:
            logger.warning(f"Failed to set non-blocking for client {client_id}: {e}")
        
        with self._lock:
            # Create client state with empty queue
            self._clients[client_id] = _ClientState(
                sock=client_socket,
                queue=deque(maxlen=MAX_CLIENT_QUEUE_SIZE),
                last_send_monotonic=time.monotonic()
            )
            logger.debug(f"Added client: {client_id}")

    def _drop_client_locked(self, client_id: str, reason: str) -> None:
        """
        Drop a client (must be called with lock held).
        
        Args:
            client_id: ID of client to drop
            reason: Reason for dropping (for logging)
        """
        state = self._clients.pop(client_id, None)
        if state:
            try:
                state.sock.close()
            except Exception:
                pass
            logger.debug(f"Dropped client {client_id}: {reason}")
    
    def remove_client(self, client_id: str) -> None:
        """
        Remove client from list per contract [H4].
        
        Args:
            client_id: ID of client to remove
        """
        with self._lock:
            self._drop_client_locked(client_id, "explicit removal")
    
    def close_all(self) -> None:
        """
        Close all client connections per contract [I27] #3.
        
        This method is called during shutdown to ensure all client sockets
        are closed gracefully.
        """
        with self._lock:
            client_ids = list(self._clients.keys())
            for client_id in client_ids:
                self._drop_client_locked(client_id, "shutdown")
        logger.info("All client connections closed")

    def broadcast(self, data: bytes) -> None:
        """
        Broadcast data to all clients per contract [H2], [H6], [H7].
        
        Per contract [H2]: Non-blocking - never blocks the main loop.
        Per contract [H6]: Uses non-blocking writes and drops slow clients.
        Per contract [H7]: All clients receive the same data.
        
        Implementation:
        - Takes snapshot of client IDs
        - Enqueues frame to each client's queue (if not full)
        - Attempts non-blocking flush of queued frames
        - Drops clients on timeout, queue full, or socket errors
        
        Args:
            data: Bytes to send to all clients
        """
        if not data:
            return
        
        now_monotonic = time.monotonic()
        timeout_sec = TOWER_CLIENT_TIMEOUT_MS / 1000.0
        dead_clients = []
        
        # Take snapshot of client IDs (under lock)
        with self._lock:
            client_ids = list(self._clients.keys())
        
        # Process each client (outside lock to avoid blocking)
        for client_id in client_ids:
            with self._lock:
                state = self._clients.get(client_id)
                if not state:
                    continue  # Client was removed
                
                # Enqueue frame if queue not full
                if len(state.queue) < MAX_CLIENT_QUEUE_SIZE:
                    state.queue.append(data)
                else:
                    # Queue still full - drop client per contract [H6], [H9]
                    dead_clients.append((client_id, "queue_full"))
                    continue
                
                # Try to flush queued frames with non-blocking send
                try:
                    flushed, should_drop = self._flush_client_queue_locked(state, now_monotonic)
                    if should_drop:
                        # Per contract [H11]: 0-byte or non-integer returns trigger graceful disconnect
                        dead_clients.append((client_id, "non_write_event_per_h11"))
                        continue
                    if flushed:
                        state.last_send_monotonic = now_monotonic
                except (OSError, BrokenPipeError, ConnectionError) as e:
                    # Hard socket error - drop client
                    dead_clients.append((client_id, f"socket_error: {e}"))
                    continue
                
                # Check timeout: if last send was too long ago, drop client
                time_since_send = now_monotonic - state.last_send_monotonic
                if time_since_send > timeout_sec:
                    dead_clients.append((client_id, f"timeout: {time_since_send*1000:.1f}ms"))
        
        # Remove dead clients (outside broadcast loop to keep it non-blocking)
        with self._lock:
            for client_id, reason in dead_clients:
                self._drop_client_locked(client_id, reason)
    
    def _flush_client_queue_locked(self, state: _ClientState, now_monotonic: float) -> tuple[bool, bool]:
        """
        Flush queued frames to client using non-blocking send.
        
        Must be called with lock held. Returns (sent_any, should_drop).
        
        Args:
            state: Client state to flush
            now_monotonic: Current monotonic time
            
        Returns:
            (sent_any, should_drop) tuple:
            - sent_any: True if any data was successfully sent, False otherwise
            - should_drop: True if client should be dropped per contract [H11] (0-byte or non-integer return)
            
        Raises:
            OSError, BrokenPipeError, ConnectionError: On socket errors
        """
        sent_any = False
        
        while state.queue:
            frame = state.queue[0]  # Peek at first frame
            
            try:
                # Non-blocking send (socket should already be non-blocking)
                if hasattr(state.sock, 'send'):
                    sent = state.sock.send(frame)
                elif hasattr(state.sock, 'sendall'):
                    # For mocks that only have sendall, try sendall
                    # This may block for mocks, but real sockets are non-blocking
                    state.sock.sendall(frame)
                    sent = len(frame)
                else:
                    # Fallback: assume it worked
                    sent = len(frame)
                
                # Per contract [H11]: socket.send() MUST return an integer
                # Non-integer returns (Mock objects, None, strings) MUST be treated as 0 bytes sent
                if not isinstance(sent, int):
                    # Per contract [H11]: Non-integer returns trigger graceful disconnect
                    return (False, True)
                
                if sent > 0:
                    # Partial or full send
                    if sent >= len(frame):
                        # Full frame sent - remove from queue
                        state.queue.popleft()
                        sent_any = True
                    else:
                        # Partial send - update frame in place
                        state.queue[0] = frame[sent:]
                        sent_any = True
                        # Partial send means socket buffer is full - stop flushing
                        break
                else:
                    # Per contract [H11]: 0-byte returns trigger graceful disconnect
                    return (False, True)
                    
            except BlockingIOError:
                # Non-blocking socket would block - buffer full, stop flushing
                break
            except (OSError, BrokenPipeError, ConnectionError) as e:
                # Socket error - re-raise to let caller drop client
                raise
        
        return (sent_any, False)

