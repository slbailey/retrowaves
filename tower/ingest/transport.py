"""
Transport abstraction for PCM Ingestion.

Per NEW_PCM_INGEST_CONTRACT I12-I16: Transport mechanism is implementation-defined.
This module provides a transport abstraction and Unix socket implementation.

The transport layer is responsible for:
- Accepting connections
- Reading raw bytes
- Calling callback with byte chunks
- Handling connection lifecycle

The transport does NOT:
- Validate frame boundaries
- Decode or modify bytes
- Perform any frame assembly
"""

import os
import socket
import threading
import logging
from abc import ABC, abstractmethod
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Canonical frame size per contract
FRAME_SIZE_BYTES = 4096


class IngestTransport(ABC):
    """
    Abstract base class for PCM ingestion transports.
    
    Per contract I12-I16: Transport is implementation-defined.
    This abstraction allows PCMIngestor to work with any transport mechanism.
    """
    
    @abstractmethod
    def start(self, on_bytes_callback: Callable[[bytes], None]) -> None:
        """
        Start the transport and begin accepting connections.
        
        Args:
            on_bytes_callback: Callback function that receives raw byte chunks.
                              Called for every chunk of bytes received.
                              Must be thread-safe and non-blocking.
        """
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """
        Stop the transport gracefully.
        
        Stops accepting new connections, finishes processing in-flight data,
        and closes all connections cleanly.
        """
        pass


class UnixSocketIngestTransport(IngestTransport):
    """
    Unix socket transport for PCM ingestion.
    
    Accepts connections via AF_UNIX socket and reads bytes in background threads.
    Calls on_bytes_callback for every chunk of bytes received.
    
    Per contract I16: Transport-specific concerns are implementation details.
    """
    
    def __init__(self, socket_path: str):
        """
        Initialize Unix socket transport.
        
        Args:
            socket_path: Path to Unix socket file (e.g., "/var/run/retrowaves/pcm.sock")
        """
        self.socket_path = socket_path
        self.on_bytes_callback: Optional[Callable[[bytes], None]] = None
        self._running = False
        self._server_sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._client_threads: list[threading.Thread] = []
        self._lock = threading.Lock()
    
    def start(self, on_bytes_callback: Callable[[bytes], None]) -> None:
        """
        Start Unix socket server and begin accepting connections.
        
        Args:
            on_bytes_callback: Callback function for received bytes.
        """
        if self._running:
            logger.warning("UnixSocketIngestTransport already started")
            return
        
        self.on_bytes_callback = on_bytes_callback
        self._running = True
        
        # Create parent directory if it doesn't exist
        socket_dir = os.path.dirname(self.socket_path)
        if socket_dir:
            try:
                os.makedirs(socket_dir, mode=0o755, exist_ok=True)
            except OSError as e:
                logger.error(f"Could not create socket directory {socket_dir}: {e}")
                raise
        
        # Remove existing socket file if it exists
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except OSError as e:
            logger.warning(f"Could not remove existing socket file {self.socket_path}: {e}")
        
        # Create Unix socket
        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(self.socket_path)
        self._server_sock.listen(5)
        
        # Set socket permissions (readable/writable by group)
        try:
            os.chmod(self.socket_path, 0o660)
        except OSError as e:
            logger.warning(f"Could not set socket permissions: {e}")
        
        # Start accept thread
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        
        logger.info(f"Unix socket transport listening on {self.socket_path}")
    
    def _accept_loop(self) -> None:
        """Accept connections in background thread."""
        while self._running:
            try:
                client_sock, addr = self._server_sock.accept()
                logger.info(f"Client connected: {addr}")
                
                # Start client handler thread
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock,),
                    daemon=True
                )
                client_thread.start()
                
                with self._lock:
                    self._client_threads.append(client_thread)
                    # Clean up finished threads
                    self._client_threads = [t for t in self._client_threads if t.is_alive()]
                    
            except OSError:
                # Socket closed during shutdown
                if self._running:
                    logger.warning("Error accepting connection")
                break
            except Exception as e:
                if self._running:
                    logger.warning(f"Unexpected error in accept loop: {e}")
    
    def _handle_client(self, client_sock: socket.socket) -> None:
        """
        Handle a single client connection.
        
        Reads bytes and calls on_bytes_callback for each chunk.
        Per contract I16: Transport does not validate or assemble frames.
        """
        try:
            while self._running:
                # Read bytes (non-blocking with timeout)
                client_sock.settimeout(1.0)
                try:
                    data = client_sock.recv(8192)  # Read up to 8KB chunks
                    if not data:
                        # Client closed connection
                        break
                    
                    # Call callback with raw bytes (no validation, no assembly)
                    if self.on_bytes_callback:
                        try:
                            self.on_bytes_callback(data)
                        except Exception as e:
                            # Callback errors should not crash transport
                            logger.debug(f"Error in bytes callback: {e}")
                            
                except socket.timeout:
                    # Timeout is fine - continue loop to check running flag
                    continue
                except (OSError, ConnectionError) as e:
                    # Client disconnected or error
                    logger.debug(f"Client connection error: {e}")
                    break
                    
        except Exception as e:
            logger.debug(f"Error handling client: {e}")
        finally:
            try:
                client_sock.close()
            except Exception:
                pass
            logger.debug("Client connection closed")
    
    def stop(self) -> None:
        """Stop transport gracefully."""
        if not self._running:
            return
        
        logger.info("Stopping Unix socket transport...")
        self._running = False
        
        # Close server socket
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        
        # Wait for accept thread
        if self._accept_thread and self._accept_thread.is_alive():
            self._accept_thread.join(timeout=1.0)
        
        # Wait for client threads (with timeout)
        with self._lock:
            for thread in self._client_threads:
                if thread.is_alive():
                    thread.join(timeout=0.5)
        
        # Remove socket file
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except OSError:
            pass
        
        logger.info("Unix socket transport stopped")

