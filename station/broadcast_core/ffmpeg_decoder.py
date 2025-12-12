import logging
import os
import subprocess
import numpy as np

logger = logging.getLogger(__name__)


class FFmpegDecoder:
    """
    Minimal real MP3 → PCM decoder using ffmpeg.
    - Outputs 16-bit signed little-endian stereo at 48 kHz
    - Yields numpy int16 frames of shape (N, 2)
    
    ARCHITECTURAL INVARIANT: This decoder has NO timing responsibility.
    It produces frames at natural decoder pacing (may burst or stall).
    Station pushes frames immediately as decoded - Tower owns all timing.
    """

    def __init__(self, path: str, frame_size: int = 1024):
        """
        Initialize FFmpeg decoder.
        
        Args:
            path: Path to audio file
            frame_size: Number of samples per frame (default: 1024)
        """
        self.path = path
        self.frame_size = frame_size
        
        # Launch ffmpeg to decode to raw s16le stereo 48k
        # Use preexec_fn=os.setsid to isolate FFmpeg from Ctrl-C (SIGINT) sent to parent
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
            preexec_fn=os.setsid,
        )

    def read_frames(self):
        """
        Generator yielding PCM frames as numpy int16 arrays shaped (N, 2).
        
        Each frame is exactly frame_size samples (1024 samples = 4096 bytes).
        
        ARCHITECTURAL INVARIANT: Yields frames at natural decoder pacing.
        No timing logic, no rate limiting, no synchronization.
        If decoder bursts → yields immediately. If decoder stalls → yields when ready.
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

    def kill(self, grace_period_seconds: float = 2.0) -> None:
        """
        Forcefully kill the FFmpeg process (PHASE 2 shutdown only).
        
        This method MUST be called during PHASE 2 (SHUTTING_DOWN) to ensure
        FFmpeg processes are terminated even when systemd uses KillMode=process.
        
        Process is in its own process group (via os.setsid), so we kill the
        entire process group to ensure no orphaned processes remain.
        
        Args:
            grace_period_seconds: Time to wait for clean exit after SIGTERM before SIGKILL
        
        This method is idempotent and safe to call multiple times.
        """
        if self.proc is None:
            return
        
        # Check if process is still running
        if self.proc.poll() is not None:
            # Process already exited
            logger.debug(f"[DECODER] FFmpeg process already exited (pid={self.proc.pid})")
            self.proc = None
            return
        
        try:
            # Get process group ID (negative PID sends signal to process group)
            pgid = os.getpgid(self.proc.pid)
            logger.info(f"[DECODER] FFmpeg SIGTERM sent (pid={self.proc.pid}, pgid={pgid})")
            
            # Send SIGTERM to process group
            os.killpg(pgid, 15)  # 15 = SIGTERM
            
            # Wait for clean exit
            try:
                self.proc.wait(timeout=grace_period_seconds)
                logger.info(f"[DECODER] FFmpeg exited cleanly (pid={self.proc.pid})")
                self.proc = None
                return
            except subprocess.TimeoutExpired:
                # Process didn't exit within grace period, force kill
                logger.warning(f"[DECODER] FFmpeg SIGKILL sent (timeout exceeded, pid={self.proc.pid}, pgid={pgid})")
                os.killpg(pgid, 9)  # 9 = SIGKILL
                try:
                    self.proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    logger.error(f"[DECODER] FFmpeg process group did not exit after SIGKILL (pid={self.proc.pid}, pgid={pgid})")
                except Exception:
                    pass
                self.proc = None
        except ProcessLookupError:
            # Process already exited (race condition)
            logger.debug(f"[DECODER] FFmpeg process already exited (pid={self.proc.pid})")
            self.proc = None
        except Exception as e:
            logger.error(f"[DECODER] Error killing FFmpeg process (pid={self.proc.pid}): {e}", exc_info=True)
            # Try fallback: kill just the process (not process group)
            try:
                if self.proc.poll() is None:
                    self.proc.kill()
                    self.proc.wait(timeout=1)
            except Exception:
                pass
            self.proc = None
    
    def close(self) -> None:
        """
        Clean up the ffmpeg process.
        
        Closes stdout and terminates/kills the process if still running.
        Safe to call multiple times.
        
        Note: For PHASE 2 shutdown, use kill() instead to ensure process group termination.
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


