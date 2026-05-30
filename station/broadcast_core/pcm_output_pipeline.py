"""
Broadcast-grade continuous PCM output.

A dedicated pump thread sends exactly one frame every ~21.333ms to Tower.
Tower AudioPump is the sole playback clock — this pump must never burst.
Producers push decoded frames into a queue; when empty, silence is sent
at the same cadence so Tower never sees a PCM gap.
"""

import logging
import threading
import time
from collections import deque
from typing import Optional

import numpy as np

from station.outputs.base_sink import BaseSink

logger = logging.getLogger(__name__)

try:
    import logging.handlers
    _pcm_handler = logging.handlers.WatchedFileHandler('/var/log/retrowaves/station.log', mode='a')
    _pcm_handler.setLevel(logging.DEBUG)
    _pcm_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
    _original_emit = _pcm_handler.emit
    def _safe_emit(record):
        try:
            _original_emit(record)
        except (IOError, OSError):
            pass
    _pcm_handler.emit = _safe_emit
    if not any(
        isinstance(h, logging.handlers.WatchedFileHandler)
        and getattr(h, 'baseFilename', None) == '/var/log/retrowaves/station.log'
        for h in logger.handlers
    ):
        logger.addHandler(_pcm_handler)
    logger.propagate = False
except Exception:
    pass

FRAME_DURATION_SEC = 1024.0 / 48000.0
DEFAULT_QUEUE_CAPACITY = 100  # ~2.1 s at 48 kHz / 1024 samples


class PCMOutputPipeline:
    """Fixed-cadence PCM sender with a producer/consumer frame queue."""

    def __init__(self, sink: BaseSink, capacity: int = DEFAULT_QUEUE_CAPACITY):
        self._sink = sink
        self._capacity = max(8, capacity)
        self._queue: deque = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._silence = np.zeros((1024, 2), dtype=np.int16)
        self._frames_sent = 0
        self._program_frames_sent = 0
        self._starve_count = 0
        self._dropped_push = 0
        self._next_tick = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._next_tick = time.monotonic()
        self._thread = threading.Thread(target=self._pump_loop, name="pcm-output-pump", daemon=True)
        self._thread.start()
        logger.info(
            f"[PCM-PUMP] Started (cadence={FRAME_DURATION_SEC*1000:.3f}ms, "
            f"queue_capacity={self._capacity})"
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def depth(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def frames_sent(self) -> int:
        return self._frames_sent

    def push(self, frame: np.ndarray, block: bool = True, timeout: float = 30.0) -> bool:
        """Enqueue a mixed PCM frame. Blocks until space is available unless block=False."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if len(self._queue) < self._capacity:
                    self._queue.append(frame)
                    return True
                if not block:
                    self._dropped_push += 1
                    return False
            if time.monotonic() >= deadline:
                self._dropped_push += 1
                logger.warning("[PCM-PUMP] Queue full — dropped producer frame")
                return False
            if self._stop.is_set():
                return False
            time.sleep(0.001)

    def _pump_loop(self) -> None:
        write_frame = getattr(self._sink, "write_paced", self._sink.write)
        starve_log_next = 0

        while not self._stop.is_set():
            wait = self._next_tick - time.monotonic()
            if wait > 0:
                if self._stop.wait(wait):
                    break

            self._next_tick += FRAME_DURATION_SEC

            frame = None
            with self._lock:
                if self._queue:
                    frame = self._queue.popleft()

            if frame is None:
                frame = self._silence
                self._starve_count += 1
                if self._starve_count >= starve_log_next:
                    if starve_log_next == 0:
                        starve_log_next = 50
                        logger.warning(
                            f"[PCM-PUMP] Queue empty — sending silence "
                            f"(starve_count={self._starve_count}, depth=0)"
                        )
                    else:
                        starve_log_next += 500
                        logger.debug(
                            f"[PCM-PUMP] Queue empty — sending silence "
                            f"(starve_count={self._starve_count}, depth=0)"
                        )
            else:
                self._starve_count = 0
                starve_log_next = 0
                self._program_frames_sent += 1

            try:
                write_frame(frame)
                self._frames_sent += 1
            except Exception as e:
                logger.error(f"[PCM-PUMP] Sink write failed: {e}", exc_info=True)
