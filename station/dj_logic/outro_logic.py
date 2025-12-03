"""
Outro Logic for Appalachia Radio 3.1.

Handles selection of outro MP3s for talk segments, including personality
outros, generic outros, and outro usage cooldowns.

Architecture 3.1 Reference:
- Section 2.5: Intros, Outros, Station IDs, and Talk Are Discrete MP3s
- Section 9: Intro/Outro/ID Decision Model
"""

import logging
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from broadcast_core.audio_event import AudioEvent

logger = logging.getLogger(__name__)

# Cooldown duration for outro reuse
OUTRO_COOLDOWN_MINUTES = 30


class OutroLogic:
    """
    Logic for selecting and managing song outros.
    
    Outros are discrete MP3 files chosen during the Prep Window when
    the DJ decides to talk after a song.
    
    Architecture 3.1 Reference: Section 9
    """
    
    def __init__(self, assets_root: Optional[Path] = None):
        """
        Initialize outro logic.
        
        Args:
            assets_root: Root directory for mock assets (default: ./mock_assets)
        """
        self.assets_root = assets_root or Path("mock_assets")
        self.outros_root = self.assets_root / "outros"
        
        # Cooldown tracking: path -> last used timestamp
        self.cooldowns: dict[str, datetime] = {}
        
        # Mock asset pools
        self.personality_outros: list[str] = []
        self.generic_outros: list[str] = []
        
        # Initialize mock asset paths
        self._initialize_mock_assets()
        
        logger.info(f"OutroLogic initialized with {len(self.generic_outros)} generic outros")
    
    def _initialize_mock_assets(self) -> None:
        """Initialize mock asset file paths."""
        # Personality outros (song-specific)
        self.personality_outros = [
            str(self.outros_root / "personality" / f"outro_{i:03d}.mp3")
            for i in range(1, 11)  # 10 personality outros
        ]
        
        # Generic outros (always available)
        self.generic_outros = [
            str(self.outros_root / "generic" / f"generic_outro_{i:03d}.mp3")
            for i in range(1, 21)  # 20 generic outros
        ]
    
    def _is_on_cooldown(self, outro_path: str) -> bool:
        """
        Check if an outro is on cooldown.
        
        Args:
            outro_path: Path to outro file
            
        Returns:
            True if outro is on cooldown (used recently)
        """
        if outro_path not in self.cooldowns:
            return False
        
        last_used = self.cooldowns[outro_path]
        cooldown_end = last_used + timedelta(minutes=OUTRO_COOLDOWN_MINUTES)
        return datetime.now() < cooldown_end
    
    def _get_available_outros(self, outro_list: list[str]) -> list[str]:
        """
        Get list of outros that are not on cooldown.
        
        Args:
            outro_list: List of outro paths
            
        Returns:
            List of available (not on cooldown) outro paths
        """
        return [outro for outro in outro_list if not self._is_on_cooldown(outro)]
    
    def select_outro(self, current_song: str, talk_frequency: Optional[dict] = None) -> Optional[AudioEvent]:
        """
        Select a concrete outro MP3 file for the current song.
        
        Called during Prep Window when DJ decides to talk. Must return a valid
        AudioEvent with an existing file path, or None if no outro should be used.
        
        Incorporates:
        - Talk frequency consideration (how long since last talk)
        - Cooldown checking
        - Fallback to generic assets
        
        Architecture 3.1 Reference: Section 4.3 (Step 3)
        
        Args:
            current_song: Filepath of the current song ending
            talk_frequency: Optional dict with talk frequency info:
                - "time_since_last_talk": timedelta or None
                - "talks_in_last_hour": int
                - "should_talk": bool (if False, return None)
        
        Returns:
            AudioEvent for the outro, or None if no outro
        """
        # If talk frequency indicates we shouldn't talk, return None
        if talk_frequency and not talk_frequency.get("should_talk", True):
            return None
        
        # Try personality outro first (if available)
        personality_outro = self._get_personality_outro(current_song)
        if personality_outro:
            logger.debug(f"[OUTRO] Selected personality outro: {personality_outro}")
            return AudioEvent(path=personality_outro, type="outro")
        
        # Fall back to generic outro
        generic_outro = self._get_generic_outro(talk_frequency)
        if generic_outro:
            logger.debug(f"[OUTRO] Selected generic outro: {generic_outro}")
            return AudioEvent(path=generic_outro, type="outro")
        
        # Last resort fallback
        fallback_outro = self._get_fallback_outro()
        if fallback_outro:
            logger.warning(f"[OUTRO] Using fallback outro: {fallback_outro}")
            return AudioEvent(path=fallback_outro, type="outro")
        
        logger.warning("[OUTRO] No outro available")
        return None
    
    def _get_personality_outro(self, song_path: str) -> Optional[str]:
        """
        Get a personality outro for a specific song.
        
        Args:
            song_path: Filepath of the song
            
        Returns:
            Path to personality outro, or None if not available
        """
        # Get available personality outros (not on cooldown)
        available = self._get_available_outros(self.personality_outros)
        
        if not available:
            return None
        
        # Simple selection: pick one based on song path (deterministic but varied)
        # Use hash of song path to consistently map to outro
        song_hash = hash(song_path) % len(available)
        selected = available[song_hash]
        
        return selected
    
    def _get_generic_outro(self, talk_frequency: Optional[dict] = None) -> Optional[str]:
        """
        Get a generic outro from the pool.
        
        Considers talk frequency - if talked recently, might select differently.
        
        Args:
            talk_frequency: Optional talk frequency context
            
        Returns:
            Path to generic outro, or None if pool empty
        """
        # Get available generic outros (not on cooldown)
        available = self._get_available_outros(self.generic_outros)
        
        if not available:
            # If all are on cooldown, use the oldest one
            if self.generic_outros:
                # Sort by last used time, pick oldest
                sorted_outros = sorted(
                    self.generic_outros,
                    key=lambda x: self.cooldowns.get(x, datetime.min)
                )
                return sorted_outros[0]
            return None
        
        # If talked recently (within last 10 minutes), avoid recently used outros
        if talk_frequency:
            time_since = talk_frequency.get("time_since_last_talk")
            if time_since and time_since < timedelta(minutes=10):
                # Prefer outros not used in last 5 minutes
                recent_cutoff = datetime.now() - timedelta(minutes=5)
                fresh = [
                    outro for outro in available
                    if outro not in self.cooldowns or self.cooldowns[outro] < recent_cutoff
                ]
                if fresh:
                    available = fresh
        
        # Random selection from available
        return random.choice(available)
    
    def _get_fallback_outro(self) -> Optional[str]:
        """
        Get a safe fallback generic outro (always available).
        
        Returns:
            Path to fallback outro, or None if no fallback exists
        """
        # Use first generic outro as fallback
        if self.generic_outros:
            return self.generic_outros[0]
        return None
    
    def record_outro_usage(self, outro_path: str) -> None:
        """
        Record that an outro was used (for cooldown tracking).
        
        Args:
            outro_path: Path to the outro that was used
        """
        self.cooldowns[outro_path] = datetime.now()
        logger.debug(f"[OUTRO] Recorded usage: {os.path.basename(outro_path)}")
