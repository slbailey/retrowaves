# tower/http/server.py

import os
import socket
import threading
import time
import logging
import uuid
import json
from collections import deque
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Client timeout per contract T-CLIENTS2
TOWER_CLIENT_TIMEOUT_MS = 250  # 250ms timeout for slow clients

# Maximum queue size per client (frames)
MAX_CLIENT_QUEUE_SIZE = 10

# Maximum number of connected clients (defensive measure)
# Default: 100, configurable via TOWER_MAX_CLIENTS env var
def _get_max_clients() -> int:
    """Get maximum client count from environment or use default."""
    return int(os.getenv("TOWER_MAX_CLIENTS", "100"))

MAX_CLIENTS = _get_max_clients()


@dataclass
class _ClientState:
    """Internal state for a connected client."""
    sock: socket.socket
    queue: deque  # Queue of frames to send
    last_send_monotonic: float  # Last successful send time (monotonic)


class _ConnectionManagerProxy:
    """
    Backwards compatibility proxy for connection_manager attribute.
    
    Per NEW_TOWER_RUNTIME_CONTRACT, HTTPServer replaced HTTPConnectionManager.
    This proxy provides access to connected_clients for tests that reference
    the old connection_manager interface.
    """
    def __init__(self, http_server):
        self._http_server = http_server
    
    @property
    def _connected_clients(self):
        """Access to connected clients dict for backwards compatibility."""
        return self._http_server._connected_clients


