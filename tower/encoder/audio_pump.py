import os
import time
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

FRAME_DURATION_SEC = 1152 / 48000  # ~0.024s

# Standard PCM frame size: 1152 samples × 2 channels × 2 bytes = 4608 bytes
SILENCE_FRAME_SIZE = 1152 * 2 * 2  # 4608 bytes


class AudioPump:
    """
    Simple working PCM→FFmpeg pump.
    Continuously pulls PCM frames from the ring buffer.
    Implements PCM grace period: uses silence frames during brief gaps,
    falls back to tone only after grace period expires.
    
    Writes PCM frames via encoder_manager.write_pcm() only.
    Never interacts with FFmpegSupervisor directly.
    """

    def __init__(self, pcm_buffer, fallback_generator, encoder_manager):
        self.pcm_buffer = pcm_buffer
        self.fallback = fallback_generator
        self.encoder_manager = encoder_manager
        self.running = False
        self.thread = None
        
        # Grace period configuration
        self.grace_period_sec = float(os.getenv("TOWER_PCM_GRACE_SEC", "5.0"))
        if self.grace_period_sec <= 0:
            self.grace_period_sec = 0  # Disable grace period if zero or negative
        
        # Grace period state
        self.grace_timer_start: Optional[float] = None  # None = grace not active
        
        # Cached silence frame (pre-built at startup per contract [G18])
        self.silence_frame = b'\x00' * SILENCE_FRAME_SIZE

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("AudioPump started")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        logger.info("AudioPump stopped")

    def _run(self):
        next_tick = time.time()

        while self.running:
            # Step 1: Try PCM first with 5ms timeout
            frame = self.pcm_buffer.pop_frame(timeout=0.005)
            
            if frame is not None:
                # PCM frame available: use it and reset grace timer per contract [G7]-[G8]
                self.grace_timer_start = None  # Reset grace timer
            else:
                # PCM buffer empty: check grace period per contract [G4]-[G6]
                now = time.monotonic()
                
                if self.grace_period_sec > 0:
                    # Grace period enabled
                    if self.grace_timer_start is None:
                        # Start grace period (buffer just became empty)
                        self.grace_timer_start = now
                        logger.debug("PCM grace period started")
                    
                    elapsed = now - self.grace_timer_start
                    
                    if elapsed < self.grace_period_sec:
                        # Within grace period: use silence frame per contract [G5]
                        frame = self.silence_frame
                    else:
                        # Grace period expired: use fallback per contract [G6]
                        frame = self.fallback.get_frame()
                else:
                    # Grace period disabled: immediately use fallback
                    frame = self.fallback.get_frame()

            try:
                self.encoder_manager.write_pcm(frame)
            except Exception as e:
                logger.error(f"AudioPump write error: {e}")
                time.sleep(0.1)
                continue

            next_tick += FRAME_DURATION_SEC
            sleep_time = next_tick - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                logger.warning("AudioPump behind schedule")
                next_tick = time.time()  # resync
