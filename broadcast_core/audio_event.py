"""
Audio Event Model for Appalachia Radio 3.1.

Defines AudioEvent dataclass for audio segments.

Architecture 3.1 Reference:
- Section 6: Audio Event Model
"""

from dataclasses import dataclass
from typing import Literal


@dataclass
class AudioEvent:
    """
    Represents a single audio segment for playout.
    
    All audio elements (songs, intros, outros, station IDs, talk)
    are represented as discrete AudioEvents with concrete file paths.
    
    Architecture 3.1 Reference: Section 6
    
    Attributes:
        path: Path to the MP3 file
        type: Type of audio segment
        gain: Gain multiplier for audio level (default 1.0)
    """
    path: str
    type: Literal["song", "intro", "outro", "talk", "id"]
    gain: float = 1.0

