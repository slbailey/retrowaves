"""
File-based fallback audio source for Tower.

This version is fully contract-compliant and pop-free:

- All decoding happens at construction time
- Crossfade for seamless looping is performed ONCE at startup on the PCM buffer
- next_frame() is zero-latency: no I/O, no locks, no math, no allocations
- PCM conforms to Tower's canonical format: 48kHz, stereo, s16le, 1024-sample frames
"""

from __future__ import annotations

import logging
import os
import subprocess
import struct
from typing import List

logger = logging.getLogger(__name__)

# ===== PCM FORMAT CONSTANTS ===== #
SAMPLE_RATE = 48000
CHANNELS = 2
BYTES_PER_SAMPLE = 2  # s16le
FRAME_SIZE_SAMPLES = 1024
FRAME_SIZE_BYTES = FRAME_SIZE_SAMPLES * CHANNELS * BYTES_PER_SAMPLE

# ===== MAX MEMORY SAFETY ===== #
DEFAULT_MAX_DURATION_SEC = 600  # 10 minutes max buffer

# ===== CROSSFADE SETTINGS ===== #
# 2048 samples ≈ 42.6 ms @ 48kHz — excellent for seamless looping
DEFAULT_CROSSFADE_SAMPLES = 2048


class FileSource:
    """
    Predecoded, in-memory, seamless-loop PCM source for fallback audio.

    Contract alignment:
    - FP2.2: next_frame() MUST be zero-latency → it simply returns a frame from memory
    - FP3.1: file fallback → decoded PCM, canonical 4096-byte frames
    - FP6.2: seamless looping → startup PCM crossfade eliminates pops/clicks
    """

    def __init__(
        self,
        file_path: str,
        max_duration_sec: int = DEFAULT_MAX_DURATION_SEC,
        crossfade_samples: int = DEFAULT_CROSSFADE_SAMPLES,
    ) -> None:

        if not file_path:
            raise ValueError("File path cannot be empty")

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Fallback file not found: {file_path}")

        if not os.access(file_path, os.R_OK):
            raise PermissionError(f"Fallback file not readable: {file_path}")

        self.file_path = os.path.abspath(file_path)
        self._frames: List[bytes] = []
        self._index = 0

        max_bytes = (
            max_duration_sec
            * SAMPLE_RATE
            * CHANNELS
            * BYTES_PER_SAMPLE
        )

        logger.info(
            "Decoding fallback file '%s' (max %s sec, %d bytes)…",
            self.file_path,
            max_duration_sec,
            max_bytes,
        )

        raw_pcm = self._decode_to_pcm(max_bytes=max_bytes)

        logger.info("Applying seamless-loop crossfade (%d samples)…", crossfade_samples)
        pcm_xfaded = self._apply_crossfade(raw_pcm, crossfade_samples)

        logger.info("Slicing PCM into 4096-byte canonical frames…")
        self._frames = self._slice_into_frames(pcm_xfaded)

        if not self._frames:
            raise RuntimeError(
                f"FileSource error: no complete PCM frames decoded from '{self.file_path}'"
            )

        dur_sec = len(self._frames) * FRAME_SIZE_SAMPLES / float(SAMPLE_RATE)
        logger.info(
            "FileSource ready: %d frames (%.2f sec) from '%s'",
            len(self._frames),
            dur_sec,
            self.file_path,
        )

    # ================================================================== #
    #                      FFmpeg Decode at Startup                      #
    # ================================================================== #

    def _decode_to_pcm(self, max_bytes: int) -> bytearray:
        """
        Decode the entire file to raw PCM (48kHz, stereo, s16le) using ffmpeg.
        This runs ONCE at construction time and may block — contract allows this.
        """
        proc = subprocess.Popen(
            [
                "ffmpeg",
                "-i",
                self.file_path,
                "-acodec",
                "pcm_s16le",
                "-f",
                "s16le",
                "-ac",
                str(CHANNELS),
                "-ar",
                str(SAMPLE_RATE),
                "-loglevel",
                "error",
                "-nostdin",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert proc.stdout

        chunks = []
        total = 0

        try:
            while True:
                chunk = proc.stdout.read(64 * 1024)
                if not chunk:
                    break

                if total + len(chunk) > max_bytes:
                    need = max_bytes - total
                    if need > 0:
                        chunks.append(chunk[:need])
                        total += need
                    break

                chunks.append(chunk)
                total += len(chunk)

        finally:
            stdout, stderr = proc.communicate()

        if proc.returncode not in (0, None):
            err = stderr.decode("utf-8", "ignore") if stderr else ""
            raise RuntimeError(f"ffmpeg decode failed: {err}")

        pcm = b"".join(chunks)
        usable = len(pcm) - (len(pcm) % FRAME_SIZE_BYTES)

        return bytearray(pcm[:usable])

    # ================================================================== #
    #            SEAMLESS LOOPING VIA STARTUP PCM CROSSFADE             #
    # ================================================================== #

    def _apply_crossfade(self, pcm: bytearray, crossfade_samples: int) -> bytearray:
        """
        Apply a PCM-level crossfade between the end and beginning of the audio
        to ensure perfectly seamless looping.

        - Done only once at startup
        - Stereo-aware (interleaved samples)
        - Removes the overlapped tail region
        """
        if crossfade_samples <= 0:
            return pcm

        samples_total = len(pcm) // (CHANNELS * BYTES_PER_SAMPLE)

        if crossfade_samples * 2 > samples_total:
            logger.warning(
                "PCM too short (%d samples) for %d-sample crossfade; skipping.",
                samples_total,
                crossfade_samples,
            )
            return pcm

        # Unpack PCM → Python ints (signed 16-bit)
        samples = list(
            struct.unpack(f"<{samples_total * CHANNELS}h", pcm)
        )

        fade_len = crossfade_samples

        for i in range(fade_len):
            w_in = i / fade_len       # fade-in weight for head
            w_out = 1.0 - w_in        # fade-out weight for tail

            for ch in range(CHANNELS):
                # Tail index
                tail_idx = (samples_total - fade_len + i) * CHANNELS + ch
                # Head index
                head_idx = i * CHANNELS + ch

                tail = samples[tail_idx]
                head = samples[head_idx]

                blended = int(tail * w_out + head * w_in)

                # Replace head with blended value
                samples[head_idx] = blended

        # Remove the faded-out tail samples
        samples = samples[: (samples_total - fade_len) * CHANNELS]

        # Pack samples → PCM bytes
        return bytearray(
            struct.pack(f"<{len(samples)}h", *samples)
        )

    # ================================================================== #
    #             PCM → Canonical 4096-Byte Frame Slicing               #
    # ================================================================== #

    def _slice_into_frames(self, pcm: bytearray) -> List[bytes]:
        frames = []
        for i in range(0, len(pcm), FRAME_SIZE_BYTES):
            chunk = pcm[i : i + FRAME_SIZE_BYTES]
            if len(chunk) == FRAME_SIZE_BYTES:
                frames.append(bytes(chunk))
        return frames

    # ================================================================== #
    #                     ZERO-LATENCY PUBLIC INTERFACE                  #
    # ================================================================== #

    def next_frame(self) -> bytes:
        """
        Return the next PCM frame with **no processing**.
        Fully FP2.2 compliant: O(1), no work, no I/O, no locks.
        """
        frame = self._frames[self._index]
        self._index += 1
        if self._index >= len(self._frames):
            self._index = 0
        return frame

    def is_available(self) -> bool:
        return bool(self._frames)

    def close(self) -> None:
        pass   # nothing to clean up
