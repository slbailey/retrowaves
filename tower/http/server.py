# tower/http/server.py

import socket
import threading
import time
import logging
import uuid

from tower.http.connection_manager import HTTPConnectionManager

logger = logging.getLogger(__name__)


class HTTPServer:
    def __init__(self, host, port, frame_source):
        self.host = host
        self.port = port
        self.frame_source = frame_source  # must implement .pop() returning bytes
        self.connection_manager = HTTPConnectionManager()
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
                logger.info(f"Client connected: {addr}")
                threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()
            except OSError:
                # Socket closed during shutdown
                break

    def _handle_client(self, client):
        """Handle a single client connection."""
        # Generate unique client ID per contract [H4]
        client_id = str(uuid.uuid4())
        try:
            request = client.recv(4096)  # read HTTP GET
            if not request:
                client.close()
                return

            # --- REQUIRED HTTP RESPONSE HEADER ---
            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: audio/mpeg\r\n"
                "Connection: keep-alive\r\n"
                "Cache-Control: no-cache, no-store, must-revalidate\r\n"
                "\r\n"
            )
            client.sendall(headers.encode("ascii"))

            # Add client to connection manager for broadcasting per contract [H4]
            self.connection_manager.add_client(client, client_id)

            # Keep connection alive - wait for client to disconnect
            # The main_loop will broadcast frames to all clients via connection_manager
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

        except Exception as e:
            logger.warning(f"Client error: {e}")
        finally:
            # Remove client by ID per contract [H4]
            self.connection_manager.remove_client(client_id)

    def broadcast(self, frame: bytes):
        """Broadcast a frame to all connected clients."""
        if frame:
            self.connection_manager.broadcast(frame)

    def stop(self):
        """
        Stop the HTTP server.
        
        Per contract [I27] #3: Stop HTTP connection manager (close client sockets).
        """
        self.running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except:
                pass
        
        # Per contract [I27] #3: Close all client connections via connection manager
        if hasattr(self, 'connection_manager'):
            self.connection_manager.close_all()

