import wave
import numpy as np
from .base_sink import BaseSink


class FileSink(BaseSink):
    """
    Simple WAV writer sink for PCM frames.
    
    Debug-only sink for inspecting audio output.
    """

    def __init__(self, path: str, sample_rate: int = 48000, channels: int = 2):
        self._wave = wave.open(path, "wb")
        self._wave.setnchannels(channels)
        self._wave.setsampwidth(2)  # int16
        self._wave.setframerate(sample_rate)

    def write(self, frame: np.ndarray) -> None:
        self._wave.writeframes(frame.tobytes())

    def close(self) -> None:
        self._wave.close()


