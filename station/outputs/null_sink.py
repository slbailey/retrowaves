import numpy as np
from .base_sink import BaseSink


class NullSink(BaseSink):
    """A sink that discards all audio. Useful for long-running tests."""

    def write(self, frame: np.ndarray) -> None:
        # Do nothing
        return

    def close(self) -> None:
        # Nothing to close
        return

