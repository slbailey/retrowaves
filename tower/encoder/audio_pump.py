import time
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# PCM frame cadence: 1024 samples at 48kHz = 21.333ms
# Per contract C1: PCM cadence is the global timing authority
FRAME_SIZE_SAMPLES = 1024
SAMPLE_RATE = 48000
FRAME_DURATION_SEC = FRAME_SIZE_SAMPLES / SAMPLE_RATE  # 0.0213333333s (21.333ms)

# Standard PCM frame size: 1024 samples × 2 channels × 2 bytes = 4096 bytes
SILENCE_FRAME_SIZE = FRAME_SIZE_SAMPLES * 2 * 2  # 4096 bytes


class AudioPump:
    """
    Simple working PCM→FFmpeg pump.
    Continuously calls encoder_manager.next_frame() at PCM cadence (1024 samples = 21.333ms).
    
    Per contract C1.3: AudioPump operates at PCM cadence (21.333ms).
    Per contract C7.1: AudioPump is the system timing authority at PCM cadence.
    
    Per contract [A3], [A7]: AudioPump DOES NOT route audio. It calls encoder_manager.next_frame()
    each tick. All routing decisions (PCM vs fallback, thresholds, operational modes) are made
    inside EncoderManager.
    
    Per contract [A1], [A4]: AudioPump is Tower's sole metronome - the only clock in the system.
    Never interacts with FFmpegSupervisor directly.
    
    Per contract [A10]: Constructor takes pcm_buffer, encoder_manager, downstream_buffer.
    Per contract [A5]: Calls encoder_manager.next_frame() with NO arguments.
    Per contract [A5.4]: Pushes returned frame to downstream_buffer (NOT via write_pcm() per A8).
    
    AudioPump ticks at PCM cadence (1024 samples = 21.333ms).
    Per contract C1.3 and C7.1: AudioPump is the global timing authority at PCM cadence.
    """

    def __init__(self, pcm_buffer, encoder_manager, downstream_buffer):
        """
        Initialize AudioPump per contract [A10].
        
        Args:
            pcm_buffer: Upstream PCM input buffer (from Station/upstream feeder)
            encoder_manager: EncoderManager instance (routing authority)
            downstream_buffer: Downstream PCM buffer feeding FFmpegSupervisor
        """
        self.pcm_buffer = pcm_buffer
        self.encoder_manager = encoder_manager
        self.downstream_buffer = downstream_buffer
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
        """
        Main tick loop per contract [A4], [A5], [A6].
        
        Per contract [A4]: Runs at PCM cadence (1024 samples = 21.333ms).
        Per contract [A5]: Calls encoder_manager.next_frame() with NO arguments each tick.
        Per contract [A5.4]: Pushes returned frame to downstream buffer (NOT via write_pcm() per A8).
        Per contract [A12], [A13]: Handles errors gracefully, never stops ticking.
        """
        # Per contract [A4]: Use absolute clock timing to prevent drift
        next_tick = time.monotonic()
        tick_index = 0

        while self.running:
            # Telemetry: Log first PCM frame generated
            if tick_index == 0:
                logger.info("AUDIO_PUMP: first PCM frame generated")
            
            # DEBUG: Diagnostic logging - buffer count on every tick
            buffer_stats = self.pcm_buffer.stats()
            logger.debug(f"Tick start. Buffer count={buffer_stats.count}")
            
            # Per contract [A5]: AudioPump calls encoder_manager.next_frame() with NO arguments
            # EncoderManager reads from its internal buffer (populated via write_pcm() from upstream)
            # EncoderManager handles ALL routing decisions internally (operational mode, thresholds, etc.)
            # AudioPump does not choose PCM vs fallback — routing is inside EncoderManager
            try:
                # Per contract [A5]: Call next_frame() with NO arguments
                # EncoderManager returns exactly one PCM frame (program, silence, or fallback)
                frame = self.encoder_manager.next_frame()
                
                # Per contract [A5.4]: Push returned frame to downstream buffer
                # Per contract [A8]: AudioPump MUST NOT call write_pcm() directly
                # Push to downstream_buffer which feeds FFmpegSupervisor
                if frame is not None:
                    self.downstream_buffer.push_frame(frame)
                else:
                    # Per contract [S7.0D]: next_frame() should never return None
                    # But per contract [A12]: Handle gracefully if it does
                    logger.warning("AudioPump: encoder_manager.next_frame() returned None, using silence")
                    # Use silence frame as fallback
                    silence_frame = b'\x00' * SILENCE_FRAME_SIZE
                    self.downstream_buffer.push_frame(silence_frame)
                    
            except Exception as e:
                # Per contract [A12]: Log error and continue ticking
                logger.error(f"AudioPump next_frame error: {e}", exc_info=True)
                # Per contract [A12]: Replace with silence for this tick
                try:
                    silence_frame = b'\x00' * SILENCE_FRAME_SIZE
                    self.downstream_buffer.push_frame(silence_frame)
                except Exception as write_error:
                    logger.error(f"AudioPump push_frame error after next_frame error: {write_error}")
                # Per contract [A13]: Continue ticking on subsequent intervals
                # Sleep for remaining time in tick period
                tick_index += 1
                next_tick += FRAME_DURATION_SEC
                sleep_time = next_tick - time.monotonic()
                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    # Behind schedule - resync per contract [A10]
                    logger.warning("AudioPump behind schedule after error, resyncing")
                    next_tick = time.monotonic()
                continue

            tick_index += 1
            # Per contract [A4]: Use absolute clock timing to prevent cumulative drift
            next_tick += FRAME_DURATION_SEC
            sleep_time = next_tick - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # Per contract [A10]: Resync if behind schedule instead of accumulating delay
                logger.warning("AudioPump behind schedule, resyncing")
                next_tick = time.monotonic()  # resync
