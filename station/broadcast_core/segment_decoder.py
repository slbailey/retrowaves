"""
Background segment decoder — FFmpeg on a worker thread, frames pushed to PCMOutputPipeline.
"""

import logging
import threading
from typing import Callable, Optional

import numpy as np

from station.broadcast_core.ffmpeg_decoder import FFmpegDecoder
from station.broadcast_core.pcm_output_pipeline import PCMOutputPipeline
from station.mixer.mixer import Mixer

logger = logging.getLogger(__name__)


class SegmentDecoder:
    """Decode one audio file on a worker thread and push mixed frames to the output pipeline."""

    def __init__(
        self,
        path: str,
        gain: float,
        mixer: Mixer,
        pipeline: PCMOutputPipeline,
        on_decoder: Optional[Callable[[FFmpegDecoder], None]] = None,
        frame_size: int = 1024,
    ):
        self._path = path
        self._gain = gain
        self._mixer = mixer
        self._pipeline = pipeline
        self._on_decoder = on_decoder
        self._frame_size = frame_size
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._exhausted = False
        self._error: Optional[BaseException] = None
        self._frames_pushed = 0
        self._decoder: Optional[FFmpegDecoder] = None

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    @property
    def error(self) -> Optional[BaseException]:
        return self._error

    @property
    def frames_pushed(self) -> int:
        return self._frames_pushed

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="segment-decode", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._decoder is not None:
            try:
                self._decoder.kill(grace_period_seconds=0.5)
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        decoder: Optional[FFmpegDecoder] = None
        try:
            decoder = FFmpegDecoder(self._path, frame_size=self._frame_size)
            self._decoder = decoder
            if self._on_decoder:
                self._on_decoder(decoder)

            for frame in decoder.read_frames():
                if self._stop.is_set():
                    break
                processed = self._mixer.mix(frame, gain=self._gain)
                if not self._pipeline.push(processed, block=True):
                    break
                self._frames_pushed += 1

            self._exhausted = True
            logger.debug(
                f"[SEG-DECODE] Finished {self._path} "
                f"(frames_pushed={self._frames_pushed}, queue_depth={self._pipeline.depth()})"
            )
        except Exception as e:
            self._error = e
            self._exhausted = True
            logger.error(f"[SEG-DECODE] Error decoding {self._path}: {e}", exc_info=True)
        finally:
            self._decoder = None
