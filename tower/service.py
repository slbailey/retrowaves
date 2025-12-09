# tower/service.py

import os
import logging
import threading
import time
from typing import Optional, Dict, Any

from tower.encoder.encoder_manager import EncoderManager, EncoderState
from tower.encoder.ffmpeg_supervisor import SupervisorState
from tower.audio.ring_buffer import FrameRingBuffer
from tower.audio.input_router import AudioInputRouter
from tower.encoder.audio_pump import AudioPump
from tower.fallback.generator import FallbackGenerator
from tower.http.server import HTTPServer
from tower.ingest.pcm_ingestor import PCMIngestor
from tower.ingest.transport import UnixSocketIngestTransport

logger = logging.getLogger(__name__)


class TowerService:
    def __init__(self, encoder_enabled: Optional[bool] = None):
        """
        Initialize TowerService.
        
        Args:
            encoder_enabled: Optional flag to enable/disable encoder (default: None, reads from TOWER_ENCODER_ENABLED)
                           If False or TOWER_ENCODER_ENABLED=0, operates in OFFLINE_TEST_MODE [O6] per [I19]
        """
        # Create buffers
        # PCM buffer accepts 4096-byte frames (1024 samples) from PCM Ingestion
        self.pcm_buffer = FrameRingBuffer(capacity=60, expected_frame_size=4096)
        # Create MP3 buffer explicitly (configurable via TOWER_MP3_BUFFER_CAPACITY_FRAMES)
        # MP3 frames have variable sizes, so no frame size validation
        mp3_buffer_capacity = int(os.getenv("TOWER_MP3_BUFFER_CAPACITY_FRAMES", "400"))
        self.mp3_buffer = FrameRingBuffer(capacity=mp3_buffer_capacity)
        # Pass MP3 buffer to EncoderManager with encoder_enabled flag per [I19]
        # In production, allow_ffmpeg=True per [I25] (tests must explicitly disable)
        # Note: station_shutdown_check will be set after http_server is created
        self.encoder = EncoderManager(
            pcm_buffer=self.pcm_buffer,
            mp3_buffer=self.mp3_buffer,
            encoder_enabled=encoder_enabled,
            allow_ffmpeg=True,  # Production code allows FFmpeg per [I25]
        )
        
        # Create audio input router and fallback generator
        self.router = AudioInputRouter()
        self.fallback = FallbackGenerator()
        
        # Create downstream PCM buffer (feeds FFmpegSupervisor)
        # Per FINDING 001: AudioPump pushes frames to downstream buffer per contract A8
        # EncoderManager reads from this buffer and forwards to supervisor
        # Downstream PCM buffer accepts 4096-byte frames
        self.downstream_pcm_buffer = FrameRingBuffer(capacity=10, expected_frame_size=4096)  # Small buffer for immediate forwarding
        
        # Pass downstream_buffer to EncoderManager per FINDING 001
        # EncoderManager needs access to downstream_buffer to read frames and forward to supervisor
        self.encoder._downstream_buffer = self.downstream_pcm_buffer
        
        # Create audio pump (feeds PCM to encoder)
        # Per contract A10: AudioPump constructor takes pcm_buffer, encoder_manager, downstream_buffer
        self.audio_pump = AudioPump(
            pcm_buffer=self.pcm_buffer,
            encoder_manager=self.encoder,
            downstream_buffer=self.downstream_pcm_buffer
        )
        
        # Create HTTP server (manages its own connection manager internally)
        # Pass PCM buffer as buffer_stats_provider for /tower/buffer endpoint per contract T-BUF5
        # Host and port are configurable via TOWER_HOST and TOWER_PORT env vars
        http_host = os.getenv("TOWER_HOST", "0.0.0.0")
        http_port = int(os.getenv("TOWER_PORT", "8005"))
        self.http_server = HTTPServer(
            host=http_host, 
            port=http_port, 
            frame_source=self.encoder,
            buffer_stats_provider=self.pcm_buffer  # PCM buffer has .stats() method
        )
        
        # Set station shutdown check callback in encoder_manager per contract T-EVENTS5 exception
        # This allows encoder_manager to suppress PCM loss warnings when station is shutting down
        self.encoder._station_shutdown_check = lambda: self.http_server.event_buffer.is_station_shutting_down()
        
        # Create PCM Ingestion subsystem
        # Per contract I43: Deliver to same upstream buffer AudioPump reads from
        # Per contract I12-I16: Transport is implementation-defined (Unix socket)
        socket_path = os.getenv("TOWER_PCM_SOCKET_PATH", "/run/retrowaves/pcm.sock")
        transport = UnixSocketIngestTransport(socket_path)
        self.pcm_ingestor = PCMIngestor(
            upstream_buffer=self.pcm_buffer,  # Same buffer AudioPump reads from
            transport=transport
        )
        
        self.running = False

    def start(self):
        """Start encoder + HTTP server threads."""
        logger.info("=== Tower starting ===")
        
        # Start PCM Ingestion (before AudioPump per contract I51)
        # Per contract I51: PCM Ingestion MUST be ready before AudioPump begins ticking
        self.pcm_ingestor.start()
        logger.info("PCM Ingestion started")
        
        # Start encoder (this also starts the drain thread internally)
        # Per contract [I7.1]: EncoderManager MAY start before AudioPump, but system MUST feed
        # initial silence per [S19] step 4, and AudioPump MUST begin ticking within ≤1 grace period.
        self.encoder.start()
        logger.info("Encoder started")
        
        # Start audio pump
        # Per contract [I7.1]: AudioPump MUST begin ticking within ≤1 grace period (≈21.33ms) after
        # encoder start to ensure continuous PCM delivery per [S7.1] and [M19].
        # The initial silence write in [S19] step 4 covers the tiny window between FFmpeg spawn
        # and AudioPump's first tick.
        # AudioPump ticks at PCM cadence (1024 samples = 21.333ms), not MP3 frame cadence.
        self.audio_pump.start()
        logger.info("AudioPump started")
        
        # Note: EncoderManager.start() already starts the drain thread internally
        # So we just log that it's started as part of encoder startup
        logger.info("EncoderOutputDrain started")
        
        # Start HTTP server (in daemon thread)
        threading.Thread(target=self.http_server.serve_forever, daemon=True).start()
        logger.info("HTTP server listening")
        
        self.running = True
        self.main_loop()

    def main_loop(self):
        """
        Main broadcast loop — frame-driven, no synthetic timing.

        Per TR-TIMING1–4: 
        - Broadcast MP3 frames immediately when available.
        - No independent timing.
        - Bounded wait handled by EncoderManager.
        - No drift possible.

        Per TR-HTTP5:
        - HTTP layer must not sleep, time, or estimate cadence.
        - TowerRuntime simply forwards whatever frames it receives.
        """
        logger.info("Main broadcast loop started (frame-driven, no synthetic timing)")

        while self.running:
            # EncoderManager is the ONLY authoritative source of MP3 frames.
            # TowerRuntime must not pass timeout - EncoderManager handles all timing internally.
            frame = self.encoder.get_frame()

            if frame is None:
                # This should never occur per contract, but handle defensively.
                # Do NOT call fallback directly - fallback is handled inside get_frame().
                # On next iteration, get_frame() will produce fallback itself.
                logger.error("EncoderManager returned None — violating contract. Retrying...")
                continue

            # Broadcast immediately — no sleeps, no pacing, no timing window.
            self.http_server.broadcast(frame)

    def run_forever(self):
        """Block forever like systemd would."""
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def get_mode(self) -> str:
        """
        Get current operational mode per [I18], [I22], [O22].
        
        Per contract [I22]: TowerService MUST be the root owner of Operational Mode state.
        EncoderManager and Supervisor MAY update internal state, but TowerService is responsible
        for exposing and publishing the final operational mode externally.
        
        Returns current operational mode as string:
        - "COLD_START" [O1]: Initial system startup before encoder process is spawned
        - "BOOTING" [O2]: Startup liveness proving - encoder process is running but first MP3 frame has not yet been received
        - "LIVE_INPUT" [O3]: Primary operation - encoder is producing MP3 frames from live PCM input
        - "FALLBACK" [O4]: Tone or silence injection - no live PCM input available
        - "RESTART_RECOVERY" [O5]: Encoder restart in progress
        - "OFFLINE_TEST_MODE" [O6]: Testing mode - FFmpeg encoder is disabled
        - "DEGRADED" [O7]: Maximum restart attempts reached - encoder has failed permanently
        
        Returns:
            str: Current operational mode name
        """
        # Per contract [I18], TowerService exposes mode selection & status
        # Per contract [I22], TowerService is the root owner of operational mode state
        # Per contract [S27], SupervisorState maps to Operational Modes
        
        if not self.encoder._encoder_enabled:
            return "OFFLINE_TEST_MODE"
        
        if self.encoder._supervisor is None:
            encoder_state = self.encoder.get_state()
            if encoder_state == EncoderState.STOPPED:
                return "COLD_START"
            # Should not happen, but fallback
            return "COLD_START"
        
        supervisor_state = self.encoder._supervisor.get_state()
        
        # Per contract [S27], SupervisorState maps to Operational Modes:
        if supervisor_state in (SupervisorState.STOPPED, SupervisorState.STARTING):
            return "COLD_START"
        elif supervisor_state == SupervisorState.BOOTING:
            return "BOOTING"
        elif supervisor_state == SupervisorState.RUNNING:
            # TODO: Could check PCM input status to determine FALLBACK vs LIVE_INPUT
            # For now, assume LIVE_INPUT if RUNNING
            return "LIVE_INPUT"
        elif supervisor_state == SupervisorState.RESTARTING:
            return "RESTART_RECOVERY"
        elif supervisor_state == SupervisorState.FAILED:
            return "DEGRADED"
        
        # Fallback
        return "COLD_START"
    
    def get_state(self) -> Dict[str, Any]:
        """
        Get current system state including operational mode per [I18], [O22].
        
        Returns:
            dict: System state including mode, frame rate, fallback status, etc.
        """
        mode = self.get_mode()
        
        # Calculate frame rate (fps) - MP3 broadcast uses 24ms intervals = ~41.6 fps
        # Note: AudioPump ticks at PCM cadence (21.333ms), but MP3 broadcast remains at 24ms
        FRAME_INTERVAL_MS = 24.0
        fps = 1000.0 / FRAME_INTERVAL_MS
        
        # Get buffer stats
        mp3_stats = self.mp3_buffer.stats()
        
        return {
            "mode": mode,
            "fps": fps,
            "fallback": mode in ("FALLBACK", "BOOTING", "RESTART_RECOVERY", "DEGRADED", "OFFLINE_TEST_MODE"),
            "encoder_state": self.encoder.get_state().name if self.encoder else "UNKNOWN",
            "mp3_buffer_count": mp3_stats.count,
            "mp3_buffer_capacity": mp3_stats.capacity,
            "mp3_buffer_overflow_count": mp3_stats.overflow_count,
        }
    
    def stop(self):
        """
        Stop Tower service.
        
        Per contract [I27]: Service Shutdown Contract
        1. Stop AudioPump (metronome halts)
        2. Stop EncoderManager (which stops Supervisor)
        3. Stop HTTP connection manager (close client sockets)
        4. Stop PCM Ingestion (per contract I53: graceful shutdown)
        5. Wait for all threads to exit (join)
        6. Return only after a fully quiescent system state
        """
        logger.info("Shutting down Tower...")
        
        # Per contract [I27] #2: Stop HTTP broadcast thread first (via self.running = False)
        # This stops the main_loop() which is running in the current thread
        self.running = False
        
        # Per contract [I27] #1: Stop AudioPump (metronome halts)
        self.audio_pump.stop()
        
        # Per contract [I27] #2: Stop EncoderManager (which stops Supervisor)
        self.encoder.stop()
        
        # Per contract I53: Stop PCM Ingestion gracefully
        self.pcm_ingestor.stop()
        
        # Per contract [I27] #3: Stop HTTP server (close client sockets)
        # HTTPServer now owns client management directly
        
        # Per contract [I27] #1: Ensure AudioPump thread has fully stopped
        if self.audio_pump.thread and self.audio_pump.thread.is_alive():
            self.audio_pump.thread.join(timeout=1.0)
            if self.audio_pump.thread.is_alive():
                logger.warning("AudioPump thread did not stop within timeout")
        
        # Per contract [I27] #4: Wait for all threads to exit (join)
        # HTTP server runs in daemon thread, so it will terminate when main thread exits
        # But we explicitly stop it to close the socket
        self.http_server.stop()
        
        # Per contract [I27] #5: Return only after a fully quiescent system state
        # Verify no critical threads are still running
        import threading
        active_threads = [t for t in threading.enumerate() if t != threading.current_thread() and not t.daemon]
        if active_threads:
            logger.warning(f"Non-daemon threads still running after shutdown: {[t.name for t in active_threads]}")
        
        logger.info("Tower service stopped")
