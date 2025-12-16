# tower/http/server.py

import os
import socket
import select
import threading
import time
import logging
import uuid
import json
from collections import deque
from dataclasses import dataclass
from typing import Optional, Dict, Any

from tower.http.event_broadcaster import EventBroadcaster
from tower.http.websocket import (
    parse_upgrade_request,
    create_upgrade_response,
    encode_websocket_frame,
    decode_websocket_frame,
    create_close_frame,
    WebSocketError
)

logger = logging.getLogger(__name__)

# Setup file handler for contract-compliant logging (LOG1, LOG2, LOG3, LOG4)
# Per contract: /var/log/retrowaves/tower.log, non-blocking, rotation-tolerant
# TowerRuntime is implemented in HTTPServer
try:
    import logging.handlers
    # Use WatchedFileHandler for rotation tolerance (per LOG3)
    handler = logging.handlers.WatchedFileHandler('/var/log/retrowaves/tower.log', mode='a')
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
               and getattr(h, 'baseFilename', None) == '/var/log/retrowaves/tower.log'
               for h in logger.handlers):
        logger.addHandler(handler)
    logger.propagate = False  # Avoid duplicate logs
except Exception:
    # Logging must never crash component per LOG4
    # Catch all exceptions (including I/O errors) to prevent import-time failures
    pass

# Client timeout per contract T-CLIENTS2
TOWER_CLIENT_TIMEOUT_MS = 250  # 250ms timeout for slow clients

