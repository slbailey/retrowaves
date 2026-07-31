"""
HTTP Server for Appalachia Radio 3.1.

Handles HTTP streaming requests for live audio stream.
"""

import json
import time
import os
import logging
import select
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from typing import Optional

from station.outputs.http_connection_manager import HTTPConnectionManager

logger = logging.getLogger(__name__)

# Module-level station_state_manager (set by Station)
_station_state_manager = None

# Process start + last-observed segment, used by /station/health to report whether
# playout is actually advancing (a wedged Station keeps answering /station/state
# with the same segment forever).
_PROCESS_START = time.time()
_LAST_SEGMENT = {"key": None, "seen_at": _PROCESS_START}
_LAST_SEGMENT_LOCK = threading.Lock()


def set_station_state_manager(manager):
    """Set the station_state_manager for HTTP handlers."""
    global _station_state_manager
    _station_state_manager = manager


class HTTPStreamingHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for /live streaming endpoint.
    
    Sends MP3-encoded audio stream to connected clients.
    """
    
    connection_manager: HTTPConnectionManager = None
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/stream":
            self._handle_stream()
        elif self.path == "/station/state":
            self._handle_station_state()
        elif self.path == "/station/health":
            self._handle_station_health()
        else:
            self.send_error(404, "Not Found")
    
    def _handle_station_state(self):
        """
        Handle /station/state GET request (per STATION_STATE_CONTRACT.md Q.1, Q.2).
        
        Contract Q.1: Endpoint MUST be accessible via HTTP GET endpoint /station/state.
        Contract Q.1: MUST return current state synchronously.
        Contract Q.1: MUST be idempotent and non-blocking.
        Contract Q.2: Response MUST include station_state, since, current_audio.
        """
        global _station_state_manager
        if _station_state_manager is None:
            self.send_error(503, "Service Unavailable")
            return
        
        # Contract Q.1: Return current state synchronously
        state_dict = _station_state_manager.get_state_dict()
        
        # Send JSON response
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        
        try:
            response_json = json.dumps(state_dict)
            self.wfile.write(response_json.encode('utf-8'))
        except Exception as e:
            logger.debug(f"Error sending station state response: {e}")
    
    def _handle_station_health(self):
        """
        Handle /station/health GET - machine-readable health for monitoring.

        Reports whether playout is ADVANCING, which /station/state alone cannot tell
        you: a wedged Station happily keeps returning the same segment forever.

        segment_age_sec  - how long the current segment has been playing
        stalled_sec      - how long the segment has NOT changed (the stall signal)
        overrun          - segment has outlived its own duration (with slack)

        Non-blocking and filesystem-free, so it still answers when the media NFS
        mount is dead.
        """
        global _station_state_manager
        now = time.time()

        state_dict = {}
        if _station_state_manager is not None:
            try:
                state_dict = _station_state_manager.get_state_dict() or {}
            except Exception as e:
                logger.debug(f"health: could not read station state: {e}")

        current = state_dict.get("current_audio") or {}
        started_at = current.get("started_at")
        duration = current.get("duration_sec")

        # Track segment changes to derive a stall duration.
        key = f"{current.get('file_path')}|{started_at}"
        with _LAST_SEGMENT_LOCK:
            if key != _LAST_SEGMENT["key"]:
                _LAST_SEGMENT["key"] = key
                _LAST_SEGMENT["seen_at"] = now
            stalled_sec = round(now - _LAST_SEGMENT["seen_at"], 1)

        segment_age = round(now - started_at, 1) if isinstance(started_at, (int, float)) else None
        overrun = bool(
            segment_age is not None
            and isinstance(duration, (int, float))
            and segment_age > duration + 60
        )

        payload = {
            "service": "station",
            "station_state": state_dict.get("station_state"),
            "segment_type": current.get("segment_type"),
            "title": current.get("title"),
            "artist": current.get("artist"),
            "segment_age_sec": segment_age,
            "duration_sec": duration,
            "stalled_sec": stalled_sec,
            "overrun": overrun,
            "uptime_sec": round(now - _PROCESS_START, 1),
            "pid": os.getpid(),
        }

        try:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            logger.debug(f"Error sending station health response: {e}")

    def do_POST(self):
        """Reject POST requests."""
        self.send_error(404, "Not Found")
    
    def do_PUT(self):
        """Reject PUT requests."""
        self.send_error(404, "Not Found")
    
    def do_PATCH(self):
        """Reject PATCH requests."""
        self.send_error(404, "Not Found")
    
    def do_DELETE(self):
        """Reject DELETE requests."""
        self.send_error(404, "Not Found")
    
    def _handle_stream(self):
        """Handle /stream streaming request."""
        # Send HTTP headers
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        
        # Flush headers immediately
        try:
            self.wfile.flush()
        except Exception:
            pass
        
        # Get the underlying socket for this connection
        # We need to use the raw socket for writing MP3 data
        client_socket = self.connection
        
        # Register client socket
        if self.connection_manager:
            client_address = self.client_address[0]
            self.connection_manager.add_client(client_socket, client_address)
            logger.info(f"[STREAM] Client connected from {client_address}")
        
        # Keep connection open (connection manager handles broadcasting)
        # The connection will be closed when client disconnects
        try:
            # Keep-alive: wait for client to disconnect
            # Use select to check if socket is still connected
            while True:
                try:
                    # Check if socket is still readable (client disconnected)
                    ready, _, _ = select.select([client_socket], [], [], 1.0)
                    if ready:
                        # Client sent data or closed connection - peek to check
                        try:
                            data = client_socket.recv(1, socket.MSG_PEEK)
                            if not data:
                                # Connection closed
                                break
                        except (ConnectionError, OSError, BrokenPipeError, socket.error):
                            # Connection error
                            break
                except (ConnectionError, OSError, BrokenPipeError, socket.error):
                    break
                except Exception as e:
                    logger.debug(f"Connection check error: {e}")
                    break
        except Exception as e:
            logger.debug(f"Connection error: {e}")
        finally:
            # Remove client when connection closes
            if self.connection_manager:
                client_address = self.client_address[0]
                self.connection_manager.remove_client(client_socket, client_address)
                logger.info(f"[STREAM] Client disconnected from {client_address}")
    
    def log_message(self, format, *args):
        """Override to use our logger instead of stderr."""
        logger.debug(f"{self.address_string()} - {format % args}")


def create_handler_class(connection_manager: HTTPConnectionManager):
    """
    Create a handler class with the connection manager bound.
    
    Args:
        connection_manager: HTTPConnectionManager instance
        
    Returns:
        Handler class with connection_manager set
    """
    class Handler(HTTPStreamingHandler):
        pass
    
    Handler.connection_manager = connection_manager
    return Handler


class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """
    Threaded HTTP server for handling multiple concurrent connections.
    
    Uses ThreadingMixIn to handle each request in a separate thread.
    """
    allow_reuse_address = True
    daemon_threads = True

