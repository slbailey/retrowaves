"""
HTTP Server for Appalachia Radio 3.1.

Handles HTTP streaming requests for live audio stream.
"""

import json
import logging
import select
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from typing import Optional

from station.outputs.http_connection_manager import HTTPConnectionManager

logger = logging.getLogger(__name__)

# Module-level now_playing_manager (set by Station)
_now_playing_manager = None


def set_now_playing_manager(manager):
    """Set the now_playing_manager for HTTP handlers."""
    global _now_playing_manager
    _now_playing_manager = manager


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
        elif self.path == "/now_playing":
            self._handle_now_playing()
        else:
            self.send_error(404, "Not Found")
    
    def _handle_now_playing(self):
        """
        Handle /now_playing GET request (per NEW_NOW_PLAYING_STATE_CONTRACT E.3).
        
        Contract E.3: REST endpoint MUST respond to GET requests with current state.
        Contract E.3: Endpoint MUST be read-only.
        Contract F.7: HTTP POST/PUT/PATCH/DELETE MUST NOT be accepted.
        """
        # Contract E.3: Endpoint MUST respond to GET requests
        global _now_playing_manager
        if _now_playing_manager is None:
            self.send_error(503, "Service Unavailable")
            return
        
        state = _now_playing_manager.get_state()
        
        # Contract E.3: Endpoint MUST return None or empty representation when no segment is playing
        if state is None:
            response_data = None
        else:
            # Contract E.3: Endpoint MUST return state in a consistent format (JSON recommended)
            response_data = {
                "segment_type": state.segment_type,
                "started_at": state.started_at,
                "title": state.title,
                "artist": state.artist,
                "album": state.album,
                "year": state.year,
                "duration_sec": state.duration_sec,
                "file_path": state.file_path
            }
        
        # Send JSON response
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        
        try:
            response_json = json.dumps(response_data)
            self.wfile.write(response_json.encode('utf-8'))
        except Exception as e:
            logger.debug(f"Error sending now_playing response: {e}")
    
    def do_POST(self):
        """Reject POST requests (per NEW_NOW_PLAYING_STATE_CONTRACT F.7)."""
        if self.path == "/now_playing":
            # Contract F.7: HTTP POST/PUT/PATCH/DELETE MUST NOT be accepted
            self.send_error(405, "Method Not Allowed")
        else:
            self.send_error(404, "Not Found")
    
    def do_PUT(self):
        """Reject PUT requests (per NEW_NOW_PLAYING_STATE_CONTRACT F.7)."""
        if self.path == "/now_playing":
            # Contract F.7: HTTP POST/PUT/PATCH/DELETE MUST NOT be accepted
            self.send_error(405, "Method Not Allowed")
        else:
            self.send_error(404, "Not Found")
    
    def do_PATCH(self):
        """Reject PATCH requests (per NEW_NOW_PLAYING_STATE_CONTRACT F.7)."""
        if self.path == "/now_playing":
            # Contract F.7: HTTP POST/PUT/PATCH/DELETE MUST NOT be accepted
            self.send_error(405, "Method Not Allowed")
        else:
            self.send_error(404, "Not Found")
    
    def do_DELETE(self):
        """Reject DELETE requests (per NEW_NOW_PLAYING_STATE_CONTRACT F.7)."""
        if self.path == "/now_playing":
            # Contract F.7: HTTP POST/PUT/PATCH/DELETE MUST NOT be accepted
            self.send_error(405, "Method Not Allowed")
        else:
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

