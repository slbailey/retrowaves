import subprocess
import numpy as np
from .base_sink import BaseSink


class FFMPEGSink(BaseSink):
    """
    FFmpeg-based encoder sink.
    
    Encodes PCM frames to AAC/MP3 and writes to a file or stream URL.
    """

    def __init__(self, target: str, sample_rate: int = 48000, channels: int = 2):
        """
        Initialize FFmpeg sink.
        
        Args:
            target: File path or stream URL (e.g., icecast)
            sample_rate: Audio sample rate (default: 48000)
            channels: Number of audio channels (default: 2)
        """
        self.target = target
        self.sample_rate = sample_rate
        self.channels = channels
        self.proc = subprocess.Popen(
            [
                "ffmpeg",
                "-f", "s16le",
                "-ac", str(channels),
                "-ar", str(sample_rate),
                "-i", "-",
                "-c:a", "aac",
                "-b:a", "128k",
                "-f", "adts",   # or 'mp3' or appropriate container
                target
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )

    def write(self, frame: np.ndarray) -> None:
        """Write PCM frame to ffmpeg stdin."""
        if self.proc and self.proc.stdin:
            self.proc.stdin.write(frame.tobytes())

    def close(self) -> None:
        """Close ffmpeg subprocess."""
        if self.proc and self.proc.stdin:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        if self.proc:
            self.proc.terminate()
            self.proc = None