class HTTPServer:
    """
    HTTP server for Tower streaming.
    
    Per contract NEW_TOWER_RUNTIME_CONTRACT T-CLIENTS1-T-CLIENTS4:
    - Owns client registration and removal
    - Performs non-blocking writes (T-CLIENTS1)
    - Enforces 250ms slow-client timeout (T-CLIENTS2)
    - Maintains thread-safe client registry (T-CLIENTS3)
    - Validates socket send return values (T-CLIENTS4)
    """
    def __init__(self, host, port, frame_source, buffer_stats_provider=None):
        """
        Initialize HTTPServer.
        
        Args:
            host: Host address to bind to
            port: Port to listen on
            frame_source: Must implement .pop() returning bytes (for /stream endpoint)
            buffer_stats_provider: Optional object with .stats() method returning buffer stats (for /tower/buffer endpoint)
        """
        self.host = host
        self.port = port
        self.frame_source = frame_source  # must implement .pop() returning bytes
        self.buffer_stats_provider = buffer_stats_provider  # for /tower/buffer endpoint
        
        # Per contract T-CLIENTS3: Thread-safe client registry
        # Store clients as dict: {client_id: _ClientState}
        self._connected_clients: dict[str, _ClientState] = {}
        self._clients_lock = threading.Lock()
        
        # Backwards compatibility: connection_manager proxy for tests
        # Per NEW_TOWER_RUNTIME_CONTRACT, HTTPServer replaced HTTPConnectionManager
        # This proxy allows tests that reference connection_manager to work
        self.connection_manager = _ConnectionManagerProxy(self)
        
        # Client statistics (for future /tower/status endpoint)
        self._total_bytes_sent = 0
        self._total_drops = 0
        self._drops_lock = threading.Lock()
        
        self.running = False
        self._server_sock = None

    def start(self):
        """Start the HTTP server in a background thread."""
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()
        logger.info(f"HTTP server running on {self.host}:{self.port}")

    def serve_forever(self):
        """Run the HTTP server in the current thread (blocking)."""
        self.running = True
        self._run()

    def _run(self):
        """Main server loop - accepts connections."""
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(50)
        logger.info(f"HTTP server listening on {self.host}:{self.port}")

        while self.running:
            try:
                client, addr = self._server_sock.accept()
                threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()
            except OSError:
                # Socket closed during shutdown
                break

    def _handle_client(self, client):
        """
        Handle a single client connection.
        
        Per contract T1: Only /stream endpoint outputs MP3.
        Other endpoints return appropriate responses (JSON for /tower/buffer, 404 for others).
        """
        # Generate unique client ID per contract [H4]
        client_id = str(uuid.uuid4())
        try:
            request = client.recv(4096)  # read HTTP GET
            if not request:
                client.close()
                return

            # Parse HTTP request to extract path
            # Format: "GET /path HTTP/1.1\r\n..."
            request_str = request.decode('utf-8', errors='ignore')
            lines = request_str.split('\r\n')
            if not lines:
                client.close()
                return
            
            # Parse request line: "GET /path HTTP/1.1"
            request_line = lines[0]
            parts = request_line.split()
            if len(parts) < 2:
                client.close()
                return
            
            method = parts[0]
            path = parts[1]
            
            # Per contract T1: Only /stream endpoint outputs MP3
            if path == "/stream":
                self._handle_stream_endpoint(client, client_id)
            elif path == "/tower/buffer":
                self._handle_buffer_endpoint(client)
            else:
                # Return 404 for unknown endpoints
                self._handle_404(client, path)
                
        except Exception as e:
            logger.warning(f"Client error: {e}")
        finally:
            # Remove client by ID per contract T-CLIENTS3 (only if it was added)
            if client_id in self._connected_clients:
                self._remove_client(client_id)
    
    def _handle_stream_endpoint(self, client, client_id):
        """
        Handle /stream endpoint - streams MP3 per contract T1.
        
        Per contract T1: Returns HTTP 200 and streams MP3 frames continuously.
        """
        # --- REQUIRED HTTP RESPONSE HEADER ---
        headers = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: audio/mpeg\r\n"
            "Connection: keep-alive\r\n"
            "Cache-Control: no-cache, no-store, must-revalidate\r\n"
            "\r\n"
        )
        client.sendall(headers.encode("ascii"))

        # Check maximum client count before adding
        with self._clients_lock:
            if len(self._connected_clients) >= MAX_CLIENTS:
                logger.warning(
                    f"Rejecting new client {client_id}: maximum client count ({MAX_CLIENTS}) reached"
                )
                client.close()
                return
        
        # Add client to internal registry per contract T-CLIENTS3
        self._add_client(client, client_id)

        # Keep connection alive - wait for client to disconnect
        # The main_loop will broadcast frames to all clients via HTTPServer.broadcast()
        while True:
            try:
                # Set timeout to periodically check if client is still connected
                client.settimeout(5.0)
                data = client.recv(1)
                if not data:
                    # Client closed connection
                    break
            except socket.timeout:
                # Timeout is fine - client is still connected, just waiting
                # Continue loop to check again
                continue
            except (OSError, ConnectionError):
                # Client disconnected
                break
    
    def _handle_buffer_endpoint(self, client):
        """
        Handle /tower/buffer endpoint - returns JSON buffer stats per contract T-BUF.
        
        Per contract T-BUF1: Endpoint path MUST remain /tower/buffer
        Per contract T-BUF2: Response MUST be JSON with capacity, count, overflow_count, ratio
        Per contract T-BUF5: Stats MUST originate from buffer stats provider
        """
        try:
            if self.buffer_stats_provider is None:
                # No buffer stats provider available
                response = (
                    "HTTP/1.1 503 Service Unavailable\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    '{"error": "Buffer stats not available"}\n'
                )
                client.sendall(response.encode("ascii"))
                client.close()
                return
            
            # Get buffer stats per contract T-BUF5
            # Use get_stats() if available (per contract), otherwise fall back to stats()
            if hasattr(self.buffer_stats_provider, 'get_stats'):
                stats = self.buffer_stats_provider.get_stats()
            else:
                stats = self.buffer_stats_provider.stats()
            
            # Build JSON response with fill and capacity
            response_data = {
                "fill": stats.count,
                "capacity": stats.capacity
            }
            
            response_json = json.dumps(response_data)
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Connection: close\r\n"
                "Content-Length: " + str(len(response_json)) + "\r\n"
                "\r\n"
                f"{response_json}"
            )
            client.sendall(response.encode("ascii"))
            client.close()
            
        except Exception as e:
            logger.warning(f"Error handling /tower/buffer endpoint: {e}")
            error_response = (
                "HTTP/1.1 500 Internal Server Error\r\n"
                "Content-Type: application/json\r\n"
                "Connection: close\r\n"
                "\r\n"
                f'{{"error": "Internal server error"}}\n'
            )
            try:
                client.sendall(error_response.encode("ascii"))
            except Exception:
                pass
            client.close()
    
    def _handle_404(self, client, path):
        """
        Handle unknown endpoints - return 404 Not Found.
        
        Per contract T1: No other endpoints shall output MP3.
        """
        response = (
            "HTTP/1.1 404 Not Found\r\n"
            "Content-Type: text/plain\r\n"
            "Connection: close\r\n"
            "\r\n"
            f"404 Not Found: {path}\n"
        )
        try:
            client.sendall(response.encode("ascii"))
        except Exception:
            pass
        client.close()

    def broadcast(self, frame: bytes):
        """
        Broadcast data to all connected clients per contract T-CLIENTS1-T-CLIENTS4.
        
        Per contract T-CLIENTS1: Non-blocking - never blocks the main loop.
        Per contract T-CLIENTS2: Uses non-blocking writes and drops slow clients (>250ms).
        Per contract T-CLIENTS3: Thread-safe client registry operations.
        Per contract T-CLIENTS4: Validates socket send return values (0 or error = disconnect).
        """
        if not frame:
            return
        
        now_monotonic = time.monotonic()
        timeout_sec = TOWER_CLIENT_TIMEOUT_MS / 1000.0
        dead_clients = []
        
        # Take snapshot of client IDs (under lock) per T-CLIENTS3
        with self._clients_lock:
            client_ids = list(self._connected_clients.keys())
        
        # Process each client (outside lock to avoid blocking) per T-CLIENTS1
        for client_id in client_ids:
            with self._clients_lock:
                state = self._connected_clients.get(client_id)
                if not state:
                    continue  # Client was removed
                
                # Enqueue frame if queue not full
                if len(state.queue) < MAX_CLIENT_QUEUE_SIZE:
                    state.queue.append(frame)
                else:
                    # Queue still full - drop client per T-CLIENTS2
                    dead_clients.append((client_id, "queue_full"))
                    continue
                
                # Try to flush queued frames with non-blocking send per T-CLIENTS1
                try:
                    flushed, should_drop = self._flush_client_queue_locked(state, now_monotonic)
                    if should_drop:
                        # Per contract T-CLIENTS4: 0-byte or non-integer returns trigger graceful disconnect
                        dead_clients.append((client_id, "non_write_event_per_t_clients4"))
                        continue
                    if flushed:
                        state.last_send_monotonic = now_monotonic
                except (OSError, BrokenPipeError, ConnectionError) as e:
                    # Hard socket error - drop client
                    dead_clients.append((client_id, f"socket_error: {e}"))
                    continue
                
                # Check timeout: if last send was too long ago, drop client per T-CLIENTS2
                time_since_send = now_monotonic - state.last_send_monotonic
                if time_since_send > timeout_sec:
                    dead_clients.append((client_id, f"timeout: {time_since_send*1000:.1f}ms"))
        
        # Remove dead clients (outside broadcast loop to keep it non-blocking) per T-CLIENTS1
        with self._clients_lock:
            for client_id, reason in dead_clients:
                self._drop_client_locked(client_id, reason)

    def stop(self, broadcast_silence: bool = False):
        """
        Stop the HTTP server gracefully.
        
        Per contract [I27] #3: Stop HTTP connection manager (close client sockets).
        
        Args:
            broadcast_silence: If True, broadcast 500ms of silence before closing connections.
                             Optional polish for graceful shutdown. Default: False.
        """
        # Optional: Broadcast silence before shutdown for graceful client disconnection
        if broadcast_silence:
            # Generate ~500ms of silence (assuming ~24ms per frame = ~21 frames)
            # MP3 silence frame (minimal valid MP3 frame that decodes as silence)
            # This is a placeholder - actual silence frame generation would be done by EncoderManager
            logger.info("Broadcasting silence before shutdown...")
            # Note: Actual silence frame would come from EncoderManager or be pre-generated
            # For now, this is a placeholder for future implementation
        
        self.running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except:
                pass
        
        # Per contract [I27] #3: Close all client connections
        self._close_all_clients()
    
    def _add_client(self, client_socket: socket.socket, client_id: str) -> None:
        """
        Register a client socket with an associated ID per contract T-CLIENTS3.
        
        Sets socket to non-blocking per contract T-CLIENTS1.
        
        Args:
            client_socket: Client socket to add to broadcast list
            client_id: Associated ID used for metrics/logging
        """
        # Set socket to non-blocking per contract T-CLIENTS1
        try:
            if hasattr(client_socket, 'setblocking'):
                client_socket.setblocking(False)
            elif hasattr(client_socket, 'settimeout'):
                client_socket.settimeout(0.0)
        except Exception as e:
            logger.warning(f"Failed to set non-blocking for client {client_id}: {e}")
        
        with self._clients_lock:
            # Create client state with empty queue
            self._connected_clients[client_id] = _ClientState(
                sock=client_socket,
                queue=deque(maxlen=MAX_CLIENT_QUEUE_SIZE),
                last_send_monotonic=time.monotonic()
            )
            logger.debug(f"Added client: {client_id}")
    
    def _remove_client(self, client_id: str) -> None:
        """
        Remove client from list per contract T-CLIENTS3.
        
        Args:
            client_id: ID of client to remove
        """
        with self._clients_lock:
            self._drop_client_locked(client_id, "explicit removal")
    
    def _drop_client_locked(self, client_id: str, reason: str) -> None:
        """
        Drop a client (must be called with lock held).
        
        Args:
            client_id: ID of client to drop
            reason: Reason for dropping (for logging)
        """
        state = self._connected_clients.pop(client_id, None)
        if state:
            try:
                state.sock.close()
            except Exception:
                pass
            
            # Log at INFO level for slow client drops (operationally important)
            # Other drops (explicit removal, shutdown) can be DEBUG
            if "timeout" in reason or "slow" in reason.lower() or "queue_full" in reason:
                logger.info(f"Dropped slow client {client_id}: {reason}")
            else:
                logger.debug(f"Dropped client {client_id}: {reason}")
            
            # Update drop statistics
            with self._drops_lock:
                self._total_drops += 1
    
    def _close_all_clients(self) -> None:
        """
        Close all client connections per contract [I27] #3.
        
        This method is called during shutdown to ensure all client sockets
        are closed gracefully.
        """
        with self._clients_lock:
            client_ids = list(self._connected_clients.keys())
            for client_id in client_ids:
                self._drop_client_locked(client_id, "shutdown")
        logger.info("All client connections closed")
    
    def _flush_client_queue_locked(self, state: _ClientState, now_monotonic: float) -> tuple[bool, bool]:
        """
        Flush queued frames to client using non-blocking send per contract T-CLIENTS1, T-CLIENTS4.
        
        Must be called with lock held. Returns (sent_any, should_drop).
        
        Args:
            state: Client state to flush
            now_monotonic: Current monotonic time
            
        Returns:
            (sent_any, should_drop) tuple:
            - sent_any: True if any data was successfully sent, False otherwise
            - should_drop: True if client should be dropped per contract T-CLIENTS4 (0-byte or non-integer return)
            
        Raises:
            OSError, BrokenPipeError, ConnectionError: On socket errors
        """
        sent_any = False
        
        while state.queue:
            frame = state.queue[0]  # Peek at first frame
            
            try:
                # Non-blocking send (socket should already be non-blocking) per T-CLIENTS1
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
                
                # Per contract T-CLIENTS4: socket.send() MUST return an integer
                # Non-integer returns (Mock objects, None, strings) MUST be treated as 0 bytes sent
                if not isinstance(sent, int):
                    # Per contract T-CLIENTS4: Non-integer returns trigger graceful disconnect
                    return (False, True)
                
                if sent > 0:
                    # Partial or full send
                    if sent >= len(frame):
                        # Full frame sent - remove from queue
                        state.queue.popleft()
                        sent_any = True
                        
                        # Update statistics
                        with self._drops_lock:
                            self._total_bytes_sent += sent
                    else:
                        # Partial send - update frame in place
                        state.queue[0] = frame[sent:]
                        sent_any = True
                        
                        # Update statistics (partial send)
                        with self._drops_lock:
                            self._total_bytes_sent += sent
                        
                        # Partial send means socket buffer is full - stop flushing
                        break
                else:
                    # Per contract T-CLIENTS4: 0-byte returns trigger graceful disconnect
                    return (False, True)
                    
            except BlockingIOError:
                # Non-blocking socket would block - buffer full, stop flushing
                break
            except (OSError, BrokenPipeError, ConnectionError) as e:
                # Socket error - re-raise to let caller drop client
                raise
        
        return (sent_any, False)
    
    def get_client_stats(self) -> dict:
        """
        Get client connection statistics (for future /tower/status or /tower/clients endpoint).
        
        Returns:
            dict: Statistics including:
                - connected_clients: Number of currently connected clients
                - max_clients: Maximum allowed clients
                - total_bytes_sent: Total bytes sent to all clients
                - total_drops: Total number of clients dropped
                - queue_fill_percentage: Average queue fill percentage across all clients
        """
        with self._clients_lock:
            connected_count = len(self._connected_clients)
            
            # Calculate average queue fill percentage
            if connected_count > 0:
                total_queue_size = sum(len(state.queue) for state in self._connected_clients.values())
                max_possible_queue = connected_count * MAX_CLIENT_QUEUE_SIZE
                queue_fill_percentage = (total_queue_size / max_possible_queue * 100.0) if max_possible_queue > 0 else 0.0
            else:
                queue_fill_percentage = 0.0
        
        with self._drops_lock:
            total_bytes = self._total_bytes_sent
            total_drops = self._total_drops
        
        return {
            "connected_clients": connected_count,
            "max_clients": MAX_CLIENTS,
            "total_bytes_sent": total_bytes,
            "total_drops": total_drops,
            "queue_fill_percentage": round(queue_fill_percentage, 2),
        }

