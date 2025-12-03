"""
Ticklers (Deferred DJ Tasks) for Appalachia Radio 3.1 - Phase 6.

Ticklers are deferred prep tasks that must be executed during THINK windows.
They allow the DJ to prepare assets in the background without blocking DO.

Architecture 3.1 Reference:
- Section 2.4: Ticklers (Deferred DJ Tasks)
"""

from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class Tickler(ABC):
    """
    A deferred prep task that must be executed during THINK.
    
    Ticklers are created during DO and executed during the next THINK window.
    This allows expensive work (like TTS generation) to happen without blocking
    the real-time audio pipeline.
    """
    
    @abstractmethod
    def run(self, dj_engine) -> None:
        """
        Perform the task using DJ state and cache.
        
        Args:
            dj_engine: DJEngine instance for accessing state and logging
        """
        pass
    
    @abstractmethod
    def __repr__(self) -> str:
        """Return string representation of the tickler."""
        pass


class GenerateIntroTickler(Tickler):
    """
    Tickler to generate an intro for a specific song.
    
    In Phase 8, this will call ElevenLabs to generate the intro.
    For now, it's a stub that logs the action.
    """
    
    def __init__(self, song_path: str):
        """
        Initialize intro generation tickler.
        
        Args:
            song_path: Path to the song that needs an intro
        """
        self.song_path = song_path
    
    def run(self, dj_engine) -> None:
        """
        Generate intro for the song.
        
        Future: call ElevenLabs, but for now just log.
        """
        logger.info(f"[Tickler] Would generate intro for {self.song_path}")
        # TODO Phase 8: Add file to cache if real generation existed
    
    def __repr__(self) -> str:
        return f"GenerateIntroTickler({self.song_path})"


class GenerateOutroTickler(Tickler):
    """
    Tickler to generate an outro for a specific song.
    
    In Phase 8, this will call ElevenLabs to generate the outro.
    For now, it's a stub that logs the action.
    """
    
    def __init__(self, song_path: str):
        """
        Initialize outro generation tickler.
        
        Args:
            song_path: Path to the song that needs an outro
        """
        self.song_path = song_path
    
    def run(self, dj_engine) -> None:
        """
        Generate outro for the song.
        
        Future: call ElevenLabs, but for now just log.
        """
        logger.info(f"[Tickler] Would generate outro for {self.song_path}")
        # TODO Phase 8: Add file to cache if real generation existed
    
    def __repr__(self) -> str:
        return f"GenerateOutroTickler({self.song_path})"


class RefillGenericIDTickler(Tickler):
    """
    Tickler to refill the generic ID asset pool.
    
    In Phase 8, this will generate new generic station IDs.
    For now, it's a stub that logs the action.
    """
    
    def run(self, dj_engine) -> None:
        """
        Refill generic ID assets.
        
        Future: generate new generic IDs via TTS or other means.
        """
        logger.info("[Tickler] Would refill generic ID assets")
        # TODO Phase 8: Generate and cache new generic IDs
    
    def __repr__(self) -> str:
        return "RefillGenericIDTickler()"
