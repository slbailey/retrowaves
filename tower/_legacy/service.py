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

import numpy as np

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
            encoder_manager=self.encoder_manager,
            audio_input_router=self.audio_input_router,
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
        # Per Phase 1 contract 8.4: Tower should prefer staying alive and streaming tone
        # rather than exiting on non-critical errors. Encoder startup failure is non-critical.
        try:
            self.encoder_manager.start()
            # Update encoder reference after start (for backwards compatibility)
            self.encoder = self.encoder_manager.encoder
        except RuntimeError as e:
            logger.error(f"Failed to start encoder: {e}")
            # Don't raise - Tower should continue even if encoder fails initially
            # EncoderManager will attempt restarts. Tower can continue operating
            # and will stream tone once encoder recovers.
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
        
        Phase 3: Every tick (21.33ms):
        1. Try to pop frame from ring buffer (non-blocking)
        2. If None, use silence frame
        3. Always write to encoder stdin (never close or restart encoder)
        
        This ensures seamless switching - no encoder restarts, no client disconnects.
        """
        logger.debug("PCM writer thread (AudioPump) started")
        
        # Calculate frame period: 1024 samples / 48000 Hz ≈ 21.33 ms
        # Tower's pump is the receiver-side metronome - must pull frames at exactly this rate
        FRAME_DURATION = self.config.frame_size / self.config.sample_rate  # ~0.021333 seconds
        
        # Minimal timeout for router.get_next_frame() - must be much shorter than frame period
        # If queue has frames, pop() returns immediately. If empty, timeout very quickly.
        router_timeout_ms = 5.0  # 5ms timeout - very short to avoid blocking
        
        # Absolute clock timing - prevents cumulative drift
        next_frame_time = time.time()
        
        # INFINITE LOOP - never exits except on shutdown
        # This ensures PCM frames continue to be written to encoder stdin regardless of:
        # - Source switching (live <-> fallback)
        # - Encoder restarts
        # - Client disconnects
        # - Input switching
        while not self._shutdown:
            try:
                # Tower's pump is the receiver-side metronome - pull frames at exactly 21.33ms intervals
                # This ensures queue never fills because we consume at the same rate Station produces
                frame: Optional[bytes] = None
                
                # Step 1: Try to get frame from ring buffer (non-blocking)
                # Switching live<->fallback only affects which source generates the frame here,
                # not the MP3 streaming output (which is handled by encoder reader loop)
                if self.audio_input_router is not None and not self.audio_input_router.router_dead:
                    # Try non-blocking pop first (if queue has frames, returns immediately)
                    frame = self.audio_input_router.get_next_frame(timeout_ms=router_timeout_ms)
                
                # Step 2: If ring buffer is empty, check grace period before fallback
                # This ensures continuous stream - tone is injected when buffer empty, not by stopping pump
                # Switching is seamless - no encoder restart, no client disconnect
                # Source switching only affects which source generates the frame, not streaming output
                if frame is None:
                    # Check grace period: if PCM was available within grace period, use silence
                    # Otherwise, use fallback source (tone/file)
                    # This prevents tone blips during short gaps between MP3 tracks
                    use_fallback = True
                    if self.audio_input_router is not None and not self.audio_input_router.router_dead:
                        # Check if PCM is available within grace period (default 5 seconds)
                        if self.audio_input_router.pcm_available(grace_sec=self.config.pcm_grace_sec):
                            # Within grace period - use silence frame to maintain continuous stream
                            # This prevents tone blips during MP3 track switching
                            frame = np.zeros(self.config.frame_bytes, dtype=np.int16).tobytes()
                            use_fallback = False
                    
                    if use_fallback:
                        # Grace period expired or no router - get fallback frame from current source (tone/silence/file)
                        # This is where source switching affects input - but streaming output is independent
                        source = self.source_manager.get_current_source()
                        frame = source.generate_frame()
                
                # Step 3: Always write to encoder stdin (never close or restart)
                # Switching is seamless - encoder stdin remains open, we just change the source of frames
                # The encoder reader loop is independent and continues reading MP3 chunks regardless
                # Validate frame size before writing
                if len(frame) != self.config.frame_bytes:
                    # Frame size mismatch - truncate or pad as needed
                    if len(frame) > self.config.frame_bytes:
                        frame = frame[:self.config.frame_bytes]
                    else:
                        # Pad with silence
                        padded = np.zeros(self.config.frame_bytes, dtype=np.int16).tobytes()
                        padded[:len(frame)] = frame
                        frame = padded
                
                try:
                    self.encoder_manager.write_pcm(frame)
                except Exception as e:
                    logger.debug(f"Error writing PCM frame: {e}")
                    # Continue to maintain pace even if write fails
                
                # CRITICAL: Real-time pacing HERE (Tower is receiver-side metronome)
                # Absolute clock timing - avoids cumulative drift
                next_frame_time += FRAME_DURATION
                sleep_time = next_frame_time - time.time()
                
                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    # If we fall behind, resync instead of accumulating delay
                    next_frame_time = time.time()
                    
            except Exception as e:
                # Per Phase 1 contract 8.4: Tower should prefer staying alive and streaming tone
                # rather than exiting on non-critical errors. Log and CONTINUE the loop.
                # The loop must be infinite and survive all errors except shutdown.
                logger.error(f"PCM writer thread error (continuing): {e}", exc_info=True)
                # Continue the loop - don't exit
                # Add a small delay to prevent tight error loops, then resync timing
                time.sleep(0.1)
                next_frame_time = time.time()
        
        logger.debug("PCM writer thread stopped (shutdown)")
    
    def _encoder_reader_loop(self):
        """
        Encoder reader thread: reads MP3 chunks from ring buffer and broadcasts.
        
        This loop is INFINITE and survives:
        - Source switching (live <-> fallback)
        - Encoder restarts
        - Client disconnects
        - Input switching
        
        The loop never exits except on service shutdown.
        
        Architecture:
        - PCM writer loop → encoder.stdin
        - Encoder stdout → drain thread → ring buffer → get_chunk() → broadcast()
        - This loop NEVER touches encoder.stdout directly
        """
        logger.debug("Encoder reader thread started")
        
        chunk_size = 1024  # Small chunk size for responsive streaming
        
        # INFINITE LOOP - never exits except on shutdown
        # This ensures broadcast continues regardless of source switching, encoder state, etc.
        # Pattern: while running: chunk = get_chunk(); broadcast(chunk); sleep
        while not self._shutdown:
            try:
                # Get MP3 chunk from ring buffer (non-blocking, always returns data)
                # get_chunk() reads from ring buffer only - never touches encoder.stdout
                # Returns real MP3 if available, silent MP3 if buffer empty
                chunk = self.encoder_manager.get_chunk(chunk_size)
                
                # Broadcast to all clients (enqueues to per-client queues)
                # This continues even if no clients are connected (chunks are just dropped)
                # but we check to avoid unnecessary work
                if self.connection_manager.get_client_count() > 0:
                    # Broadcast chunk (always has data - real or silent)
                    # This enqueues to all client queues - switching live<->fallback
                    # only affects what PCM frames go to ffmpeg stdin, not what MP3
                    # chunks are broadcast here
                    # Wrap broadcast in try/except to ensure individual client failures
                    # don't stop the broadcast loop
                    try:
                        self.connection_manager.broadcast(chunk)
                    except Exception as broadcast_error:
                        # Broadcast failure should not stop the encoder read loop
                        # Individual client failures are handled inside broadcast()
                        # This catch is for unexpected broadcast() exceptions
                        logger.debug(f"Broadcast error (continuing): {broadcast_error}")
                        # Continue - don't let broadcast failures stop broadcast loop
                
                # Small sleep to avoid CPU spinning while maintaining responsive streaming
                # 10-20ms sleep provides good balance between responsiveness and CPU usage
                time.sleep(0.015)  # 15ms - ensures ~66 chunks/second
                
            except Exception as e:
                # Per Phase 1 contract 8.4: Tower should prefer staying alive and streaming tone
                # rather than exiting on non-critical errors. Log and CONTINUE the loop.
                # The loop must be infinite and survive all errors except shutdown.
                logger.error(f"Encoder reader thread error (continuing): {e}", exc_info=True)
                # Continue the loop - don't exit
                # Add a small delay to prevent tight error loops
                time.sleep(0.015)  # Brief sleep before retry
        
        logger.debug("Encoder reader thread stopped (shutdown)")
    
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

