"""
HTTP Server for Appalachia Radio 3.1.

Handles HTTP streaming requests for live audio stream.
"""

import logging
import select
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler

from station.outputs.http_connection_manager import HTTPConnectionManager

logger = logging.getLogger(__name__)


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

