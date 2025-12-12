"""
PCM Ingestion subsystem for Tower.

Per NEW_PCM_INGEST_CONTRACT: PCM Ingestion accepts canonical PCM frames from
upstream providers and delivers them to Tower's upstream PCM buffer.

PCM Ingestion is a pure transport layer that:
- Validates frame size (exactly 4096 bytes)
- Delivers valid frames immediately
- Discards malformed/incomplete frames safely
- Never blocks, transforms, or modifies data
"""

import logging
import threading
from typing import Optional

from tower.audio.ring_buffer import FrameRingBuffer
from tower.ingest.transport import IngestTransport

logger = logging.getLogger(__name__)

# Setup file handler for contract-compliant logging (LOG1, LOG2, LOG3, LOG4)
# Per contract: /var/log/retrowaves/tower.log, non-blocking, rotation-tolerant
try:
    import logging.handlers
    # Use WatchedFileHandler for rotation tolerance (per LOG3)
    handler = logging.handlers.WatchedFileHandler('/var/log/retrowaves/tower.log', mode='a')
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    # Wrap emit to handle write failures gracefully (per LOG4)
    original_emit = handler.emit
    def safe_emit(record):
        try:
            original_emit(record)
        except (IOError, OSError):
            # Logging failures degrade silently per contract LOG4
            pass
    handler.emit = safe_emit
    # Prevent duplicate handlers on module reload
    if not any(isinstance(h, logging.handlers.WatchedFileHandler)
               and getattr(h, 'baseFilename', None) == '/var/log/retrowaves/tower.log'
               for h in logger.handlers):
        logger.addHandler(handler)
    logger.propagate = False  # Avoid duplicate logs
except Exception:
    # Logging must never crash component per LOG4
    # Catch all exceptions (including I/O errors) to prevent import-time failures
    pass

# Canonical frame size per contract I7
FRAME_SIZE_BYTES = 4096


class PCMIngestor:
    """
    PCM Ingestion subsystem.
    
    Per NEW_PCM_INGEST_CONTRACT:
    - Accepts PCM frames via configured transport (I1)
    - Validates frame size (4096 bytes) (I7, I8, I11, I47)
    - Delivers valid frames immediately (I2, I37)
    - Discards malformed frames safely (I3, I18, I19)
    - Never blocks, transforms, or modifies data (I4, I30, I34, I36)
    """
    
    def __init__(self, upstream_buffer: FrameRingBuffer, transport: IngestTransport):
        """
        Initialize PCM Ingestor.
        
        Args:
            upstream_buffer: FrameRingBuffer to deliver valid frames to.
                            Per contract I43: Same buffer AudioPump reads from.
            transport: IngestTransport implementation (Unix socket, TCP, etc.)
                      Per contract I12-I16: Transport is implementation-defined.
        """
        self.upstream_buffer = upstream_buffer
        self.transport = transport
        
        # Per contract I35: Buffer only for atomic frame delivery
        # Accumulate bytes until we have complete 4096-byte frames
        self._accumulator = bytearray()
        self._accumulator_lock = threading.Lock()
        
        # Per contract I17: Never crash on malformed input
        # Statistics (optional per I55)
        self._frames_received = 0
        self._frames_discarded = 0
        self._running = False
    
    def start(self) -> None:
        """
        Start PCM Ingestion.
        
        Per contract I51: Must be ready before AudioPump begins ticking.
        Per contract I52: Continues accepting frames until explicitly stopped.
        """
        if self._running:
            logger.warning("PCMIngestor already started")
            return
        
        self._running = True
        
        # Register callback with transport
        # Per contract I16: Transport calls callback with raw bytes
        self.transport.start(on_bytes_callback=self._on_bytes_received)
        
        logger.info("PCM Ingestion started")
    
    def stop(self) -> None:
        """
        Stop PCM Ingestion gracefully.
        
        Per contract I53: Stop accepting new connections, finish processing
        in-flight frames, close transport connections cleanly.
        """
        if not self._running:
            return
        
        logger.info("Stopping PCM Ingestion...")
        self._running = False
        
        # Stop transport
        self.transport.stop()
        
        # Discard any remaining partial frame in accumulator
        # Per contract I19: No repair attempts
        with self._accumulator_lock:
            if len(self._accumulator) > 0:
                logger.debug(f"Discarding {len(self._accumulator)} bytes of partial frame on shutdown")
                self._frames_discarded += 1
                self._accumulator.clear()
        
        logger.info("PCM Ingestion stopped")
    
    def _on_bytes_received(self, data: bytes) -> None:
        """
        Handle bytes received from transport.
        
        Per contract I16: Transport provides raw bytes, no validation.
        This method accumulates bytes and extracts complete 4096-byte frames.
        
        Args:
            data: Raw bytes from transport (any size chunk)
        """
        if not self._running:
            return
        
        # Per contract I17: Never crash on malformed input
        try:
            with self._accumulator_lock:
                # Add new bytes to accumulator
                self._accumulator.extend(data)
                
                # Extract complete 4096-byte frames
                # Per contract I5, I10: Frames must be atomic (complete or not at all)
                while len(self._accumulator) >= FRAME_SIZE_BYTES:
                    # Extract one complete frame
                    frame = bytes(self._accumulator[:FRAME_SIZE_BYTES])
                    self._accumulator = self._accumulator[FRAME_SIZE_BYTES:]
                    
                    # Per contract I47: Validate frame size before delivery
                    if len(frame) == FRAME_SIZE_BYTES:
                        # Per contract I2, I37: Deliver immediately upon validation
                        self._deliver_frame(frame)
                    else:
                        # Should not happen (we checked >= FRAME_SIZE_BYTES)
                        # But per contract I19: Discard if not complete
                        logger.debug(f"Frame size validation failed: {len(frame)} != {FRAME_SIZE_BYTES}")
                        self._frames_discarded += 1
                        
        except Exception as e:
            # Per contract I17: Never crash on malformed input
            logger.debug(f"Error processing bytes: {e}")
            self._frames_discarded += 1
    
    def _deliver_frame(self, frame: bytes) -> None:
        """
        Deliver a validated frame to upstream buffer.
        
        Per contract I2, I37: Deliver immediately upon validation.
        Per contract I38: Preserve atomicity (complete frame or nothing).
        Per contract I39: Never write partial frames.
        Per contract I41: Respect buffer overflow policy.
        Per contract I64: Never delay based on buffer fill level.
        
        Args:
            frame: Complete 4096-byte frame (already validated)
        """
        # Per contract I47: Frame must be exactly 4096 bytes
        assert len(frame) == FRAME_SIZE_BYTES, f"Frame must be {FRAME_SIZE_BYTES} bytes"
        
        try:
            # Per contract I2, I37, I64: Write immediately, no delay
            # Per contract I41: Buffer handles overflow (drops oldest)
            self.upstream_buffer.push_frame(frame)
            self._frames_received += 1
            
        except Exception as e:
            # Per contract I17, I23: Handle full buffer gracefully
            # Buffer.push_frame() should not raise, but handle just in case
            logger.debug(f"Error delivering frame to buffer: {e}")
            self._frames_discarded += 1
    
    def get_stats(self) -> dict:
        """
        Get ingestion statistics (optional per contract I55).
        
        Returns:
            dict: Statistics including frames_received, frames_discarded
        """
        with self._accumulator_lock:
            return {
                "frames_received": self._frames_received,
                "frames_discarded": self._frames_discarded,
                "partial_frame_bytes": len(self._accumulator),
            }

