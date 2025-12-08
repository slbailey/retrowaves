"""
HTTP Streaming Sink for Appalachia Radio 3.1.

Streams PCM audio as MP3 over HTTP for client playback.
"""

import logging
import subprocess
import threading
import time
from queue import Queue, Empty
from typing import Optional

import numpy as np

from station.outputs.base_sink import BaseSink
from station.outputs.http_connection_manager import HTTPConnectionManager

logger = logging.getLogger(__name__)


class HTTPStreamingSink(BaseSink):
    """
    HTTP streaming sink that encodes PCM to MP3 and streams via HTTP.
    
    Architecture: PlayoutEngine → Mixer → HTTPStreamingSink → ffmpeg encoding → HTTP response
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8000, sample_rate: int = 48000, channels: int = 2):
        """
        Initialize HTTP streaming sink.
        
        Args:
            host: Host address to bind to (default: 0.0.0.0)
            port: Port to listen on (default: 8000)
            sample_rate: Audio sample rate (default: 48000)
            channels: Number of audio channels (default: 2)
        """
        self.host = host
        self.port = port
        self.sample_rate = sample_rate
        self.channels = channels
        
        self.connection_manager = HTTPConnectionManager()
        self.http_server: Optional[threading.Thread] = None
        self.http_server_instance = None  # Store server instance for shutdown
        self.encoder_process: Optional[subprocess.Popen] = None
        self.encoder_thread: Optional[threading.Thread] = None
        
        self._running = False
        self._pcm_queue: Queue[bytes] = Queue(maxsize=100)  # Buffer PCM frames
        self._mp3_queue: Queue[bytes] = Queue(maxsize=100)  # Buffer MP3 frames
        
        logger.info(f"HTTPStreamingSink initialized (host={host}, port={port})")
    
    def start(self) -> None:
        """Start the HTTP server and encoder."""
        if self._running:
            logger.warning("HTTPStreamingSink already started")
            return
        
        self._running = True
        
        # Start ffmpeg encoder
        self._start_encoder()
        
        # Start encoder reader thread
        self.encoder_thread = threading.Thread(target=self._encoder_reader_loop, daemon=True)
        self.encoder_thread.start()
        
        # Start HTTP server in separate thread
        from app.http_server import create_handler_class, ThreadingHTTPServer
        handler_class = create_handler_class(self.connection_manager)
        self.http_server_instance = ThreadingHTTPServer((self.host, self.port), handler_class)
        self.http_server = threading.Thread(target=self.http_server_instance.serve_forever, daemon=True)
        self.http_server.start()
        
        logger.info(f"[STREAM] HTTP server listening on port {self.port}")
        
        # Print VLC connection instructions
        import socket as sock
        try:
            # Get server IP address
            s = sock.socket(sock.AF_INET, sock.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            server_ip = s.getsockname()[0]
            s.close()
        except Exception:
            server_ip = self.host if self.host != "0.0.0.0" else "localhost"
        
        print("\n" + "=" * 70)
        print("STREAM READY")
        print(f"Open this in VLC: http://{server_ip}:{self.port}/stream")
        print("=" * 70 + "\n")
    
    def _start_encoder(self) -> None:
        """Start ffmpeg encoder process."""
        try:
            self.encoder_process = subprocess.Popen(
                [
                    "ffmpeg",
                    "-f", "s16le",
                    "-ar", str(self.sample_rate),
                    "-ac", str(self.channels),
                    "-i", "pipe:0",
                    "-f", "mp3",
                    "-b:a", "128k",
                    "-content_type", "audio/mpeg",
                    "pipe:1"
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0  # Unbuffered
            )
            logger.info("[STREAM] FFmpeg encoder started")
        except Exception as e:
            logger.error(f"[STREAM] Failed to start ffmpeg encoder: {e}")
            raise
    
    def _encoder_reader_loop(self) -> None:
        """Read encoded MP3 bytes from ffmpeg stdout and broadcast to clients."""
        if not self.encoder_process or not self.encoder_process.stdout:
            return
        
        chunk_size = 8192  # Read in 8KB chunks
        
        while self._running:
            try:
                mp3_data = self.encoder_process.stdout.read(chunk_size)
                if not mp3_data:
                    # EOF or process ended
                    if self.encoder_process.poll() is not None:
                        logger.warning("[STREAM] FFmpeg encoder process ended")
                        # Try to restart
                        try:
                            self._restart_encoder()
                        except Exception as e:
                            logger.error(f"[STREAM] Failed to restart encoder: {e}")
                        break
                    time.sleep(0.01)  # Small delay to avoid busy-waiting
                    continue
                
                # Broadcast to all connected clients
                self.connection_manager.broadcast(mp3_data)
                
            except Exception as e:
                logger.error(f"[STREAM] Error reading from encoder: {e}")
                break
        
        logger.debug("[STREAM] Encoder reader loop ended")
    
    def write(self, frame: np.ndarray) -> None:
        """
        Write PCM frames into the ffmpeg encoder stdin.
        
        Non-blocking: frames are queued if encoder is busy.
        
        Args:
            frame: numpy array containing PCM audio data
        """
        if not self._running or not self.encoder_process or not self.encoder_process.stdin:
            return
        
        try:
            # Convert numpy array to bytes (s16le format)
            pcm_bytes = frame.tobytes()
            
            # Write to encoder stdin (non-blocking with timeout)
            try:
                self.encoder_process.stdin.write(pcm_bytes)
                self.encoder_process.stdin.flush()
            except BrokenPipeError:
                logger.warning("[STREAM] Encoder stdin broken pipe - encoder may have died")
                self._restart_encoder()
            except Exception as e:
                logger.error(f"[STREAM] Error writing to encoder: {e}")
                
        except Exception as e:
            logger.error(f"[STREAM] Error in write(): {e}")
    
    def _restart_encoder(self) -> None:
        """Restart the encoder process if it died."""
        logger.info("[STREAM] Restarting encoder...")
        try:
            if self.encoder_process:
                try:
                    self.encoder_process.terminate()
                    self.encoder_process.wait(timeout=2)
                except Exception:
                    pass
            
            self._start_encoder()
            logger.info("[STREAM] Encoder restarted successfully")
        except Exception as e:
            logger.error(f"[STREAM] Failed to restart encoder: {e}")
    
    def close(self) -> None:
        """Stop ffmpeg and all HTTP connections."""
        logger.info("[STREAM] Stopping HTTPStreamingSink...")
        
        self._running = False
        
        # Stop HTTP server
        if self.http_server_instance:
            self.http_server_instance.shutdown()
        
        # Close all client connections
        self.connection_manager.close_all()
        
        # Stop encoder
        if self.encoder_process:
            try:
                self.encoder_process.stdin.close()
            except Exception:
                pass
            try:
                self.encoder_process.terminate()
                self.encoder_process.wait(timeout=2)
            except Exception:
                try:
                    self.encoder_process.kill()
                except Exception:
                    pass
            self.encoder_process = None
        
        logger.info("[STREAM] HTTPStreamingSink stopped")

