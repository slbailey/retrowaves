from abc import ABC, abstractmethod
import numpy as np


class BaseSink(ABC):
    """
    Abstract base class for all output sinks.
    
    All sinks must implement write() and close() methods.
    """
    
    @abstractmethod
    def write(self, frame: np.ndarray) -> None:
        """
        Write a PCM frame to the output sink.
        
        Args:
            frame: numpy array containing PCM audio data
        """
        ...
    
    @abstractmethod
    def close(self) -> None:
        """
        Close the output sink and release resources.
        """
        ...

