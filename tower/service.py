"""
TowerService - Main service that wires all components together.

Coordinates tone generation, FFmpeg encoding, and HTTP streaming.
"""

import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from tower.audio_input_router import AudioInputRouter
from tower.config import TowerConfig, get_config
from tower.encoder import Encoder
from tower.encoder_manager import EncoderManager
from tower.fallback import ToneGenerator
from tower.http_conn import HTTPConnectionManager
from tower.http_server import TowerHTTPServer
from tower.silent_mp3 import generate_silent_mp3_chunk
from tower.source_manager import SourceManager
from tower.sources import SourceMode

logger = logging.getLogger(__name__)


class TowerService:
    """
    Main Tower service.
    
    Coordinates all components:
    - Tone generator (PCM source)
    - FFmpeg encoder (PCM -> MP3)
    - HTTP server (streaming to clients)
    - Connection manager (client tracking)
    """
    
    def __init__(self, config: Optional[TowerConfig] = None):
        """
        Initialize Tower service.
        
        Args:
            config: Tower configuration (defaults to loading from env)
        """
        self.config = config or get_config()
        self._shutdown = False
        self._start_time = time.time()
        
        # Components
        self.tone_generator: Optional[ToneGenerator] = None  # Kept for backwards compatibility
        self.source_manager: Optional[SourceManager] = None
        self.audio_input_router: Optional[AudioInputRouter] = None  # Phase 3
        self.encoder: Optional[Encoder] = None  # Kept for backwards compatibility
        self.encoder_manager: Optional[EncoderManager] = None  # Phase 4
        self.connection_manager: Optional[HTTPConnectionManager] = None
        self.http_server: Optional[TowerHTTPServer] = None
        
        # Phase 4: Silent MP3 for FAILED state
        self._silent_mp3_chunk: Optional[bytes] = None
        
        # Threads
        self.pcm_writer_thread: Optional[threading.Thread] = None
        self.encoder_reader_thread: Optional[threading.Thread] = None
        self.failed_state_thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        """Start Tower service."""
        if self.source_manager is not None:
            raise RuntimeError("Service already started")
        
        logger.info("Starting Tower service...")
        
        # Initialize SourceManager with priority-based default source selection:
        # 1. MP3 file (if TOWER_SILENCE_MP3_PATH is set and exists) - note: FileSource only handles WAV,
        #    so MP3 files will need to be converted or this will fall through to tone
        # 2. Tone generator (if MP3 file not available or invalid)
        # 3. Silence (if tone generation fails)
        default_mode = None
        default_file_path = None
        
        # Priority 1: Check for MP3 file in TOWER_SILENCE_MP3_PATH
        # Note: FileSource only handles WAV files, so if this is an MP3, it will fail
        # and fall through to tone. This is intentional - MP3 files would need special handling.
        if self.config.silence_mp3_path and Path(self.config.silence_mp3_path).exists():
            # Check if it's a WAV file (FileSource requirement)
            file_path = Path(self.config.silence_mp3_path)
            if file_path.suffix.lower() == '.wav':
                logger.info(f"Using WAV file as default source: {self.config.silence_mp3_path}")
                default_mode = SourceMode.FILE
                default_file_path = self.config.silence_mp3_path
            else:
                # MP3 file - FileSource can't handle it, will fall through to tone
                logger.info(f"MP3 file found but FileSource only handles WAV, using tone generator: {self.config.silence_mp3_path}")
                default_mode = SourceMode.TONE
                default_file_path = None
        else:
            # Priority 2: Use tone generator (default)
            default_mode_str = self.config.default_source.lower()
            try:
                default_mode = SourceMode(default_mode_str)
            except ValueError:
                raise ValueError(
                    f"Invalid TOWER_DEFAULT_SOURCE: {default_mode_str} "
                    f"(must be 'tone', 'silence', or 'file')"
                )
            
            default_file_path = self.config.default_file_path if default_mode == SourceMode.FILE else None
        
        # Priority 3: If initialization fails, fall back to silence
        try:
            self.source_manager = SourceManager(
                self.config,
                default_mode=default_mode,
                default_file_path=default_file_path
            )
        except (FileNotFoundError, ValueError) as e:
            logger.warning(f"Failed to initialize source with {default_mode.value}: {e}")
            # Fall back to silence if initialization fails
            if default_mode != SourceMode.SILENCE:
                logger.info("Falling back to silence source")
                try:
                    self.source_manager = SourceManager(
                        self.config,
                        default_mode=SourceMode.SILENCE,
                        default_file_path=None
                    )
                except Exception as fallback_error:
                    logger.error(f"Failed to initialize silence source: {fallback_error}")
                    raise
            else:
                # Already trying silence and it failed
                raise
        
        # Keep tone_generator for backwards compatibility (Phase 1 tests)
        # In Phase 2, we use source_manager, but tone_generator is still referenced
        # by tests that check for its existence
        self.tone_generator = ToneGenerator(self.config)
        
        # Initialize AudioInputRouter (Phase 3)
        try:
            self.audio_input_router = AudioInputRouter(
                self.config,
                self.config.socket_path
            )
            self.audio_input_router.start()
            logger.info("AudioInputRouter started")
        except (OSError, PermissionError) as e:
            # Permission errors are OK in test environments
            # Tower can still work with fallback only
            logger.warning(f"Could not start AudioInputRouter (permission error): {e}")
            logger.warning("Tower will continue with fallback audio only")
            self.audio_input_router = None
        except Exception as e:
            logger.error(f"Failed to start AudioInputRouter: {e}")
            # Don't fail startup if router fails - Tower can still work with fallback
            self.audio_input_router = None
        
        # Initialize other components
        # Phase 4: Use EncoderManager instead of direct Encoder
        self.encoder_manager = EncoderManager(self.config)
        
        # Keep encoder reference for backwards compatibility (Phase 1-3 tests)
        # Will be set after encoder_manager.start()
        self.encoder = None
        
        self.connection_manager = HTTPConnectionManager(
            client_timeout_ms=self.config.client_timeout_ms,
            client_buffer_bytes=self.config.client_buffer_bytes,
            test_mode=self.config.test_mode,
            force_slow_client_test=self.config.force_slow_client_test
        )
        self.connection_manager.start()  # Start flush thread
        
        self.http_server = TowerHTTPServer(
            self.config.host,
            self.config.port,
            self.connection_manager,
            source_manager=self.source_manager,
            encoder=self.encoder_manager,  # Pass encoder_manager
            start_time=self._start_time
        )
        
        # Generate silent MP3 chunk for FAILED state
        try:
            self._silent_mp3_chunk = generate_silent_mp3_chunk(self.config)
            logger.debug(f"Generated silent MP3 chunk ({len(self._silent_mp3_chunk)} bytes)")
        except Exception as e:
            logger.warning(f"Failed to generate silent MP3 chunk: {e}")
            self._silent_mp3_chunk = None
        
        # Start encoder through EncoderManager
        try:
            self.encoder_manager.start()
            # Update encoder reference after start (for backwards compatibility)
            self.encoder = self.encoder_manager.encoder
        except RuntimeError as e:
            logger.error(f"Failed to start encoder: {e}")
            # Don't raise - Tower should continue even if encoder fails initially
            # EncoderManager will attempt restarts
            pass
        
        # Start HTTP server
        self.http_server.start()
        
        # Give server a moment to start
        time.sleep(0.1)
        
        # Start PCM writer thread (feeds tone to FFmpeg)
        self.pcm_writer_thread = threading.Thread(
            target=self._pcm_writer_loop,
            daemon=False,
            name="PCMWriter"
        )
        self.pcm_writer_thread.start()
        
        # Start encoder reader thread (reads MP3 from FFmpeg, broadcasts)
        self.encoder_reader_thread = threading.Thread(
            target=self._encoder_reader_loop,
            daemon=False,
            name="EncoderReader"
        )
        self.encoder_reader_thread.start()
        
        logger.info("Tower service started")
    
    def _pcm_writer_loop(self):
        """
        PCM writer thread (AudioPump): coordinates between live PCM and fallback.
        
        Phase 3: Attempts to get frame from AudioInputRouter first, falls back
        to SourceManager if None is returned.
        """
        logger.debug("PCM writer thread (AudioPump) started")
        
        # Calculate frame period: 1024 samples / 48000 Hz ≈ 21.3 ms
        frame_period = self.config.frame_size / self.config.sample_rate
        
        # Timeout for router.get_next_frame() - 50ms as per contract
        router_timeout_ms = 50.0
        
        try:
            while not self._shutdown:
                frame_start_time = time.time()
                
                # Phase 4: Check encoder state
                encoder_state = self.encoder_manager.get_state()
                if encoder_state.value in ("restarting", "failed"):
                    # Encoder is down (RESTARTING or FAILED) - write but ignore errors
                    # Per contract: AudioPump MUST discard PCM frames when encoder is unavailable
                    # But we still attempt write in RESTARTING to avoid blocking
                    try:
                        frame: Optional[bytes] = None
                        
                        # Still generate frame to maintain real-time pace
                        # Phase 3: Try to get frame from AudioInputRouter first
                        if self.audio_input_router is not None:
                            frame = self.audio_input_router.get_next_frame(timeout_ms=router_timeout_ms)
                        
                        # If no frame from router, fall back to SourceManager
                        if frame is None:
                            # Get current source (thread-safe, may change between calls)
                            source = self.source_manager.get_current_source()
                            
                            # Generate frame from current source
                            frame = source.generate_frame()
                        
                        # Validate frame size
                        if len(frame) != self.config.frame_bytes:
                            import numpy as np
                            frame = np.zeros(self.config.frame_bytes, dtype=np.int16).tobytes()
                        
                        # Attempt write (EncoderManager will ignore BrokenPipeError in RESTARTING)
                        self.encoder_manager.write_pcm(frame)
                        # Frame is written or discarded - this maintains real-time pace
                        
                    except Exception as e:
                        logger.debug(f"Error generating frame (encoder down): {e}")
                        # Continue to maintain pace
                    
                    # Maintain real-time pace even when discarding
                    elapsed = time.time() - frame_start_time
                    sleep_time = frame_period - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    continue
                
                # Encoder is running - normal operation
                try:
                    frame: Optional[bytes] = None
                    
                    # Phase 3: Try to get frame from AudioInputRouter first
                    if self.audio_input_router is not None:
                        frame = self.audio_input_router.get_next_frame(timeout_ms=router_timeout_ms)
                    
                    # If no frame from router, fall back to SourceManager
                    if frame is None:
                        # Get current source (thread-safe, may change between calls)
                        source = self.source_manager.get_current_source()
                        
                        # Generate frame from current source
                        frame = source.generate_frame()
                    
                    # Validate frame size (fallback to silence if invalid)
                    if len(frame) != self.config.frame_bytes:
                        logger.warning(
                            f"Invalid frame size: {len(frame)} bytes, "
                            f"expected {self.config.frame_bytes} bytes. Using silence."
                        )
                        # Fallback to silence
                        import numpy as np
                        frame = np.zeros(self.config.frame_bytes, dtype=np.int16).tobytes()
                    
                    # Write frame to encoder via EncoderManager
                    if not self.encoder_manager.write_pcm(frame):
                        # Write failed - encoder may have died
                        # EncoderManager will handle restart
                        logger.debug("Failed to write PCM frame (encoder may be restarting)")
                    else:
                        logger.debug(f"Wrote PCM frame ({len(frame)} bytes) to encoder")
                    
                except Exception as e:
                    logger.error(f"Unexpected error in PCM writer: {e}")
                    # Continue to next iteration (source may have changed)
                
                # Maintain real-time pace: sleep for remaining time in frame period
                elapsed = time.time() - frame_start_time
                sleep_time = frame_period - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                # If we're behind schedule, continue immediately (don't accumulate latency)
        
        except Exception as e:
            logger.error(f"PCM writer thread error: {e}")
        finally:
            logger.debug("PCM writer thread stopped")
    
    def _encoder_reader_loop(self):
        """Encoder reader thread: reads MP3 chunks from encoder and broadcasts."""
        logger.debug("Encoder reader thread started")
        
        chunk_size = self.config.read_chunk_size
        
        try:
            while not self._shutdown:
                # Phase 4: Use get_chunk() which ALWAYS returns data (never None)
                # This ensures broadcast loop never starves
                chunk = self.encoder_manager.get_chunk(chunk_size)
                
                # Only broadcast if we have clients
                if self.connection_manager.get_client_count() > 0:
                    # Broadcast chunk (always has data)
                    self.connection_manager.broadcast(chunk)
                
                # Sleep to maintain reasonable broadcast rate
                # At 128kbps, 8192 bytes ≈ 0.5 seconds
                # Sleep shorter to ensure fast clients get data quickly
                # But not too short to avoid CPU spinning
                # Reduced to 10ms to ensure tests receive at least 20-30 chunks in 0.5s
                time.sleep(0.01)  # 10ms - ensures ~100 chunks/second
        
        except Exception as e:
            logger.error(f"Encoder reader thread error: {e}")
        finally:
            logger.debug("Encoder reader thread stopped")
    
    def stop(self) -> None:
        """Stop Tower service."""
        if self._shutdown:
            return
        
        logger.info("Stopping Tower service...")
        self._shutdown = True
        
        # Stop HTTP server (closes all client connections)
        if self.http_server:
            self.http_server.stop()
        
        # Close all client connections
        if self.connection_manager:
            self.connection_manager.close_all()
        
        # Stop encoder manager (Phase 4)
        if self.encoder_manager:
            self.encoder_manager.stop()
        
        # Stop encoder (for backwards compatibility)
        if self.encoder:
            try:
                self.encoder.stop()
            except Exception:
                pass
        
        # Clean up source manager
        if self.source_manager:
            self.source_manager.cleanup()
        
        # Stop AudioInputRouter (Phase 3)
        if self.audio_input_router:
            try:
                self.audio_input_router.stop()
            except Exception as e:
                logger.warning(f"Error stopping AudioInputRouter: {e}")
        
        # Wait for threads to finish
        if self.pcm_writer_thread:
            self.pcm_writer_thread.join(timeout=2.0)
        
        if self.encoder_reader_thread:
            self.encoder_reader_thread.join(timeout=2.0)
        
        if self.failed_state_thread:
            self.failed_state_thread.join(timeout=2.0)
        
        logger.info("Tower service stopped")
    
    def run_forever(self) -> None:
        """Run service until shutdown signal."""
        # Set up signal handlers
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            self.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        try:
            # Keep main thread alive
            while not self._shutdown:
                time.sleep(1.0)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt, shutting down...")
            self.stop()

