import subprocess
import numpy as np


class FFmpegDecoder:
    """
    Minimal real MP3 → PCM decoder using ffmpeg.
    - Outputs 16-bit signed little-endian stereo at 48 kHz
    - Yields numpy int16 frames of shape (N, 2)
    """

    def __init__(self, path: str, frame_size: int = 1024):
        self.path = path
        self.frame_size = frame_size
        # Launch ffmpeg to decode to raw s16le stereo 48k
        self.proc = subprocess.Popen(
            [
                "ffmpeg",
                "-i", self.path,
                "-f", "s16le",
                "-ac", "2",
                "-ar", "48000",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=self.frame_size * 4,  # hint
        )

    def read_frames(self):
        """
        Generator yielding PCM frames as numpy int16 arrays shaped (N, 2).
        """
        assert self.proc.stdout is not None
        bytes_per_frame = self.frame_size * 2 * 2  # samples * 2 bytes * 2 channels

        while True:
            data = self.proc.stdout.read(bytes_per_frame)
            if not data:
                break
            # If partial last chunk, still yield what we got
            num_samples = len(data) // 4  # 2 bytes * 2 channels
            if num_samples == 0:
                break
            frame = np.frombuffer(data[: num_samples * 4], dtype=np.int16).reshape(-1, 2)
            yield frame

        self.proc.stdout.close()
        self.proc.wait()


