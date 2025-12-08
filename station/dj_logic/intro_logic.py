"""
Intro Logic for Appalachia Radio 3.1.

Handles selection of intro MP3s for songs, including personality intros,
generic intros, and intro usage cooldowns.

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

from station.broadcast_core.audio_event import AudioEvent

logger = logging.getLogger(__name__)

# Cooldown duration for intro reuse
INTRO_COOLDOWN_MINUTES = 30


class IntroLogic:
    """
    Logic for selecting and managing song intros.
    
    Intros are discrete MP3 files chosen during the Prep Window and
    executed during the Transition Window.
    
    Architecture 3.1 Reference: Section 9
    """
    
    def __init__(self, assets_root: Optional[Path] = None):
        """
        Initialize intro logic.
        
        Args:
            assets_root: Root directory for mock assets (default: ./mock_assets)
        """
        self.assets_root = assets_root or Path("mock_assets")
        self.intros_root = self.assets_root / "intros"
        
        # Cooldown tracking: path -> last used timestamp
        self.cooldowns: dict[str, datetime] = {}
        
        # Mock asset pools
        self.personality_intros: list[str] = []
        self.generic_intros: list[str] = []
        
        # Initialize mock asset paths
        self._initialize_mock_assets()
        
        logger.info(f"IntroLogic initialized with {len(self.generic_intros)} generic intros")
    
    def _initialize_mock_assets(self) -> None:
        """Initialize mock asset file paths."""
        # Personality intros (song-specific)
        self.personality_intros = [
            str(self.intros_root / "personality" / f"intro_{i:03d}.mp3") 
            for i in range(1, 11)  # 10 personality intros
        ]
        
        # Generic intros (always available)
        self.generic_intros = [
            str(self.intros_root / "generic" / f"generic_intro_{i:03d}.mp3")
            for i in range(1, 21)  # 20 generic intros
        ]
    
    def _is_on_cooldown(self, intro_path: str) -> bool:
        """
        Check if an intro is on cooldown.
        
        Args:
            intro_path: Path to intro file
            
        Returns:
            True if intro is on cooldown (used recently)
        """
        if intro_path not in self.cooldowns:
            return False
        
        last_used = self.cooldowns[intro_path]
        cooldown_end = last_used + timedelta(minutes=INTRO_COOLDOWN_MINUTES)
        return datetime.now() < cooldown_end
    
    def _get_available_intros(self, intro_list: list[str]) -> list[str]:
        """
        Get list of intros that are not on cooldown.
        
        Args:
            intro_list: List of intro paths
            
        Returns:
            List of available (not on cooldown) intro paths
        """
        return [intro for intro in intro_list if not self._is_on_cooldown(intro)]
    
    def select_intro(self, next_song: str) -> Optional[AudioEvent]:
        """
        Select a concrete intro MP3 file for the next song.
        
        Called during Prep Window. Must return a valid AudioEvent with
        an existing file path, or None if no intro should be used.
        
        Incorporates:
        - Talk frequency consideration (via break_context if provided)
        - Cooldown checking
        - Fallback to generic assets
        
        Architecture 3.1 Reference: Section 4.3 (Step 3)
        
        Args:
            next_song: Filepath of the next song
            
        Returns:
            AudioEvent for the intro, or None if no intro
        """
        # Try personality intro first (if available)
        personality_intro = self._get_personality_intro(next_song)
        if personality_intro:
            logger.debug(f"[INTRO] Selected personality intro: {personality_intro}")
            return AudioEvent(path=personality_intro, type="intro")
        
        # Fall back to generic intro
        generic_intro = self._get_generic_intro()
        if generic_intro:
            logger.debug(f"[INTRO] Selected generic intro: {generic_intro}")
            return AudioEvent(path=generic_intro, type="intro")
        
        # Last resort fallback
        fallback_intro = self._get_fallback_intro()
        if fallback_intro:
            logger.warning(f"[INTRO] Using fallback intro: {fallback_intro}")
            return AudioEvent(path=fallback_intro, type="intro")
        
        logger.warning("[INTRO] No intro available")
        return None
    
    def _get_personality_intro(self, song_path: str) -> Optional[str]:
        """
        Get a personality intro for a specific song.
        
        Args:
            song_path: Filepath of the song
            
        Returns:
            Path to personality intro, or None if not available
        """
        # For now, try to match based on song filename hash or simple heuristic
        # In production, this would use a database or mapping
        
        # Get available personality intros (not on cooldown)
        available = self._get_available_intros(self.personality_intros)
        
        if not available:
            return None
        
        # Simple selection: pick one based on song path (deterministic but varied)
        # Use hash of song path to consistently map to intro
        song_hash = hash(song_path) % len(available)
        selected = available[song_hash]
        
        return selected
    
    def _get_generic_intro(self) -> Optional[str]:
        """
        Get a generic intro from the pool.
        
        Returns:
            Path to generic intro, or None if pool empty
        """
        # Get available generic intros (not on cooldown)
        available = self._get_available_intros(self.generic_intros)
        
        if not available:
            # If all are on cooldown, use the oldest one
            if self.generic_intros:
                # Sort by last used time, pick oldest
                sorted_intros = sorted(
                    self.generic_intros,
                    key=lambda x: self.cooldowns.get(x, datetime.min)
                )
                return sorted_intros[0]
            return None
        
        # Random selection from available
        return random.choice(available)
    
    def _get_fallback_intro(self) -> Optional[str]:
        """
        Get a safe fallback generic intro (always available).
        
        Returns:
            Path to fallback intro, or None if no fallback exists
        """
        # Use first generic intro as fallback
        if self.generic_intros:
            return self.generic_intros[0]
        return None
    
    def record_intro_usage(self, intro_path: str) -> None:
        """
        Record that an intro was used (for cooldown tracking).
        
        Args:
            intro_path: Path to the intro that was used
        """
        self.cooldowns[intro_path] = datetime.now()
        logger.debug(f"[INTRO] Recorded usage: {os.path.basename(intro_path)}")
