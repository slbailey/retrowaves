"""
SourceMode enum for Retrowaves Tower.

Defines the available audio source modes.
"""

from enum import Enum


class SourceMode(str, Enum):
    """
    Audio source mode enumeration.
    
    Values are strings for JSON serialization.
    """
    TONE = "tone"
    SILENCE = "silence"
    FILE = "file"

