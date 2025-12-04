"""
HTTP server for Retrowaves Tower.

Provides the /stream endpoint that serves continuous MP3 audio.
Phase 2: Adds /status and /control/source endpoints.
"""

import json
import logging
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import Optional

from tower.http_conn import HTTPConnectionManager
from tower.encoder import Encoder
from tower.encoder_manager import EncoderManager
from tower.source_manager import SourceManager

logger = logging.getLogger(__name__)


def make_stream_handler(
    connection_manager: HTTPConnectionManager,
    source_manager: Optional[SourceManager] = None,
    encoder: Optional[Encoder] = None,  # For backwards compatibility
    encoder_manager: Optional[EncoderManager] = None,  # Phase 4
    start_time: Optional[float] = None
):
    """Create a StreamHandler class with dependencies."""
    
    class StreamHandler(BaseHTTPRequestHandler):
        """HTTP request handler for Tower endpoints."""
        
        def __init__(self, *args, **kwargs):
            """Initialize handler."""
            # Dependencies injected from outer scope
            self.connection_manager = connection_manager
            self.source_manager = source_manager
            self.encoder = encoder  # For backwards compatibility
            self.encoder_manager = encoder_manager  # Phase 4
            self.start_time = start_time or time.time()
            super().__init__(*args, **kwargs)
        
        def do_GET(self):
            """Handle GET requests."""
            if self.path == "/stream":
                self._handle_stream()
            elif self.path == "/status":
                self._handle_status()
            else:
                self.send_error(404, "Not Found")
        
        def do_POST(self):
            """Handle POST requests."""
            if self.path == "/control/source":
                self._handle_control_source()
            else:
                self.send_error(404, "Not Found")
        
        def _handle_stream(self):
            """Handle /stream endpoint."""
            # 1. Write headers
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            # Keep connection open for streaming; HTTP/1.1 defaults to persistent
            # connections unless "Connection: close" is sent.
            self.send_header("Connection", "keep-alive")
            # Prevent caching of stream data
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            
            # Flush headers so clients can start reading body bytes immediately.
            try:
                self.wfile.flush()
            except Exception:
                pass
            
            # 2. Register client with connection manager
            # Store both the raw socket and the buffered writer
            try:
                sock = self.connection
                wfile = self.wfile
                self.connection_manager.add_client(sock, wfile)
            except Exception as e:
                logger.error(f"Error registering client: {e}", exc_info=True)
                raise
            
            # 3. Return immediately so httpx doesn't hang:
            # Encoder reader thread will call broadcast() which writes to all clients.
            # The connection manager will detect disconnects during write operations.
            return
        
        def _handle_status(self):
            """Handle GET /status endpoint."""
            if not self.source_manager:
                self.send_error(503, "Service Unavailable")
                return
            
            try:
                # Get current state
                source_mode = self.source_manager.get_current_mode()
                file_path = self.source_manager.get_current_file_path()
                num_clients = self.connection_manager.get_client_count()
                
                # Phase 4: Use EncoderManager if available, fall back to encoder
                if self.encoder_manager:
                    encoder_running = self.encoder_manager.is_running()
                elif self.encoder:
                    encoder_running = self.encoder.is_running()
                else:
                    encoder_running = False
                
                uptime_seconds = time.time() - self.start_time
                
                # Build response
                response = {
                    "source_mode": source_mode.value,
                    "file_path": file_path,
                    "num_clients": num_clients,
                    "encoder_running": encoder_running,
                    "uptime_seconds": uptime_seconds
                }
                
                # Send response
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))
                
            except Exception as e:
                logger.error(f"Error handling /status: {e}")
                self.send_error(500, "Internal Server Error")
        
        def _handle_control_source(self):
            """Handle POST /control/source endpoint."""
            if not self.source_manager:
                self.send_error(503, "Service Unavailable")
                return
            
            try:
                # Read request body
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length == 0:
                    self._send_error_response(400, "Request body is required")
                    return
                
                body = self.rfile.read(content_length)
                
                # Parse JSON
                try:
                    data = json.loads(body.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    self._send_error_response(400, f"Invalid JSON: {e}")
                    return
                
                # Validate mode
                if 'mode' not in data:
                    self._send_error_response(400, "Missing 'mode' field")
                    return
                
                mode_str = data.get('mode')
                if not isinstance(mode_str, str):
                    self._send_error_response(400, "'mode' must be a string")
                    return
                
                # Import here to avoid circular dependency
                from tower.sources import SourceMode
                
                try:
                    mode = SourceMode(mode_str)
                except ValueError:
                    self._send_error_response(400, f"Invalid mode: {mode_str} (must be 'tone', 'silence', or 'file')")
                    return
                
                # Validate file_path based on mode
                file_path = data.get('file_path')
                
                if mode == SourceMode.FILE:
                    if not file_path:
                        self._send_error_response(400, "file_path is required for 'file' mode")
                        return
                    if not isinstance(file_path, str):
                        self._send_error_response(400, "file_path must be a string")
                        return
                    if not file_path:
                        self._send_error_response(400, "file_path cannot be empty")
                        return
                elif file_path is not None:
                    self._send_error_response(400, f"file_path should not be provided for mode '{mode.value}'")
                    return
                
                # Switch source (non-blocking, but may raise exceptions)
                try:
                    self.source_manager.switch_source(mode, file_path)
                except FileNotFoundError as e:
                    self._send_error_response(400, f"File not found: {e}")
                    return
                except ValueError as e:
                    self._send_error_response(400, str(e))
                    return
                except Exception as e:
                    logger.error(f"Unexpected error switching source: {e}")
                    self._send_error_response(500, "Internal server error")
                    return
                
                # Success response
                response = {
                    "status": "ok",
                    "source_mode": mode.value,
                    "file_path": file_path
                }
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))
                
            except Exception as e:
                logger.error(f"Error handling /control/source: {e}")
                self._send_error_response(500, "Internal server error")
        
        def _send_error_response(self, status_code: int, error_message: str):
            """Send error response in JSON format."""
            response = {
                "status": "error",
                "error": error_message
            }
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
        
        def log_message(self, format, *args):
            """Override to use our logger."""
            logger.debug(f"{self.address_string()} - {format % args}")
    
    return StreamHandler


