"""
Tower encoder subsystem.

This package provides the encoder management components for Tower:
- EncoderManager: Manages FFmpeg process lifecycle
- EncoderOutputDrainThread: Drains encoder stdout and packetizes frames
"""

from tower.encoder.encoder_manager import EncoderManager, EncoderState
from tower.encoder.drain_thread import EncoderOutputDrainThread

__all__ = [
    "EncoderManager",
    "EncoderState",
    "EncoderOutputDrainThread",
]

