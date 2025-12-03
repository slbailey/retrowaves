"""
Music Rotation Logic for Appalachia Radio 3.1.

Handles song selection, rotation weighting, history tracking, and
holiday-aware music selection.

Uses weighted selection algorithm based on legacy playlist manager:
- Recent play penalty (queue-like system)
- Time-based bonus (old songs get priority)
- Never-played bonus
- Play count balance
- Holiday season weighting

Architecture 3.1 Reference:
- Section 2.1: The DJ Is the Brain (selects songs)
- Section 4.3: DJ Prep Window Behavior (chooses next song)
"""

import json
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Constants matching legacy implementation
HISTORY_SIZE: int = 48
IMMEDIATE_REPEAT_PENALTY: float = 0.01
RECENT_PLAY_WINDOW: int = 20
RECENT_PLAY_BASE_PENALTY: float = 0.1
RECENT_PLAY_DECAY: float = 0.15
NEVER_PLAYED_BONUS: float = 3.0
MAX_TIME_BONUS: float = 2.0


class RotationManager:
    """
    Manages music rotation and song selection.
    
    Provides weighted song selection based on age, holidays, and
    rotation history using sophisticated probability calculations.
    
    Architecture 3.1 Reference: Section 4.3 (Step 3)
    """
    
    def __init__(self, regular_tracks: Optional[List[str]] = None, holiday_tracks: Optional[List[str]] = None, state_file: Optional[str] = None):
        """
        Initialize rotation manager.
        
        Args:
            regular_tracks: List of regular song filepaths (optional, can be set later)
            holiday_tracks: List of holiday song filepaths (optional, can be set later)
            state_file: Optional path to JSON file for saving/loading state
        """
        # Store track lists for reference (used when selecting from all available tracks)
        self._regular_tracks: List[str] = list(regular_tracks or [])
        self._holiday_tracks: List[str] = list(holiday_tracks or [])
        
        # History tracking: (filepath, timestamp, is_holiday) tuples
        self.history: List[Tuple[str, float, bool]] = []
        
        # Play counts: track filepath -> play count
        self.play_counts: dict[str, int] = {}  # Regular songs
        self.holiday_play_counts: dict[str, int] = {}  # Holiday songs
        
        self.state_file: Optional[str] = state_file
        
        # Load saved state if available
        if self.state_file:
            self.load_state()
        
        logger.info(f"RotationManager initialized with {len(self._regular_tracks)} regular and {len(self._holiday_tracks)} holiday tracks")
    
    def is_holiday_season(self) -> bool:
        """
        Check if current date is within holiday season.
        
        The holiday season is defined as November 1 through December 31.
        
        Returns:
            True if current date is in November or December, False otherwise.
        """
        current_date = datetime.now()
        return current_date.month in (11, 12)
    
    def get_holiday_selection_probability(self) -> float:
        """
        Calculate the probability of selecting a holiday song based on date.
        
        Implements a date-based probability curve that increases throughout
        the holiday season:
        - November 1: 1% chance
        - Linear progression to December 25: 33% chance
        - December 26-31: 33% chance (stays at maximum)
        - Outside holiday season: 0% chance
        
        Returns:
            Probability between 0.0 and 0.33 (0% to 33%).
        """
        if not self.is_holiday_season():
            return 0.0
        
        current_date = datetime.now()
        
        # Calculate days from Nov 1
        if current_date.month == 11:
            days_from_nov1 = current_date.day - 1  # Nov 1 = 0, Nov 30 = 29
        elif current_date.month == 12:
            days_from_nov1 = 30 + (current_date.day - 1)  # Dec 1 = 30, Dec 25 = 54
        else:
            return 0.0
        
        total_days_to_dec25 = 54  # Day 0 (Nov 1) to day 54 (Dec 25)
        max_probability = 0.33  # Maximum 33% chance
        
        if current_date.month == 12 and current_date.day > 25:
            # Dec 26-31: 33% chance
            return max_probability
        elif days_from_nov1 <= total_days_to_dec25:
            # Nov 1 to Dec 25: Linear progression from 1% to 33%
            progress = days_from_nov1 / total_days_to_dec25
            return 0.01 + progress * (max_probability - 0.01)  # Linear from 1% to 33%
        else:
            return max_probability
    
    def _is_holiday_track(self, filepath: str) -> bool:
        """
        Determine if a track is a holiday track based on path.
        
        Args:
            filepath: Full path to track
            
        Returns:
            True if track appears to be holiday music
        """
        filepath_lower = filepath.lower()
        # Check if path contains "holiday" (case-insensitive)
        return 'holiday' in filepath_lower
    
    def _calculate_weights(
        self, regular_tracks: List[str], holiday_tracks: List[str]
    ) -> Tuple[List[float], List[str], List[bool]]:
        """
        Calculate weighted probabilities for song selection.
        
        Implements sophisticated weighting algorithm that considers:
        1. Recent Play Penalty: Songs played recently get reduced weight
        2. Time-Based Bonus: Songs not played in a while get bonus weight
        3. Never-Played Bonus: Songs never played get bonus multiplier
        4. Play Count Balance: Songs with fewer plays get higher weight
        
        Args:
            regular_tracks: List of regular song filepaths
            holiday_tracks: List of holiday song filepaths
            
        Returns:
            Tuple of:
            - weights: List of float weights (not normalized)
            - all_tracks: List of all song filepaths (regular + holiday)
            - is_holiday_list: List of booleans indicating holiday status
        """
        current_time = time.time()
        weights = []
        
        all_tracks = [(f, False) for f in regular_tracks] + [(f, True) for f in holiday_tracks]
        
        for track_path, is_holiday in all_tracks:
            weight = 1.0
            play_counts = self.holiday_play_counts if is_holiday else self.play_counts
            
            # Queue-like system: Check if song was recently played
            most_recent_position = None
            last_played_time = None
            
            # Search history from most recent to oldest
            for idx in range(len(self.history) - 1, -1, -1):
                stored_path, timestamp, h = self.history[idx]
                if stored_path == track_path and h == is_holiday:
                    most_recent_position = len(self.history) - 1 - idx  # 0 = most recent
                    last_played_time = timestamp
                    break
            
            if most_recent_position is not None:
                # Song was played recently - apply queue penalty
                if most_recent_position == 0:
                    # Very last song - almost eliminate it
                    weight *= IMMEDIATE_REPEAT_PENALTY
                elif most_recent_position < RECENT_PLAY_WINDOW:
                    # In recent play window - apply decreasing penalty
                    recovery = most_recent_position / RECENT_PLAY_WINDOW
                    penalty_factor = RECENT_PLAY_BASE_PENALTY + (1.0 - RECENT_PLAY_BASE_PENALTY) * recovery
                    penalty_factor = max(0.05, min(1.0, penalty_factor))  # Clamp between 5% and 100%
                    weight *= penalty_factor
                
                # Time-based bonus for songs not played in a while (age weighting)
                if last_played_time:
                    hours_since_played = (current_time - last_played_time) / 3600
                    if hours_since_played > 1:
                        # Older songs get bonus (square root growth, capped)
                        time_factor = min(MAX_TIME_BONUS, (hours_since_played / 24) ** 0.5)
                        weight *= time_factor
            else:
                # Song never played - give it a bonus
                weight *= NEVER_PLAYED_BONUS
            
            # Play count balance - ensure all songs get fair play
            total_plays = sum(play_counts.values())
            if total_plays > 0 and len(play_counts) > 0:
                expected_plays = total_plays / len(play_counts)
                actual_plays = play_counts.get(track_path, 0)
                play_count_factor = (expected_plays + 1) / (actual_plays + 1)
                weight *= play_count_factor
            
            weights.append(weight)
        
        return weights, [t for t, _ in all_tracks], [h for _, h in all_tracks]
    
    def select_next_song(self, available_tracks: Optional[List[str]] = None) -> str:
        """
        Select the next song from available tracks using weighted probabilities.
        
        Handles holiday season detection and probability calculation.
        Uses age weighting, history tracking, and play count balance.
        
        Architecture 3.1 Reference: Section 4.3 (Step 3)
        
        Args:
            available_tracks: Optional list of full filepaths to available MP3 files.
                            If None, uses all tracks from constructor (regular + holiday).
            
        Returns:
            Full filepath to selected song
            
        Raises:
            ValueError: If no tracks available
        """
        # If no tracks provided, use all tracks from constructor
        if available_tracks is None:
            available_tracks = self._regular_tracks + self._holiday_tracks
        
        if not available_tracks:
            raise ValueError("No tracks available for selection")
        
        # Separate regular and holiday tracks
        regular_tracks = []
        holiday_tracks = []
        
        for track in available_tracks:
            if self._is_holiday_track(track):
                holiday_tracks.append(track)
            else:
                regular_tracks.append(track)
        
        # Check holiday season and calculate holiday probability
        holiday_prob = 0.0
        if self.is_holiday_season():
            holiday_prob = self.get_holiday_selection_probability()
        
        # Decide if we should select from holiday files
        use_holiday = False
        if holiday_tracks and random.random() < holiday_prob:
            use_holiday = True
        
        # Select from appropriate pool
        if use_holiday:
            candidate_tracks = holiday_tracks
        else:
            candidate_tracks = regular_tracks
        
        # If no candidates in selected pool, fall back to other pool
        if not candidate_tracks:
            candidate_tracks = holiday_tracks if not use_holiday else regular_tracks
        
        # Calculate weights for all tracks (including both pools for proper weighting)
        weights, all_tracks, is_holiday_list = self._calculate_weights(
            regular_tracks=regular_tracks,
            holiday_tracks=holiday_tracks
        )
        
        # Normalize weights to probabilities
        total_weight = sum(weights)
        if total_weight > 0:
            probabilities = [w / total_weight for w in weights]
        else:
            probabilities = [1.0 / len(all_tracks)] * len(all_tracks) if all_tracks else []
        
        # Select using weighted random
        if not all_tracks:
            # Fallback: random selection
            return random.choice(candidate_tracks)
        
        selected_index = random.choices(range(len(all_tracks)), weights=probabilities)[0]
        selected_track = all_tracks[selected_index]
        
        logger.debug(f"[ROTATION] Selected: {os.path.basename(selected_track)} "
                    f"(holiday={is_holiday_list[selected_index]}, weight={weights[selected_index]:.3f})")
        
        return selected_track
    
    def record_song_played(self, song_path: str) -> None:
        """
        Record that a song was played.
        
        Updates history, play counts, and maintains history size limit.
        
        Args:
            song_path: Full filepath to the song that was played
        """
        current_time = time.time()
        is_holiday = self._is_holiday_track(song_path)
        
        # Add to history
        self.history.append((song_path, current_time, is_holiday))
        if len(self.history) > HISTORY_SIZE:
            self.history.pop(0)
        
        # Update play counts
        if is_holiday:
            self.holiday_play_counts[song_path] = self.holiday_play_counts.get(song_path, 0) + 1
        else:
            self.play_counts[song_path] = self.play_counts.get(song_path, 0) + 1
        
        logger.debug(f"[ROTATION] Recorded play: {os.path.basename(song_path)} "
                    f"(holiday={is_holiday}, total plays={self.play_counts.get(song_path, self.holiday_play_counts.get(song_path, 0))})")
        
        # Auto-save state after each update
        if self.state_file:
            self.save_state()
    
    def get_last_played_songs(self, count: int = 10) -> List[str]:
        """
        Get list of recently played song filepaths.
        
        Args:
            count: Number of recent songs to return
            
        Returns:
            List of song filepaths (most recent first)
        """
        # Return most recent songs from history
        recent = self.history[-count:] if len(self.history) > count else self.history
        # Reverse to get most recent first
        return [path for path, _, _ in reversed(recent)]
    
    def save_state(self) -> None:
        """
        Save rotation state (history and play counts) to JSON file.
        
        Preserves weighted playlist state across restarts to prevent
        immediate repeats after graceful restart.
        """
        if not self.state_file:
            return
        
        try:
            state = {
                "history": self.history,
                "play_counts": self.play_counts,
                "holiday_play_counts": self.holiday_play_counts,
            }
            
            # Write to temp file first, then rename (atomic operation)
            temp_file = self.state_file + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(state, f, indent=2)
            
            # Atomic rename
            os.replace(temp_file, self.state_file)
            
            logger.debug(f"[ROTATION] Saved state to {self.state_file}")
        except Exception as e:
            logger.warning(f"[ROTATION] Failed to save state: {e}")
    
    def load_state(self) -> bool:
        """
        Load rotation state (history and play counts) from JSON file.
        
        Returns:
            True if state was loaded successfully, False otherwise
        """
        if not self.state_file or not os.path.exists(self.state_file):
            return False
        
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            
            # Restore state
            self.history = [
                (item[0], float(item[1]), bool(item[2]))
                for item in state.get("history", [])
            ]
            self.play_counts = state.get("play_counts", {})
            self.holiday_play_counts = state.get("holiday_play_counts", {})
            
            logger.info(f"[ROTATION] Loaded state: {len(self.history)} history entries, "
                       f"{len(self.play_counts)} regular songs, {len(self.holiday_play_counts)} holiday songs")
            return True
        except Exception as e:
            logger.warning(f"[ROTATION] Failed to load state: {e}")
            return False
