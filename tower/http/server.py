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

from tower.http.event_buffer import EventBuffer
from tower.http.websocket import (
    parse_upgrade_request,
    create_upgrade_response,
    encode_websocket_frame,
    decode_websocket_frame,
    create_close_frame,
    WebSocketError
)

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
    def __init__(self, host, port, frame_source, buffer_stats_provider=None, event_buffer_capacity=1000):
        """
        Initialize HTTPServer.
        
        Args:
            host: Host address to bind to
            port: Port to listen on
            frame_source: Must implement .pop() returning bytes (for /stream endpoint)
            buffer_stats_provider: Optional object with .stats() method returning buffer stats (for /tower/buffer endpoint)
            event_buffer_capacity: Maximum number of events to store (default: 1000)
        """
        self.host = host
        self.port = port
        self.frame_source = frame_source  # must implement .pop() returning bytes
        self.buffer_stats_provider = buffer_stats_provider  # for /tower/buffer endpoint
        
        # Per contract T-CLIENTS3: Thread-safe client registry
        # Store clients as dict: {client_id: _ClientState}
        self._connected_clients: dict[str, _ClientState] = {}
        self._clients_lock = threading.Lock()
        
        # Event buffer per contract T-EVENTS2
        self.event_buffer = EventBuffer(capacity=event_buffer_capacity)
        
        # Track last broadcasted event ID to prevent duplicate broadcasts
        self._last_broadcasted_event_id: Optional[str] = None
        self._last_broadcasted_lock = threading.Lock()
        
        # Event streaming clients (for /tower/events WebSocket endpoint) per contract T-EXPOSE1
        self._event_clients: dict[str, socket.socket] = {}
        self._event_clients_lock = threading.Lock()
        
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
            elif path == "/tower/events/ingest":
                self._handle_events_ingest_endpoint(client, method, request)
            elif path.startswith("/tower/events"):
                # Check if this is a WebSocket upgrade request
                request_str = request.decode('utf-8', errors='ignore')
                ws_info = parse_upgrade_request(request_str)
                
                if ws_info:
                    # WebSocket upgrade request
                    path_parts = ws_info['path'].split("?")
                    base_path = path_parts[0]
                    query_params = {}
                    if len(path_parts) > 1:
                        # Parse query string
                        for param in path_parts[1].split("&"):
                            if "=" in param:
                                key, value = param.split("=", 1)
                                query_params[key] = value
                    
                    if base_path == "/tower/events/recent":
                        self._handle_websocket_events_recent(client, client_id, ws_info['sec-websocket-key'], query_params)
                    elif base_path == "/tower/events":
                        self._handle_websocket_events(client, client_id, ws_info['sec-websocket-key'], query_params)
                    else:
                        self._handle_404(client, path)
                else:
                    # Not a WebSocket upgrade - return 400 (WebSocket required)
                    response = (
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Content-Type: text/plain\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        "WebSocket upgrade required\r\n"
                    )
                    try:
                        client.sendall(response.encode("ascii"))
                    except Exception:
                        pass
                    client.close()
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
    
    def _handle_events_ingest_endpoint(self, client, method, request):
        """
        Handle POST /tower/events/ingest endpoint for event ingestion.
        
        Per contract T-EVENTS1: Accepts Station heartbeat events via HTTP POST.
        Per contract T-EVENTS6: Non-blocking reception.
        Per contract T-EVENTS7: Validates events.
        """
        if method != "POST":
            response = (
                "HTTP/1.1 405 Method Not Allowed\r\n"
                "Content-Type: application/json\r\n"
                "Connection: close\r\n"
                "\r\n"
                '{"error": "Method not allowed. Use POST."}\n'
            )
            try:
                client.sendall(response.encode("ascii"))
            except Exception:
                pass
            client.close()
            return
        
        try:
            # ====================================================================
            # Byte-precise HTTP POST body parsing
            # Per contract T-EVENTS6: Non-blocking, complete body retrieval
            # ====================================================================
            
            # Step 1: Operate on bytes, not decoded strings
            data = request  # data is already bytes from client.recv()
            
            # Step 2: Handle header fragmentation - find header/body separator
            header_end = data.find(b"\r\n\r\n")
            max_header_reads = 50  # Allow for slow network chunking (was 10, too low)
            max_header_size = 65536  # 64 KB max header size to prevent DoS
            header_reads = 0
            
            # Save original timeout to restore later (if socket supports it)
            try:
                original_timeout = client.gettimeout()
            except Exception:
                original_timeout = None
            
            # Set timeout once for header reading section (not per iteration)
            try:
                client.settimeout(1.0)  # 1 second timeout (was 0.1s, too short for network/load)
            except Exception:
                pass  # Ignore if settimeout fails
            
            # If headers are incomplete, continue reading until \r\n\r\n is found
            while header_end < 0 and header_reads < max_header_reads:
                try:
                    chunk = client.recv(4096)
                    if not chunk:
                        # Connection closed before headers complete
                        response = (
                            "HTTP/1.1 400 Bad Request\r\n"
                            "Content-Type: application/json\r\n"
                            "Connection: close\r\n"
                            "\r\n"
                            '{"error": "Incomplete headers"}\n'
                        )
                        try:
                            client.sendall(response.encode("ascii"))
                        except Exception:
                            pass
                        client.close()
                        return
                    data += chunk
                    
                    # Problem 3: Enforce max header size to prevent DoS
                    if len(data) > max_header_size:
                        # Header too large, reject to prevent memory exhaustion
                        response = (
                            "HTTP/1.1 413 Payload Too Large\r\n"
                            "Connection: close\r\n"
                            "\r\n"
                        )
                        try:
                            client.sendall(response.encode("ascii"))
                        except Exception:
                            pass
                        client.close()
                        return
                    
                    header_end = data.find(b"\r\n\r\n")
                    header_reads += 1
                except socket.timeout:
                    # Timeout reading headers - reject request
                    response = (
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Content-Type: application/json\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        '{"error": "Header read timeout"}\n'
                    )
                    try:
                        client.sendall(response.encode("ascii"))
                    except Exception:
                        pass
                    client.close()
                    return
                except Exception:
                    break
            
            if header_end < 0:
                # Headers never completed - restore timeout before closing
                try:
                    if original_timeout is not None:
                        client.settimeout(original_timeout)
                except Exception:
                    pass
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    '{"error": "Incomplete headers"}\n'
                )
                try:
                    client.sendall(response.encode("ascii"))
                except Exception:
                    pass
                client.close()
                return
            
            # Step 3: Parse Content-Length from header bytes
            header_bytes = data[:header_end]
            content_length = None
            
            # Extract Content-Length header
            for line in header_bytes.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    try:
                        # Extract value after colon
                        value = line.split(b":", 1)[1].strip()
                        content_length = int(value)
                        if content_length < 0:
                            content_length = None  # Invalid negative value
                        logger.debug(f"[EVENTS_INGEST] Parsed Content-Length: {content_length}")
                        break
                    except (ValueError, IndexError):
                        # Invalid Content-Length format
                        content_length = None
                        logger.debug(f"[EVENTS_INGEST] Invalid Content-Length format: {line}")
                        break
            
            if content_length is None:
                # No Content-Length header - restore timeout and reject request
                try:
                    if original_timeout is not None:
                        client.settimeout(original_timeout)
                except Exception:
                    pass
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    '{"error": "Content-Length header required"}\n'
                )
                try:
                    client.sendall(response.encode("ascii"))
                except Exception:
                    pass
                client.close()
                return
            
            # Step 4 & 5: Read body until exactly Content-Length bytes have been received
            # Extract any body bytes already in the first recv()
            body_start = header_end + 4  # Skip \r\n\r\n
            body_bytes = data[body_start:]
            
            logger.debug(f"[EVENTS_INGEST] Initial body bytes from first recv: {len(body_bytes)}/{content_length}")
            
            # Set timeout once for body reading section (not per iteration)
            try:
                client.settimeout(0.5)  # 0.5 second timeout (was 0.1s, too short under load)
            except Exception:
                pass  # Ignore if settimeout fails
            
            # Read remaining body bytes if needed
            max_body_reads = 100  # Prevent infinite loop
            body_reads = 0
            
            while len(body_bytes) < content_length and body_reads < max_body_reads:
                try:
                    remaining = content_length - len(body_bytes)
                    chunk = client.recv(min(remaining, 4096))  # Don't read more than needed
                    if not chunk:
                        # Connection closed before body complete
                        response = (
                            "HTTP/1.1 400 Bad Request\r\n"
                            "Content-Type: application/json\r\n"
                            "Connection: close\r\n"
                            "\r\n"
                            '{"error": "Incomplete request body"}\n'
                        )
                        try:
                            client.sendall(response.encode("ascii"))
                        except Exception:
                            pass
                        client.close()
                        return
                    body_bytes += chunk
                    body_reads += 1
                except socket.timeout:
                    # Timeout reading body - reject request
                    response = (
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Content-Type: application/json\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        '{"error": "Body read timeout"}\n'
                    )
                    try:
                        client.sendall(response.encode("ascii"))
                    except Exception:
                        pass
                    client.close()
                    return
                except Exception as e:
                    logger.warning(f"Error reading request body: {e}")
                    response = (
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Content-Type: application/json\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        '{"error": "Error reading request body"}\n'
                    )
                    try:
                        client.sendall(response.encode("ascii"))
                    except Exception:
                        pass
                    client.close()
                    return
            
            # Step 6: Verify we have exactly Content-Length bytes
            if len(body_bytes) != content_length:
                # Body length mismatch - restore timeout before closing
                try:
                    if original_timeout is not None:
                        client.settimeout(original_timeout)
                except Exception:
                    pass
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    f'{{"error": "Body length mismatch: expected {content_length}, got {len(body_bytes)}"}}\n'
                )
                try:
                    client.sendall(response.encode("ascii"))
                except Exception:
                    pass
                client.close()
                return
            
            # Restore original socket timeout before processing
            try:
                if original_timeout is not None:
                    client.settimeout(original_timeout)
            except Exception:
                pass  # Ignore errors restoring timeout
            
            # Step 7: Only after full body is received, decode as UTF-8 and JSON-parse
            logger.debug(f"[EVENTS_INGEST] Body complete: {len(body_bytes)} bytes, decoding UTF-8")
            try:
                body_str = body_bytes.decode("utf-8", errors="strict")
            except UnicodeDecodeError as e:
                # Invalid UTF-8 encoding
                logger.warning(f"[EVENTS_INGEST] Invalid UTF-8 in request body: {e}")
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    '{"error": "Invalid UTF-8 encoding"}\n'
                )
                try:
                    client.sendall(response.encode("ascii"))
                except Exception:
                    pass
                client.close()
                return
            
            logger.debug(f"[EVENTS_INGEST] UTF-8 decoded, parsing JSON: {len(body_str)} chars")
            try:
                event_data = json.loads(body_str)
                logger.debug(f"[EVENTS_INGEST] JSON parsed successfully: {event_data.get('event_type', 'unknown')}")
            except json.JSONDecodeError as e:
                # Invalid JSON - per contract T-EVENTS7: reject invalid events
                logger.warning(f"[EVENTS_INGEST] Invalid JSON in request body: {e}, body: {body_str[:100]}")
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    '{"error": "Invalid JSON"}\n'
                )
                try:
                    client.sendall(response.encode("ascii"))
                except Exception:
                    pass
                client.close()
                return
            
            # Extract event fields
            event_type = event_data.get("event_type")
            timestamp = event_data.get("timestamp")
            metadata = event_data.get("metadata", {})
            
            # Validate and store event per contract T-EVENTS7
            success = self.event_buffer.add_event(event_type, timestamp, metadata)
            
            if success:
                response = (
                    "HTTP/1.1 204 No Content\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                # Broadcast to streaming clients per contract T-EXPOSE1.7 (immediate flush)
                self._broadcast_event_to_streaming_clients()
            else:
                # Invalid event - silently dropped per contract T-EVENTS7
                response = (
                    "HTTP/1.1 204 No Content\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
            
            client.sendall(response.encode("ascii"))
            client.close()
            
        except Exception as e:
            logger.warning(f"Error handling /tower/events/ingest: {e}")
            response = (
                "HTTP/1.1 500 Internal Server Error\r\n"
                "Content-Type: application/json\r\n"
                "Connection: close\r\n"
                "\r\n"
                '{"error": "Internal server error"}\n'
            )
            try:
                client.sendall(response.encode("ascii"))
            except Exception:
                pass
            client.close()
    
    def _handle_websocket_events(self, client, client_id, sec_websocket_key, query_params):
        """
        Handle WebSocket upgrade and streaming for /tower/events endpoint.
        
        Per contract T-EXPOSE1:
        - Accepts WebSocket upgrade requests from clients
        - Streams heartbeat events immediately as they are stored
        - Supports multiple simultaneous WS clients
        - Broadcasts events to all connected clients without delay
        """
        # Parse query parameters
        event_type_filter = query_params.get("event_type")
        since = query_params.get("since")
        since_timestamp = None
        if since:
            try:
                since_timestamp = float(since)
            except ValueError:
                # Reject upgrade with 400
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    '{"error": "Invalid since parameter"}\n'
                )
                try:
                    client.sendall(response.encode("ascii"))
                except Exception:
                    pass
                client.close()
                return
        
        # Perform WebSocket upgrade
        try:
            upgrade_response = create_upgrade_response(sec_websocket_key)
            client.sendall(upgrade_response)
        except Exception as e:
            logger.warning(f"Error sending WebSocket upgrade response: {e}")
            client.close()
            return
        
        # Get the timestamp of the most recent event BEFORE adding client to prevent race condition
        # This ensures we don't receive events via broadcast that we'll also get from the stream
        with self._event_clients_lock:
            # Get the most recent event timestamp to use as a cutoff
            recent_result = self.event_buffer.get_recent_events(limit=1)
            cutoff_timestamp = None
            cutoff_event_id = None
            if recent_result["events"]:
                # Use a timestamp slightly after the most recent event to ensure we don't duplicate it
                cutoff_timestamp = recent_result["events"][0].get("tower_received_at", 0) + 0.001
                cutoff_event_id = recent_result["events"][0].get("event_id")
        
        # Track which events we've sent to this client to prevent duplicates
        sent_event_ids = set()
        
        # Send existing events that match filters (BEFORE adding client to avoid race condition)
        # Send all events up to (but not including) the cutoff timestamp
        try:
            for event in self.event_buffer.get_events_stream(
                event_type=event_type_filter,
                since=since_timestamp
            ):
                # Stop before events that will be sent via broadcast
                if cutoff_timestamp is not None and event.tower_received_at >= cutoff_timestamp:
                    break
                if not self.running:
                    break
                
                # Skip if we've already sent this event (defensive check)
                if event.event_id in sent_event_ids:
                    continue
                sent_event_ids.add(event.event_id)
                
                # Format as JSON message per contract T-EXPOSE1
                event_json = json.dumps({
                    "event_type": event.event_type,
                    "timestamp": event.timestamp,
                    "tower_received_at": event.tower_received_at,
                    "event_id": event.event_id,
                    "metadata": event.metadata
                })
                
                # Send WebSocket text frame
                try:
                    frame = encode_websocket_frame(event_json.encode('utf-8'), opcode=0x1)  # Text frame
                    client.sendall(frame)
                except (OSError, BrokenPipeError, ConnectionError):
                    # Client disconnected
                    break
        except Exception as e:
            logger.warning(f"Error sending initial events to client {client_id}: {e}")
        
        # Add client to event streaming clients per contract T-EXPOSE1.2
        # Do this AFTER sending initial events to avoid race condition with broadcasts
        with self._event_clients_lock:
            self._event_clients[client_id] = {
                'socket': client,
                'event_type_filter': event_type_filter,
                'since_timestamp': since_timestamp,
                'last_send_time': time.time(),
                'cutoff_timestamp': cutoff_timestamp,  # Track events received before connection
                'cutoff_event_id': cutoff_event_id,  # Track the specific event at cutoff
                'sent_event_ids': sent_event_ids  # Track which events we've already sent
            }
        
        # Keep connection alive and handle incoming frames (ping/pong, close)
        buffer = b''
        try:
            while self.running:
                try:
                    client.settimeout(1.0)
                    data = client.recv(4096)
                    if not data:
                        break
                    
                    buffer += data
                    
                    # Process WebSocket frames
                    while len(buffer) >= 2:
                        opcode, payload, consumed = decode_websocket_frame(buffer)
                        if opcode is None:
                            # Incomplete frame, wait for more data
                            break
                        
                        buffer = buffer[consumed:]
                        
                        if opcode == 0x8:  # Close frame
                            # Send close frame response
                            try:
                                close_frame = create_close_frame()
                                client.sendall(close_frame)
                            except Exception:
                                pass
                            break
                        elif opcode == 0x9:  # Ping frame
                            # Respond with pong
                            try:
                                pong_frame = encode_websocket_frame(payload, opcode=0xA)  # Pong
                                client.sendall(pong_frame)
                            except Exception:
                                pass
                        # Ignore other opcodes (text/binary from client)
                    
                    # Check for slow client (per T-CLIENTS2)
                    with self._event_clients_lock:
                        if client_id in self._event_clients:
                            last_send = self._event_clients[client_id]['last_send_time']
                            if time.time() - last_send > TOWER_CLIENT_TIMEOUT_MS / 1000.0:
                                # Client is slow, disconnect
                                break
                    
                except socket.timeout:
                    # Timeout is fine - check if we should disconnect slow client
                    continue
                except (OSError, BrokenPipeError, ConnectionError):
                    break
                    
        except Exception as e:
            logger.warning(f"Error in WebSocket connection to client {client_id}: {e}")
        finally:
            # Remove client
            with self._event_clients_lock:
                self._event_clients.pop(client_id, None)
            try:
                client.close()
            except Exception:
                pass
    
    def _handle_websocket_events_recent(self, client, client_id, sec_websocket_key, query_params):
        """
        Handle WebSocket upgrade and send recent events for /tower/events/recent endpoint.
        
        Per contract T-EXPOSE2:
        - Accepts WebSocket upgrade requests from clients
        - Sends the most recent N events immediately upon connection
        - Each event sent as a separate WebSocket text message
        """
        try:
            # Parse query parameters
            limit = 100  # Default per contract
            if "limit" in query_params:
                try:
                    limit = int(query_params["limit"])
                    if limit < 1:
                        limit = 100
                    if limit > 1000:
                        limit = 1000
                except ValueError:
                    limit = 100
            
            event_type_filter = query_params.get("event_type")
            since = query_params.get("since")
            since_timestamp = None
            if since:
                try:
                    since_timestamp = float(since)
                except ValueError:
                    # Reject upgrade with 400
                    response = (
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Content-Type: application/json\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        '{"error": "Invalid since parameter"}\n'
                    )
                    try:
                        client.sendall(response.encode("ascii"))
                    except Exception:
                        pass
                    client.close()
                    return
            
            # Perform WebSocket upgrade
            try:
                upgrade_response = create_upgrade_response(sec_websocket_key)
                client.sendall(upgrade_response)
            except Exception as e:
                logger.warning(f"Error sending WebSocket upgrade response: {e}")
                client.close()
                return
            
            # Get recent events per contract T-EXPOSE2
            result = self.event_buffer.get_recent_events(
                limit=limit,
                event_type=event_type_filter,
                since=since_timestamp
            )
            
            # Send each event as a separate WebSocket text message
            for event_dict in result.get("events", []):
                try:
                    event_json = json.dumps(event_dict)
                    frame = encode_websocket_frame(event_json.encode('utf-8'), opcode=0x1)  # Text frame
                    client.sendall(frame)
                except (OSError, BrokenPipeError, ConnectionError):
                    # Client disconnected
                    client.close()
                    return
            
            # Close WebSocket connection after sending events
            # Per contract: "MAY close after sending the initial batch"
            try:
                close_frame = create_close_frame()
                client.sendall(close_frame)
            except Exception:
                pass
            client.close()
            
        except Exception as e:
            logger.warning(f"Error handling /tower/events/recent WebSocket: {e}")
            try:
                client.close()
            except Exception:
                pass
    
    def _broadcast_event_to_streaming_clients(self):
        """
        Broadcast most recent event to all connected WebSocket clients.
        
        Per contract T-EXPOSE1.7: Immediate flush requirement.
        Events MUST be pushed to clients as soon as they are stored.
        """
        # Get the most recent event (just added)
        result = self.event_buffer.get_recent_events(limit=1)
        if not result["events"]:
            return
        
        event_dict = result["events"][0]
        event_id = event_dict.get("event_id")
        
        # Prevent duplicate broadcasts of the same event
        with self._last_broadcasted_lock:
            if event_id == self._last_broadcasted_event_id:
                # This event was already broadcasted, skip
                return
            self._last_broadcasted_event_id = event_id
        
        event_json = json.dumps(event_dict)
        
        # Create WebSocket text frame
        ws_frame = encode_websocket_frame(event_json.encode('utf-8'), opcode=0x1)
        
        # Broadcast to all streaming clients
        dead_clients = []
        event_received_at = event_dict.get('tower_received_at', 0)
        
        with self._event_clients_lock:
            clients_copy = dict(self._event_clients)
        
        for client_id, client_info in clients_copy.items():
            # Skip if this client is for /tower/events/recent (one-shot)
            if isinstance(client_info, dict) and 'socket' in client_info:
                client_sock = client_info['socket']
                
                # Skip if this event was received before the client connected
                # (it will be sent via get_events_stream instead)
                cutoff_timestamp = client_info.get('cutoff_timestamp')
                cutoff_event_id = client_info.get('cutoff_event_id')
                if cutoff_timestamp is not None and event_received_at <= cutoff_timestamp:
                    continue
                # Also skip if this is the exact event at the cutoff (defensive check)
                if cutoff_event_id and event_id == cutoff_event_id:
                    continue
                
                # Skip if we've already sent this event to this client (defensive check)
                sent_event_ids = client_info.get('sent_event_ids')
                if sent_event_ids and event_id in sent_event_ids:
                    continue
                
                # Check filters
                event_type_filter = client_info.get('event_type_filter')
                since_timestamp = client_info.get('since_timestamp')
                
                # Apply filters
                if event_type_filter and event_dict.get('event_type') != event_type_filter:
                    continue
                if since_timestamp and event_received_at < since_timestamp:
                    continue
                
                # Mark this event as sent to this client
                if sent_event_ids is not None:
                    sent_event_ids.add(event_id)
                
                try:
                    client_sock.sendall(ws_frame)
                    client_info['last_send_time'] = time.time()
                except (OSError, BrokenPipeError, ConnectionError):
                    dead_clients.append(client_id)
            else:
                # Old format (socket directly) - backward compatibility
                try:
                    client_sock = client_info if isinstance(client_info, socket.socket) else None
                    if client_sock:
                        client_sock.sendall(ws_frame)
                except (OSError, BrokenPipeError, ConnectionError):
                    dead_clients.append(client_id)
        
        # Remove dead clients
        if dead_clients:
            with self._event_clients_lock:
                for client_id in dead_clients:
                    self._event_clients.pop(client_id, None)

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
        
        # Close event streaming clients
        with self._event_clients_lock:
            event_client_ids = list(self._event_clients.keys())
            for client_id in event_client_ids:
                client_sock = self._event_clients.pop(client_id, None)
                if client_sock:
                    try:
                        client_sock.close()
                    except Exception:
                        pass
        
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