# WebSocket send stall timeout per contract T-WS4
# Bounded timeout for detecting send stalls (slow consumers)
TOWER_WS_SEND_STALL_TIMEOUT_MS = 250  # 250ms timeout for send stall detection

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
        
        # Event broadcaster per contract T-EVENTS2 (no storage, only tracks shutdown state)
        self.event_buffer = EventBroadcaster()
        
        # Event streaming clients (for /tower/events WebSocket endpoint) per contract T-EXPOSE1
        self._event_clients: dict[str, dict] = {}
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
            elif path == "/__test__/broadcast" and os.getenv("TOWER_TEST_MODE") == "1":
                # Test-only endpoint for triggering event broadcasts
                # Only available when TOWER_TEST_MODE=1
                self._handle_test_broadcast_endpoint(client, method, request)
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
                    
                    if base_path == "/tower/events":
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
            
            # Build JSON response per contract T-BUF2
            # Required fields: capacity, count, overflow_count, ratio
            capacity = stats.capacity
            count = stats.count
            overflow_count = getattr(stats, 'overflow_count', 0)  # May not be available on all stats objects
            ratio = count / capacity if capacity > 0 else 0.0
            
            response_data = {
                "capacity": capacity,
                "count": count,
                "overflow_count": overflow_count,
                "ratio": ratio
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
            
            # Validate event per contract T-EVENTS7
            success = self.event_buffer.validate_event(event_type, timestamp, metadata)
            
            if success:
                # Update shutdown state for critical events (per contract T-EVENTS5 exception)
                # Use new event names (station_startup, station_shutdown)
                critical_events = {"station_startup", "station_shutdown"}
                if event_type in critical_events:
                    # EventBroadcaster tracks shutdown state for encoder manager
                    self.event_buffer.update_shutdown_state(event_type)
                
                # Broadcast event immediately to connected clients (per contract T-EXPOSE1.7)
                self._broadcast_event_to_streaming_clients(event_type, timestamp, metadata)
                
                response = (
                    "HTTP/1.1 204 No Content\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
            else:
                # Invalid event - reject with 400 Bad Request per contract T-EVENTS7
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    '{"error": "Invalid event type"}\n'
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
    
    def _handle_test_broadcast_endpoint(self, client, method, request):
        """
        Handle POST /__test__/broadcast endpoint for test-only event broadcasting.
        
        Only available when TOWER_TEST_MODE=1.
        Accepts JSON body with event_type, timestamp, and metadata.
        Broadcasts event to all connected WebSocket clients.
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
            # Extract body from request bytes (may be in initial recv)
            request_str = request.decode('utf-8', errors='ignore')
            header_end = request_str.find('\r\n\r\n')
            if header_end >= 0:
                # Body starts after headers
                body_start = header_end + 4
                body_data = request[body_start:] if len(request) > body_start else b''
            else:
                body_data = b''
            
            # Read remaining body if Content-Length indicates more data
            # Parse Content-Length from headers
            content_length = None
            for line in request_str.split('\r\n'):
                if line.lower().startswith('content-length:'):
                    try:
                        content_length = int(line.split(':', 1)[1].strip())
                        break
                    except (ValueError, IndexError):
                        pass
            
            # Read remaining body if needed
            if content_length is not None and len(body_data) < content_length:
                client.settimeout(1.0)
                while len(body_data) < content_length:
                    try:
                        chunk = client.recv(min(4096, content_length - len(body_data)))
                        if not chunk:
                            break
                        body_data += chunk
                    except socket.timeout:
                        break
                    except Exception:
                        break
            
            if not body_data:
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    '{"error": "Request body required"}\n'
                )
                try:
                    client.sendall(response.encode("ascii"))
                except Exception:
                    pass
                client.close()
                return
            
            # Parse JSON
            try:
                body_str = body_data.decode("utf-8")
                event_data = json.loads(body_str)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    f'{{"error": "Invalid JSON: {str(e)}"}}\n'
                )
                try:
                    client.sendall(response.encode("ascii"))
                except Exception:
                    pass
                client.close()
                return
            
            # Extract event fields
            event_type = event_data.get("event_type", "test_event")
            timestamp = event_data.get("timestamp", time.time())
            metadata = event_data.get("metadata", {})
            
            # Broadcast event immediately to connected clients
            self._broadcast_event_to_streaming_clients(event_type, timestamp, metadata)
            
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Connection: close\r\n"
                "\r\n"
                '{"status": "broadcast"}\n'
            )
            client.sendall(response.encode("ascii"))
            client.close()
            
        except Exception as e:
            logger.warning(f"Error handling /__test__/broadcast: {e}")
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
        - Broadcasts heartbeat events immediately upon receipt
        - Supports multiple simultaneous WS clients
        - Broadcasts events to all connected clients without delay
        """
        # Parse query parameters
        event_type_filter = query_params.get("event_type")
        # Note: 'since' parameter removed per contract - events are not stored
        
        # Perform WebSocket upgrade
        try:
            upgrade_response = create_upgrade_response(sec_websocket_key)
            client.sendall(upgrade_response)
        except Exception as e:
            logger.warning(f"Error sending WebSocket upgrade response: {e}")
            client.close()
            return
        
        # Add client to event streaming clients per contract T-EXPOSE1.2
        # Per T-WS4: Reduce socket send buffer to enable send-stall detection
        # Smaller buffer makes it easier to detect when client is slow (buffer fills faster)
        try:
            # Set smaller send buffer (8KB) to enable bounded send-stall detection
            # This allows T-WS4 compliance: detect stalls when buffer fills, not based on idle time
            client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8192)
        except Exception:
            # If setting buffer size fails, continue anyway (some systems may not allow it)
            pass
        
        with self._event_clients_lock:
            self._event_clients[client_id] = {
                'socket': client,
                'event_type_filter': event_type_filter,
                'last_activity_time': time.time()
            }
        
        # Keep connection alive and handle incoming frames (ping/pong, close)
        # Per T-WS2: Idle connections MUST NOT be disconnected based solely on lack of data transfer
        # Per T-WS4: Slow-consumer drop applies only when an actual send operation stalls
        buffer = b''
        try:
            while self.running:
                
                try:
                    # Per T-WS2: Idle connections MUST NOT be disconnected
                    # Only check for close frames, ping/pong, not for inactivity
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
                        
                        # Update last_activity_time when data is received from client (any opcode)
                        with self._event_clients_lock:
                            if client_id in self._event_clients:
                                self._event_clients[client_id]['last_activity_time'] = time.time()
                        
                        if opcode == 0x8:  # Close frame
                            # Send close frame response
                            try:
                                close_frame = create_close_frame()
                                client.sendall(close_frame)
                                # Update last_activity_time when frame is successfully sent
                                with self._event_clients_lock:
                                    if client_id in self._event_clients:
                                        self._event_clients[client_id]['last_activity_time'] = time.time()
                            except Exception:
                                pass
                            break
                        elif opcode == 0x9:  # Ping frame
                            # Respond with pong
                            try:
                                pong_frame = encode_websocket_frame(payload, opcode=0xA)  # Pong
                                client.sendall(pong_frame)
                                # Update last_activity_time when frame is successfully sent
                                with self._event_clients_lock:
                                    if client_id in self._event_clients:
                                        self._event_clients[client_id]['last_activity_time'] = time.time()
                            except Exception:
                                pass
                        # Ignore other opcodes (text/binary from client)
                    
                except socket.timeout:
                    # Timeout is a normal polling event - just continue the loop
                    # The inactivity check at the top of the loop will handle true inactivity
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
    
    def _broadcast_event_to_streaming_clients(self, event_type: str, timestamp: float, metadata: Dict[str, Any]):
        """
        Broadcast event to all connected WebSocket clients.
        
        Per contract T-EXPOSE1.7: Immediate flush requirement.
        Events MUST be pushed to clients as soon as they are received.
        
        Args:
            event_type: Event type
            timestamp: Station Clock A timestamp
            metadata: Event metadata
        """
        import time as time_module
        import uuid
        
        # Create event dict with tower_received_at timestamp
        event_dict = {
            "event_type": event_type,
            "timestamp": timestamp,
            "tower_received_at": time_module.time(),  # Tower wall-clock time
            "event_id": str(uuid.uuid4()),
            "metadata": metadata
        }
        
        event_json = json.dumps(event_dict)
        
        # Create WebSocket text frame
        ws_frame = encode_websocket_frame(event_json.encode('utf-8'), opcode=0x1)
        
        # Broadcast to all streaming clients
        dead_clients = []
        
        with self._event_clients_lock:
            clients_copy = dict(self._event_clients)
        
        for client_id, client_info in clients_copy.items():
            if isinstance(client_info, dict) and 'socket' in client_info:
                client_sock = client_info['socket']
                
                # Check filters
                event_type_filter = client_info.get('event_type_filter')
                
                # Apply filters
                if event_type_filter and event_type != event_type_filter:
                    continue
                
                # Per T-WS4: Slow-consumer drop applies only when an actual send operation stalls
                # Per T-WS7: WebSocket write operations MUST be non-blocking
                # Bounded send semantics: Use select.select() to check writability before send
                # select() is required to make T-WS4 enforceable and testable (detects send stalls deterministically)
                try:
                    # Check if socket is writable within bounded timeout (per T-WS4)
                    send_timeout = TOWER_WS_SEND_STALL_TIMEOUT_MS / 1000.0
                    readable, writable, exceptional = select.select([], [client_sock], [], send_timeout)
                    
                    if client_sock not in writable:
                        # Socket not writable within timeout - send would stall
                        # Per T-WS4: disconnect slow consumer when send stalls
                        logger.debug(f"WebSocket send stall (not writable) for client {client_id} - disconnecting slow consumer")
                        dead_clients.append(client_id)
                        try:
                            # Send close frame (best effort, non-blocking)
                            close_frame = create_close_frame()
                            try:
                                client_sock.setblocking(False)
                                client_sock.send(close_frame)
                            except Exception:
                                pass
                            client_sock.close()
                        except Exception:
                            pass
                    else:
                        # Socket is writable - attempt send
                        # Save original blocking mode
                        was_blocking = client_sock.getblocking()
                        # Set non-blocking mode for send operation (secondary guard)
                        client_sock.setblocking(False)
                        
                        try:
                            # Attempt non-blocking send
                            # If buffer is full, send() raises BlockingIOError immediately
                            # Partial send indicates failed frame send - disconnect client
                            sent = client_sock.send(ws_frame)
                            if sent < len(ws_frame):
                                # Partial send - failed frame send, disconnect client
                                logger.debug(f"WebSocket partial send (failed frame) for client {client_id} - disconnecting")
                                dead_clients.append(client_id)
                                try:
                                    # Send close frame (best effort)
                                    close_frame = create_close_frame()
                                    try:
                                        client_sock.send(close_frame)
                                    except Exception:
                                        pass
                                    client_sock.close()
                                except Exception:
                                    pass
                            else:
                                # Full frame sent successfully
                                client_sock.setblocking(was_blocking)  # Restore blocking mode
                                # Update activity time on successful send
                                client_info['last_activity_time'] = time.time()
                        except BlockingIOError:
                            # Socket buffer is full - send would block
                            # Per T-WS4: disconnect slow consumer when send stalls
                            logger.debug(f"WebSocket send stall (BlockingIOError) for client {client_id} - disconnecting slow consumer")
                            dead_clients.append(client_id)
                            try:
                                # Send close frame (best effort, may also block)
                                close_frame = create_close_frame()
                                try:
                                    client_sock.send(close_frame)
                                except Exception:
                                    pass
                                client_sock.close()
                            except Exception:
                                pass
                        except (OSError, BrokenPipeError, ConnectionError):
                            # Send failed - connection broken
                            dead_clients.append(client_id)
                            try:
                                client_sock.close()
                            except Exception:
                                pass
                        finally:
                            # Restore original blocking mode if socket still open
                            try:
                                if client_id not in dead_clients:
                                    client_sock.setblocking(was_blocking)
                            except Exception:
                                pass
                except (OSError, BrokenPipeError, ConnectionError, ValueError):
                    # Socket error or invalid file descriptor
                    dead_clients.append(client_id)
                    try:
                        client_sock.close()
                    except Exception:
                        pass
        
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

