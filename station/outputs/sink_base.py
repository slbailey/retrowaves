"""
Base Output Sink for Appalachia Radio 3.1.

Abstract base class for all output sinks (FM, YouTube, etc.).

Architecture 3.1 Reference:
- Section 2.7: Frame-Based Audio Pipeline (FMSink, YouTubeSink)
"""

import logging
from abc import ABC, abstractmethod
from typing import Iterator

logger = logging.getLogger(__name__)


class SinkBase(ABC):
    """
    Abstract base class for output sinks.
    
    All sinks must implement non-blocking frame writing.
    Architecture 3.1 Reference: Section 2.7
    """
    
    @abstractmethod
    def write_frames(self, frames: Iterator[bytes]) -> None:
        """
        Write PCM frames to output sink.
        
        Must never block the audio pipeline.
        
        Architecture 3.1 Reference: Section 2.7
        
        Args:
            frames: Iterator of PCM frame data
        """
        raise NotImplementedError("Subclasses must implement write_frames")
    
    @abstractmethod
    def start(self) -> None:
        """Start the output sink."""
        raise NotImplementedError("Subclasses must implement start")
    
    @abstractmethod
    def stop(self) -> None:
        """Stop the output sink gracefully."""
        raise NotImplementedError("Subclasses must implement stop")

