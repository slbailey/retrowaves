#!/usr/bin/env python3
"""
PCM to MP3 validation harness for Tower.

This tool validates PCM format correctness and FFmpeg flags by streaming
Tower-format PCM frames to FFmpeg and verifying MP3 output.

Per contract [S26] in docs/contracts/FFMPEG_SUPERVISOR_CONTRACT.md.

This tool is purely diagnostic and MUST NOT be imported or used by Tower runtime.
"""

from __future__ import annotations

import argparse
import math
import subprocess
import struct
import sys
import threading
import time
from typing import Optional


# Tower PCM format constants (duplicated from tower.fallback.generator)
SAMPLE_RATE = 48000  # Hz
CHANNELS = 2  # Stereo
FRAME_SIZE_SAMPLES = 1152  # Samples per frame (MP3 frame size)
BYTES_PER_SAMPLE = 2  # s16le = 2 bytes per sample
FRAME_SIZE_BYTES = FRAME_SIZE_SAMPLES * CHANNELS * BYTES_PER_SAMPLE  # 4608 bytes

# Tone generation constants
TONE_FREQUENCY = 440.0  # Hz (A4 note)
PHASE_INCREMENT = 2.0 * math.pi * TONE_FREQUENCY / SAMPLE_RATE  # Radians per sample
AMPLITUDE = int(32767 * 0.8)  # 80% of max amplitude to avoid clipping

# FFmpeg command (duplicated from tower.encoder.ffmpeg_supervisor.DEFAULT_FFMPEG_CMD)
# Per contract [S26.2], [S26.5]: Use exact same audio pipeline as supervisor, including -frame_size 1152
FFMPEG_CMD = [
    "ffmpeg",
    "-hide_banner",
    "-nostdin",
    "-loglevel", "debug",  # Use debug for diagnostic tool
    "-f", "s16le",
    "-ar", "48000",
    "-ac", "2",
    "-i", "pipe:0",
    "-c:a", "libmp3lame",
    "-b:a", "128k",
    "-frame_size", "1152",  # Per contract [S26.5]: Required for raw PCM encoding
    "-f", "mp3",
    "-fflags", "+nobuffer",
    "-flush_packets", "1",
    "-write_xing", "0",
    "pipe:1",
]

# Timeout configuration per contract [S26.3]
DEFAULT_TIMEOUT_MS = 1000  # 1 second default timeout
MIN_MP3_BYTES = 100  # Minimum bytes to consider success


class PCMGenerator:
    """Generates Tower-format PCM frames."""
    
    def __init__(self, mode: str):
        """
        Initialize PCM generator.
        
        Args:
            mode: "silence" or "tone"
        """
        self.mode = mode
        self._phase: float = 0.0  # Phase accumulator for tone generation
    
    def get_frame(self) -> bytes:
        """
        Generate one PCM frame.
        
        Returns:
            bytes: PCM frame (4608 bytes for 1152 samples × 2 channels × 2 bytes)
        """
        if self.mode == "silence":
            return self._generate_silence_frame()
        elif self.mode == "tone":
            return self._generate_tone_frame()
        else:
            raise ValueError(f"Unknown mode: {self.mode}")
    
    def _generate_silence_frame(self) -> bytes:
        """Generate one frame of silence (zeros)."""
        return b'\x00' * FRAME_SIZE_BYTES
    
    def _generate_tone_frame(self) -> bytes:
        """Generate one frame of 440Hz sine tone."""
        frame_data = bytearray(FRAME_SIZE_BYTES)
        
        for i in range(FRAME_SIZE_SAMPLES):
            # Calculate sample value from current phase
            sample_value = int(AMPLITUDE * math.sin(self._phase))
            
            # Pack as s16le (signed 16-bit little-endian)
            sample_bytes = struct.pack('<h', sample_value)  # '<h' = little-endian signed short
            
            # Write to left channel
            offset = i * CHANNELS * BYTES_PER_SAMPLE
            frame_data[offset:offset + BYTES_PER_SAMPLE] = sample_bytes
            
            # Write to right channel (same value for stereo)
            frame_data[offset + BYTES_PER_SAMPLE:offset + BYTES_PER_SAMPLE * 2] = sample_bytes
            
            # Advance phase accumulator
            self._phase += PHASE_INCREMENT
            
            # Wrap phase to prevent overflow
            if self._phase >= 2.0 * math.pi:
                self._phase -= 2.0 * math.pi
        
        return bytes(frame_data)


