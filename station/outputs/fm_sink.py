"""
FM Sink for Appalachia Radio 3.1.

Outputs audio to FM transmitter via ALSA.

Architecture 3.1 Reference:
- Section 2.7: Frame-Based Audio Pipeline (FMSink → must never block)
"""

import logging
from typing import Iterator

from outputs.sink_base import SinkBase

logger = logging.getLogger(__name__)


class FMSink(SinkBase):
    """
    FM output sink via ALSA.
    
    Must never block the audio pipeline.
    Architecture 3.1 Reference: Section 2.7
    """
    
    def __init__(self, device: str = "default"):
        """
        Initialize FM sink.
        
        Args:
            device: ALSA device name (e.g., "default" or "hw:1,0")
        """
        self.device = device
        # TODO: Initialize ALSA output
    
    def write_frames(self, frames: Iterator[bytes]) -> None:
        """
        Write PCM frames to FM transmitter.
        
        Must never block.
        Architecture 3.1 Reference: Section 2.7
        
        Args:
            frames: Iterator of PCM frame data
        """
        # TODO: Implement non-blocking ALSA output
        raise NotImplementedError("TODO: Implement FM sink frame writing")
    
    def start(self) -> None:
        """Start the FM sink."""
        # TODO: Initialize ALSA connection
        raise NotImplementedError("TODO: Implement FM sink start")
    
    def stop(self) -> None:
        """Stop the FM sink gracefully."""
        # TODO: Close ALSA connection
        raise NotImplementedError("TODO: Implement FM sink stop")

