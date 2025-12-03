"""
Event Queue for Appalachia Radio 3.1.

This module will contain queue structures for managing audio events.
AudioEvent is now defined in broadcast_core.audio_event.

Architecture 3.1 Reference:
- Section 5: Updated Playout Engine Flow
"""

# AudioEvent is imported from audio_event module
from broadcast_core.audio_event import AudioEvent

__all__ = ["AudioEvent"]
