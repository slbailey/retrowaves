"""
Station ID Logic for Appalachia Radio 3.1.

Handles selection of station ID MP3s, including legal ID requirements,
ID usage cooldowns, and ID placement rules.

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

# Cooldown duration for ID reuse
ID_COOLDOWN_MINUTES = 15
LEGAL_ID_COOLDOWN_HOURS = 1


class IDLogic:
    """
    Logic for selecting and managing station IDs.
    
    Station IDs are discrete MP3 files chosen during the Prep Window
    and placed between elements during the Transition Window.
    
    Architecture 3.1 Reference: Section 9
    """
    
    def __init__(self, assets_root: Optional[Path] = None):
        """
        Initialize ID logic.
        
        Args:
            assets_root: Root directory for mock assets (default: ./mock_assets)
        """
        self.assets_root = assets_root or Path("mock_assets")
        self.ids_root = self.assets_root / "station_ids"
        
        # Cooldown tracking: path -> last used timestamp
        self.cooldowns: dict[str, datetime] = {}
        
        # Legal ID tracking
        self.last_legal_id_time: Optional[datetime] = None
        
        # Mock asset pools
        self.legal_ids: list[str] = []
        self.generic_ids: list[str] = []
        
        # Initialize mock asset paths
        self._initialize_mock_assets()
        
        logger.info(f"IDLogic initialized with {len(self.legal_ids)} legal IDs, "
                   f"{len(self.generic_ids)} generic IDs")
    
    def _initialize_mock_assets(self) -> None:
        """Initialize mock asset file paths."""
        # Legal IDs (for top-of-hour requirements)
        self.legal_ids = [
            str(self.ids_root / "legal" / f"legal_id_{i:03d}.mp3")
            for i in range(1, 6)  # 5 legal IDs
        ]
        
        # Generic IDs (for general use)
        self.generic_ids = [
            str(self.ids_root / "generic" / f"generic_id_{i:03d}.mp3")
            for i in range(1, 16)  # 15 generic IDs
        ]
    
    def _is_on_cooldown(self, id_path: str) -> bool:
        """
        Check if an ID is on cooldown.
        
        Args:
            id_path: Path to ID file
            
        Returns:
            True if ID is on cooldown (used recently)
        """
        if id_path not in self.cooldowns:
            return False
        
        last_used = self.cooldowns[id_path]
        
        # Legal IDs have longer cooldown
        is_legal = any(legal in id_path for legal in self.legal_ids)
        cooldown_minutes = LEGAL_ID_COOLDOWN_HOURS * 60 if is_legal else ID_COOLDOWN_MINUTES
        
        cooldown_end = last_used + timedelta(minutes=cooldown_minutes)
        return datetime.now() < cooldown_end
    
    def _get_available_ids(self, id_list: list[str]) -> list[str]:
        """
        Get list of IDs that are not on cooldown.
        
        Args:
            id_list: List of ID paths
            
        Returns:
            List of available (not on cooldown) ID paths
        """
        return [id_path for id_path in id_list if not self._is_on_cooldown(id_path)]
    
    def needs_legal_id(self, break_context: Optional[dict] = None) -> bool:
        """
        Check if a legal ID is required at this time.
        
        Architecture 3.1 Reference: Section 9 (Rules Examples)
        
        Legal IDs are required:
        - At top of hour (or within tolerance window)
        - At least once per hour
        
        Args:
            break_context: Optional context dict with:
                - "current_time": datetime
                - "is_top_of_hour": bool
                - "minutes_since_last_legal_id": int or None
        
        Returns:
            True if legal ID is required
        """
        now = datetime.now()
        
        # Check if at top of hour (within 5 minutes)
        is_top_of_hour = break_context.get("is_top_of_hour", False) if break_context else False
        if not is_top_of_hour:
            # Check current time
            if now.minute <= 5:  # Within first 5 minutes of hour
                is_top_of_hour = True
        
        if is_top_of_hour:
            # Check if we've already played a legal ID this hour
            if self.last_legal_id_time:
                time_since = now - self.last_legal_id_time
                if time_since < timedelta(hours=1):
                    logger.debug(f"[ID] Legal ID not needed: played {time_since.total_seconds()/60:.0f} minutes ago")
                    return False
            logger.debug("[ID] Legal ID needed: top of hour")
            return True
        
        # Check if enough time since last legal ID
        if self.last_legal_id_time:
            time_since = now - self.last_legal_id_time
            if time_since >= timedelta(hours=1):
                logger.debug(f"[ID] Legal ID needed: {time_since.total_seconds()/3600:.1f} hours since last")
                return True
        else:
            # Never played a legal ID
            logger.debug("[ID] Legal ID needed: never played")
            return True
        
        return False
    
    def select_station_ids(self, break_context: Optional[dict] = None) -> list[AudioEvent]:
        """
        Select concrete station ID MP3 files for the next break.
        
        Called during Prep Window. Returns list of AudioEvents with
        existing file paths.
        
        Incorporates:
        - Legal ID requirements (top-of-hour, hourly requirement)
        - Cooldown checking
        - Fallback to generic assets
        
        Architecture 3.1 Reference: Section 4.3 (Step 3)
        
        Args:
            break_context: Optional context dict with:
                - "current_time": datetime
                - "is_top_of_hour": bool
                - "time_since_last_talk": timedelta
                - "talks_in_last_hour": int
        
        Returns:
            List of AudioEvents for station IDs (0-N)
        """
        selected_ids: list[AudioEvent] = []
        
        # Check if legal ID is needed
        needs_legal = self.needs_legal_id(break_context)
        
        if needs_legal:
            legal_id = self._get_legal_id()
            if legal_id:
                selected_ids.append(AudioEvent(path=legal_id, type="id"))
                logger.debug(f"[ID] Selected legal ID: {legal_id}")
        
        # Optionally add a generic ID (if we haven't used one recently)
        # Only if we're not already using a legal ID or if we want both
        if not needs_legal or random.random() < 0.3:  # 30% chance to add generic too
            generic_id = self._get_generic_id(break_context)
            if generic_id:
                selected_ids.append(AudioEvent(path=generic_id, type="id"))
                logger.debug(f"[ID] Selected generic ID: {generic_id}")
        
        return selected_ids
    
    def _get_legal_id(self) -> Optional[str]:
        """
        Get a legal station ID.
        
        Returns:
            Path to legal ID, or None if not available
        """
        # Get available legal IDs (not on cooldown)
        available = self._get_available_ids(self.legal_ids)
        
        if not available:
            # If all are on cooldown, use the oldest one (legal IDs are required)
            if self.legal_ids:
                sorted_ids = sorted(
                    self.legal_ids,
                    key=lambda x: self.cooldowns.get(x, datetime.min)
                )
                selected = sorted_ids[0]
                logger.warning(f"[ID] All legal IDs on cooldown, using oldest: {selected}")
                return selected
            return None
        
        # Random selection from available
        return random.choice(available)
    
    def _get_generic_id(self, break_context: Optional[dict] = None) -> Optional[str]:
        """
        Get a generic station ID from the pool.
        
        Args:
            break_context: Optional break context for frequency consideration
        
        Returns:
            Path to generic ID, or None if pool empty
        """
        # Get available generic IDs (not on cooldown)
        available = self._get_available_ids(self.generic_ids)
        
        if not available:
            # If all are on cooldown, use the oldest one
            if self.generic_ids:
                sorted_ids = sorted(
                    self.generic_ids,
                    key=lambda x: self.cooldowns.get(x, datetime.min)
                )
                return sorted_ids[0]
            return None
        
        # Consider talk frequency - if talked recently, maybe avoid IDs that were used then
        if break_context:
            time_since = break_context.get("time_since_last_talk")
            if time_since and time_since < timedelta(minutes=10):
                # Prefer IDs not used in last 5 minutes
                recent_cutoff = datetime.now() - timedelta(minutes=5)
                fresh = [
                    id_path for id_path in available
                    if id_path not in self.cooldowns or self.cooldowns[id_path] < recent_cutoff
                ]
                if fresh:
                    available = fresh
        
        # Random selection from available
        return random.choice(available)
    
    def record_id_usage(self, id_path: str, is_legal: bool = False) -> None:
        """
        Record that a station ID was used (for cooldown tracking).
        
        Args:
            id_path: Path to the ID that was used
            is_legal: Whether this was a legal ID
        """
        self.cooldowns[id_path] = datetime.now()
        
        if is_legal:
            self.last_legal_id_time = datetime.now()
            logger.debug(f"[ID] Recorded legal ID usage: {os.path.basename(id_path)}")
        else:
            logger.debug(f"[ID] Recorded generic ID usage: {os.path.basename(id_path)}")
