"""
DJ Intent Model for Appalachia Radio 3.1.

This module defines the DJIntent dataclass and related structures that
represent the DJ's pre-decided plan for the next break.

Architecture 3.1 Reference:
- Section 4.2: DJ Intent Structure
"""

from dataclasses import dataclass
from typing import Optional, List

from broadcast_core.audio_event import AudioEvent


@dataclass
class DJIntent:
    """
    Represents everything the DJ plans to do on the next break,
    fully resolved to concrete audio files.
    
    Built during the Prep Window (THINK) and executed during the
    Transition Window (DO).
    
    Architecture 3.1 Reference: Section 4.2
    
    Attributes:
        next_song: Required next song AudioEvent
        outro: Optional outro AudioEvent for talk segments
        station_ids: Optional list of station ID AudioEvents (0-N)
        intro: Optional intro AudioEvent for the next song
        has_legal_id: True if any station_ids are legal IDs (decided in THINK)
    """
    next_song: AudioEvent                     # required
    outro: Optional[AudioEvent] = None        # optional
    station_ids: Optional[List[AudioEvent]] = None  # optional, 0–N IDs
    intro: Optional[AudioEvent] = None        # optional
    has_legal_id: bool = False                # metadata: True if any ID is legal (decided in THINK)
