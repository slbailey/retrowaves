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
        
        Each frame is exactly frame_size samples (1024 samples = 4096 bytes).
        """
        assert self.proc.stdout is not None
        bytes_per_frame = self.frame_size * 2 * 2  # samples * 2 bytes * 2 channels
        
        # Buffer for partial frames
        buffer = bytearray()

        try:
            while True:
                # Read data (may return more or less than bytes_per_frame)
                data = self.proc.stdout.read(bytes_per_frame * 2)  # Read up to 2 frames to handle buffering
                if not data:
                    # EOF - check if we have a partial frame in buffer
                    if len(buffer) >= bytes_per_frame:
                        # Extract complete frame from buffer
                        frame_data = bytes(buffer[:bytes_per_frame])
                        buffer = buffer[bytes_per_frame:]
                        frame = np.frombuffer(frame_data, dtype=np.int16).reshape(-1, 2)
                        yield frame
                    break
                
                # Add to buffer
                buffer.extend(data)
                
                # Extract complete frames from buffer
                while len(buffer) >= bytes_per_frame:
                    # Extract exactly one frame
                    frame_data = bytes(buffer[:bytes_per_frame])
                    buffer = buffer[bytes_per_frame:]
                    frame = np.frombuffer(frame_data, dtype=np.int16).reshape(-1, 2)
                    yield frame
                
                # If buffer has partial frame, keep it for next iteration
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


