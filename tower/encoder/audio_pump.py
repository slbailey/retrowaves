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
    Continuously calls encoder_manager.next_frame() at 24ms intervals.
    
    Per contract [A3], [A7]: AudioPump DOES NOT route audio. It calls encoder_manager.next_frame()
    each tick. All routing decisions (PCM vs fallback, thresholds, operational modes) are made
    inside EncoderManager.
    
    Per contract [A1], [A4]: AudioPump is Tower's sole metronome - the only clock in the system.
    Never interacts with FFmpegSupervisor directly.
    """

    def __init__(self, pcm_buffer, fallback_generator, encoder_manager):
        self.pcm_buffer = pcm_buffer
        self.fallback = fallback_generator
        self.encoder_manager = encoder_manager
        self.running = False
        self.thread = None

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
        tick_index = 0

        while self.running:
            # Telemetry: Log first PCM frame generated
            if tick_index == 0:
                logger.info("AUDIO_PUMP: first PCM frame generated")
            
            # Per contract [A3], [A7]: AudioPump calls encoder_manager.next_frame() each tick
            # EncoderManager handles ALL routing decisions internally (operational mode, thresholds, etc.)
            # AudioPump does not choose PCM vs fallback — routing is inside EncoderManager
            try:
                self.encoder_manager.next_frame(self.pcm_buffer)
            except Exception as e:
                logger.error(f"AudioPump next_frame error: {e}")
                time.sleep(0.1)
                continue

            tick_index += 1
            next_tick += FRAME_DURATION_SEC
            sleep_time = next_tick - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                logger.warning("AudioPump behind schedule")
                next_tick = time.time()  # resync