class TowerHTTPServer:
    """HTTP server for Tower streaming."""
    
    def __init__(
        self,
        host: str,
        port: int,
        connection_manager: HTTPConnectionManager,
        source_manager: Optional[SourceManager] = None,
        encoder: Optional[Encoder] = None,  # For backwards compatibility
        encoder_manager: Optional[EncoderManager] = None,  # Phase 4
        start_time: Optional[float] = None
    ):
        """
        Initialize HTTP server.
        
        Args:
            host: Host to bind to
            port: Port to bind to
            connection_manager: HTTPConnectionManager instance
            source_manager: SourceManager instance (for Phase 2 endpoints)
            encoder: Encoder instance (for Phase 2 endpoints, backwards compatibility)
            encoder_manager: EncoderManager instance (for Phase 4)
            start_time: Server start time (for uptime calculation)
        """
        self.host = host
        self.port = port
        self.connection_manager = connection_manager
        self.source_manager = source_manager
        self.encoder = encoder
        self.encoder_manager = encoder_manager
        self.start_time = start_time or time.time()
        self.server: Optional[HTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self._shutdown = False
    
    def start(self) -> None:
        """Start HTTP server in a background thread."""
        if self.server is not None:
            raise RuntimeError("Server already started")
        
        # Create handler class with dependencies
        handler_class = make_stream_handler(
            self.connection_manager,
            self.source_manager,
            encoder=self.encoder,  # For backwards compatibility
            encoder_manager=self.encoder_manager,  # Phase 4
            start_time=self.start_time
        )
        
        # Create server (use ThreadingHTTPServer so each request gets its own thread)
        self.server = ThreadingHTTPServer((self.host, self.port), handler_class)
        
        # Start server in background thread
        self.server_thread = threading.Thread(
            target=self._run_server,
            daemon=True,
            name="HTTPServer"
        )
        self.server_thread.start()
        
        logger.info(f"HTTP server started on {self.host}:{self.port}")
    
    def _run_server(self):
        """Run server (called in background thread)."""
        try:
            self.server.serve_forever()
        except Exception as e:
            if not self._shutdown:
                logger.error(f"HTTP server error: {e}")
    
    def stop(self) -> None:
        """Stop HTTP server."""
        if self.server is None:
            return
        
        self._shutdown = True
        
        # Shutdown server
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        
        # Wait for thread to finish
        if self.server_thread:
            self.server_thread.join(timeout=2.0)
        
        self.server = None
        self.server_thread = None
        
        logger.info("HTTP server stopped")