class FFmpegValidator:
    """Validates FFmpeg encoding with Tower-format PCM input."""
    
    def __init__(self, generator: PCMGenerator, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        """
        Initialize FFmpeg validator.
        
        Args:
            generator: PCMGenerator instance
            timeout_ms: Timeout in milliseconds for MP3 output
        """
        self.generator = generator
        self.timeout_ms = timeout_ms
        self.timeout_sec = timeout_ms / 1000.0
        
        # Output tracking
        self.mp3_bytes_received = 0
        self.mp3_bytes_lock = threading.Lock()
        self.first_byte_time: Optional[float] = None
        
        # PCM input tracking
        self.pcm_bytes_sent = 0
        self.pcm_bytes_lock = threading.Lock()
        
        # Process tracking
        self.process: Optional[subprocess.Popen] = None
        self.stderr_lines: list[str] = []
        self.stderr_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        
        # Probe phase detection
        self.in_probe_phase = False
        self.probe_phase_lock = threading.Lock()
    
    def run(self) -> int:
        """
        Run validation test.
        
        Returns:
            int: Exit code (0 for success, non-zero for failure)
        """
        try:
            # Spawn FFmpeg process per contract [S26.2]
            self.process = subprocess.Popen(
                FFMPEG_CMD,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            
            if self.process is None:
                print("Startup error: Failed to spawn FFmpeg process", file=sys.stderr)
                return 1
            
            # Start stderr reader thread
            stderr_thread = threading.Thread(
                target=self._read_stderr,
                daemon=True,
                name="StderrReader"
            )
            stderr_thread.start()
            
            # Start stdout reader thread
            stdout_thread = threading.Thread(
                target=self._read_stdout,
                daemon=True,
                name="StdoutReader"
            )
            stdout_thread.start()
            
            # Start PCM writer thread
            writer_thread = threading.Thread(
                target=self._write_pcm,
                daemon=True,
                name="PCMWriter"
            )
            writer_thread.start()
            
            # Start status logging thread (every 250ms)
            status_thread = threading.Thread(
                target=self._log_status,
                daemon=True,
                name="StatusLogger"
            )
            status_thread.start()
            
            # Monitor for timeout or process exit
            start_time = time.monotonic()
            deadline = start_time + self.timeout_sec
            
            while time.monotonic() < deadline:
                # Check if process exited
                if self.process.poll() is not None:
                    exit_code = self.process.returncode
                    if exit_code != 0:
                        with self.stderr_lock:
                            stderr_text = '\n'.join(self.stderr_lines)
                        if stderr_text:
                            print(f"FFmpeg exited with code {exit_code}\n{stderr_text}", file=sys.stderr)
                        else:
                            print(f"FFmpeg exited with code {exit_code} (no frames produced)", file=sys.stderr)
                        return exit_code
                    # Process exited with code 0, but check if we got MP3 data
                    break
                
                # Check if we received enough MP3 data
                with self.mp3_bytes_lock:
                    if self.mp3_bytes_received >= MIN_MP3_BYTES:
                        elapsed_ms = (time.monotonic() - start_time) * 1000.0
                        print(f"Success: Received {self.mp3_bytes_received} MP3 bytes within {elapsed_ms:.0f}ms")
                        return 0
                
                time.sleep(0.01)  # 10ms polling interval
            
            # Timeout or process exited - check final state
            if self.process.poll() is not None:
                exit_code = self.process.returncode
                with self.mp3_bytes_lock:
                    bytes_received = self.mp3_bytes_received
                if bytes_received < MIN_MP3_BYTES:
                    print(f"FFmpeg exited with code {exit_code} (only {bytes_received} bytes produced, need {MIN_MP3_BYTES})", file=sys.stderr)
                    return exit_code if exit_code != 0 else 1
                else:
                    print(f"Success: Received {bytes_received} MP3 bytes before process exit")
                    return 0
            else:
                # Timeout
                with self.mp3_bytes_lock:
                    bytes_received = self.mp3_bytes_received
                if bytes_received < MIN_MP3_BYTES:
                    print(f"Timeout: no MP3 output within {self.timeout_ms}ms (received {bytes_received} bytes)", file=sys.stderr)
                    return 1
                else:
                    print(f"Success: Received {bytes_received} MP3 bytes within timeout")
                    return 0
        
        except Exception as e:
            print(f"Startup error: {e}", file=sys.stderr)
            return 1
        finally:
            self.shutdown_event.set()
            if self.process:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
                except Exception:
                    pass
    
    def _write_pcm(self) -> None:
        """Continuously write PCM frames to FFmpeg stdin."""
        try:
            if self.process is None or self.process.stdin is None:
                return
            
            frame_interval = FRAME_SIZE_SAMPLES / SAMPLE_RATE  # ~0.024s
            next_frame_time = time.monotonic()
            
            while not self.shutdown_event.is_set():
                if self.process.poll() is not None:
                    break
                
                # Generate and write frame
                frame = self.generator.get_frame()
                try:
                    self.process.stdin.write(frame)
                    self.process.stdin.flush()
                    # Track PCM bytes sent
                    with self.pcm_bytes_lock:
                        self.pcm_bytes_sent += len(frame)
                except BrokenPipeError:
                    # FFmpeg closed stdin (process ended)
                    break
                
                # Sleep until next frame time (maintain proper frame rate)
                next_frame_time += frame_interval
                sleep_time = next_frame_time - time.monotonic()
                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    # We're behind schedule, continue immediately
                    next_frame_time = time.monotonic()
        
        except Exception as e:
            print(f"PCM write error: {e}", file=sys.stderr)
    
    def _read_stdout(self) -> None:
        """Continuously read MP3 bytes from FFmpeg stdout."""
        try:
            if self.process is None or self.process.stdout is None:
                return
            
            while not self.shutdown_event.is_set():
                if self.process.poll() is not None:
                    # Try to read remaining data
                    try:
                        data = self.process.stdout.read(4096)
                        if data:
                            with self.mp3_bytes_lock:
                                self.mp3_bytes_received += len(data)
                                if self.first_byte_time is None:
                                    self.first_byte_time = time.monotonic()
                        else:
                            break
                    except Exception:
                        break
                else:
                    # Process still running, read available data
                    try:
                        data = self.process.stdout.read(4096)
                        if not data:
                            # EOF
                            break
                        with self.mp3_bytes_lock:
                            self.mp3_bytes_received += len(data)
                            if self.first_byte_time is None:
                                self.first_byte_time = time.monotonic()
                    except Exception:
                        break
        
        except Exception as e:
            print(f"Stdout read error: {e}", file=sys.stderr)
    
    def _read_stderr(self) -> None:
        """Continuously read and print stderr lines per contract [S26.2]."""
        try:
            if self.process is None or self.process.stderr is None:
                return
            
            while not self.shutdown_event.is_set():
                if self.process.poll() is not None:
                    # Try to read remaining stderr
                    try:
                        line = self.process.stderr.readline()
                        if line:
                            decoded = line.decode(errors='ignore').rstrip()
                            print(f"[FFMPEG] {decoded}")
                            with self.stderr_lock:
                                self.stderr_lines.append(decoded)
                            # Detect probe phase per requirement
                            if "Before avformat_find_stream_info()" in decoded:
                                with self.probe_phase_lock:
                                    self.in_probe_phase = True
                        else:
                            break
                    except Exception:
                        break
                else:
                    # Process still running, read available lines
                    try:
                        line = self.process.stderr.readline()
                        if not line:
                            # EOF
                            break
                        decoded = line.decode(errors='ignore').rstrip()
                        if decoded:  # Only print non-empty lines
                            print(f"[FFMPEG] {decoded}")
                            with self.stderr_lock:
                                self.stderr_lines.append(decoded)
                            # Detect probe phase per requirement
                            if "Before avformat_find_stream_info()" in decoded:
                                with self.probe_phase_lock:
                                    self.in_probe_phase = True
                    except Exception:
                        break
        
        except Exception as e:
            print(f"Stderr read error: {e}", file=sys.stderr)
    
    def _log_status(self) -> None:
        """Log status every 250ms showing PCM sent, MP3 received, and probe phase."""
        while not self.shutdown_event.is_set():
            if self.process is None:
                time.sleep(0.25)
                continue
            
            # Check if process is running
            is_running = self.process.poll() is None
            
            # Get current counts
            with self.pcm_bytes_lock:
                pcm_sent = self.pcm_bytes_sent
            with self.mp3_bytes_lock:
                mp3_received = self.mp3_bytes_received
            with self.probe_phase_lock:
                in_probe = self.in_probe_phase
            
            # Build status message per requirement
            # Format: "STATUS: ffmpeg running, PCM sent=X bytes, MP3 received=Y bytes"
            status_parts = [
                "ffmpeg running" if is_running else "ffmpeg stopped",
                f"PCM sent={pcm_sent} bytes",
                f"MP3 received={mp3_received} bytes"
            ]
            
            if in_probe:
                status_parts.append("PROBE-PHASE")
            
            print(f"STATUS: {', '.join(status_parts)}")
            
            # Sleep for 250ms
            time.sleep(0.25)


def main() -> int:
    """Main entry point per contract [S26.1]."""
    parser = argparse.ArgumentParser(
        description="PCM to MP3 validation harness for Tower (per contract [S26])"
    )
    
    # Per contract [S26.1]: Support --silence and --tone modes
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--silence",
        action="store_const",
        const="silence",
        dest="mode",
        help="Generate silence frames (all zeros)"
    )
    mode_group.add_argument(
        "--tone",
        action="store_const",
        const="tone",
        dest="mode",
        help="Generate 440Hz sine tone frames"
    )
    # Future: --file mode (not implemented yet)
    # mode_group.add_argument(
    #     "--file",
    #     type=str,
    #     dest="file_path",
    #     help="Read PCM or WAV file and feed as Tower-format frames (future enhancement)"
    # )
    
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help=f"Timeout in milliseconds for MP3 output (default: {DEFAULT_TIMEOUT_MS}ms)"
    )
    
    args = parser.parse_args()
    
    # Create PCM generator
    generator = PCMGenerator(args.mode)
    
    # Create and run validator
    validator = FFmpegValidator(generator, timeout_ms=args.timeout_ms)
    exit_code = validator.run()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
