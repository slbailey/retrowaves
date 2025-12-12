"""
Audio Event Model for Appalachia Radio 3.1.

Defines AudioEvent dataclass for audio segments.

Architecture 3.1 Reference:
- Section 6: Audio Event Model
"""

from dataclasses import dataclass, field
from typing import Literal, Optional, Dict, Any
import uuid


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
        metadata: Optional MP3 metadata (title, artist, duration) extracted during THINK phase
        is_terminal: True if this is a terminal segment (e.g., shutdown announcement) during draining
        intent_id: UUID of the DJIntent that created this AudioEvent (for atomic execution tracking)
    """
    path: str
    type: Literal["song", "intro", "outro", "talk", "id", "announcement"]
    gain: float = 1.0
    metadata: Optional[Dict[str, Any]] = field(default=None)
    is_terminal: bool = False
    intent_id: Optional[uuid.UUID] = field(default=None)  # UUID of the DJIntent that created this event

