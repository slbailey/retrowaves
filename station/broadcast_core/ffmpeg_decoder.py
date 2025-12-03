import logging
import subprocess
import numpy as np

logger = logging.getLogger(__name__)


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

        try:
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
        finally:
            # Always cleanup, even if generator is stopped early
            self.close()

    def close(self) -> None:
        """
        Clean up the ffmpeg process.
        
        Closes stdout and terminates/kills the process if still running.
        Safe to call multiple times.
        """
        if self.proc is None:
            return
        
        try:
            # Close stdout first
            if self.proc.stdout:
                self.proc.stdout.close()
        except Exception:
            pass
        
        # Terminate the process
        if self.proc.poll() is None:  # Process is still running
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Force kill if terminate didn't work
                try:
                    logger.warning(f"[DECODER] FFmpeg process didn't terminate, killing: {self.path}")
                    self.proc.kill()
                    self.proc.wait(timeout=1)
                except Exception:
                    pass
            except Exception:
                pass
        
        self.proc = None


