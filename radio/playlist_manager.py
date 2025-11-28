# playlist_manager.py
import logging
import os
import time
from datetime import datetime
from typing import List, Tuple
from .constants import (
    HISTORY_SIZE, IMMEDIATE_REPEAT_PENALTY, NEVER_PLAYED_BONUS,
    MAX_TIME_BONUS, RECENT_PLAY_WINDOW, RECENT_PLAY_BASE_PENALTY, RECENT_PLAY_DECAY
)

logger = logging.getLogger(__name__)

class PlaylistManager:
    """Manages playlist logic, play counts, and song selection probabilities."""
    
    def __init__(self) -> None:
        """Initialize the playlist manager."""
        self.history: List[Tuple[str, float, bool]] = []  # (song_name, timestamp, is_holiday)
        self.play_counts: dict[str, int] = {}  # Tracks how many times each song has been played
        self.holiday_play_counts: dict[str, int] = {}  # Separate tracking for holiday songs

    def _initialize_play_counts_for_path(self, path: str, is_holiday: bool) -> dict[str, int]:
        """
        Initialize play counts for a single directory.
        
        Args:
            path: Path to music directory
            is_holiday: Whether this is a holiday music directory
            
        Returns:
            Dictionary mapping filenames to play counts (all 0)
        """
        if not os.path.exists(path):
            logger.warning(f"{'Holiday' if is_holiday else 'Regular'} music path does not exist: {path}")
            return {}
        
        try:
            files = [f for f in os.listdir(path) if f.endswith('.mp3')]
            counts = {f: 0 for f in files}
            logger.info(f"Initialized {len(counts)} {'holiday' if is_holiday else 'regular'} songs")
            return counts
        except OSError as e:
            logger.error(f"Error reading {'holiday' if is_holiday else 'regular'} music directory {path}: {e}")
            return {}
    
    def initialize_play_counts(self, regular_path: str, holiday_path: str) -> None:
        """
        Initialize play count tracking for all songs.
        
        Args:
            regular_path: Path to regular music directory
            holiday_path: Path to holiday music directory
        """
        self.play_counts = self._initialize_play_counts_for_path(regular_path, is_holiday=False)
        self.holiday_play_counts = self._initialize_play_counts_for_path(holiday_path, is_holiday=True)

    def is_holiday_season(self) -> bool:
        """
        Check if current date is within holiday season (Nov 1 - Dec 31).
        
        Returns:
            True if within holiday season, False otherwise
        """
        current_date = datetime.now()
        if current_date.month == 11:
            return True
        if current_date.month == 12:
            return True
        return False

    def get_holiday_selection_probability(self) -> float:
        """
        Calculate the probability of selecting a holiday song based on date.
        
        Returns:
            Probability between 0.0 and 0.33 (0% to 33%)
            - Nov 1: 0.01 (1%)
            - Midpoint (Dec 12-13): ~0.17 (17%)
            - Dec 25-31: 0.33 (33%)
        """
        if not self.is_holiday_season():
            return 0.0
        
        current_date = datetime.now()
        
        # Calculate days from Nov 1
        # Nov 1 = day 0, Nov 30 = day 29, Dec 1 = day 30, Dec 25 = day 54
        if current_date.month == 11:
            days_from_nov1 = current_date.day - 1  # Nov 1 = 0, Nov 30 = 29
        elif current_date.month == 12:
            days_from_nov1 = 30 + (current_date.day - 1)  # Dec 1 = 30, Dec 25 = 54
        else:
            return 0.0
        
        # Total days from Nov 1 to Dec 25 = 55 days (Nov 1 to Dec 25 inclusive)
        # Actually: Nov has 30 days, so Nov 1 to Nov 30 = 30 days (days 0-29)
        # Dec 1 to Dec 25 = 25 days (days 30-54)
        # Total = 55 days, but day 0 to day 54 = 55 days total
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
            # Shouldn't reach here, but just in case
            return max_probability

    def calculate_probabilities(
        self, regular_files: List[str], holiday_files: List[str]
    ) -> Tuple[List[float], List[str], List[bool]]:
        """
        Calculate probabilities for both regular and holiday songs.
        
        Args:
            regular_files: List of regular song filenames
            holiday_files: List of holiday song filenames
            
        Returns:
            Tuple of (probabilities, all_files, is_holiday_list)
        """
        current_time = time.time()
        probabilities = []
        
        # Note: Holiday selection is now handled separately in play_random_mp3()
        # This method only calculates weights for the provided files
        all_files = [(f, False) for f in regular_files] + [(f, True) for f in holiday_files]
        
        for mp3_file, is_holiday in all_files:
            weight = 1.0
            play_counts = self.holiday_play_counts if is_holiday else self.play_counts
            
            # Queue-like system: Check if song was recently played
            # Find the most recent occurrence of this song in history
            most_recent_position = None
            last_played_time = None
            
            # Search history from most recent to oldest
            for idx in range(len(self.history) - 1, -1, -1):
                song, timestamp, h = self.history[idx]
                if song == mp3_file and h == is_holiday:
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
                    # Penalty decreases as position increases (more songs ago = less penalty)
                    # Formula: base_penalty + (1 - base_penalty) * (position / window)
                    # This creates a sliding scale where songs gradually recover
                    recovery = most_recent_position / RECENT_PLAY_WINDOW
                    penalty_factor = RECENT_PLAY_BASE_PENALTY + (1.0 - RECENT_PLAY_BASE_PENALTY) * recovery
                    penalty_factor = max(0.05, min(1.0, penalty_factor))  # Clamp between 5% and 100%
                    weight *= penalty_factor
                
                # Also apply time-based bonus for songs that haven't played in a while
                if last_played_time:
                    hours_since_played = (current_time - last_played_time) / 3600
                    if hours_since_played > 1:  # Only apply if more than 1 hour
                        time_factor = min(MAX_TIME_BONUS, (hours_since_played / 24) ** 0.5)
                        weight *= time_factor
            else:
                # Song never played - give it a bonus
                weight *= NEVER_PLAYED_BONUS

            # Play count balance - ensure all songs get fair play
            total_plays = sum(play_counts.values())
            if total_plays > 0:
                expected_plays = total_plays / len(play_counts)
                actual_plays = play_counts.get(mp3_file, 0)
                play_count_factor = (expected_plays + 1) / (actual_plays + 1)
                weight *= play_count_factor
            
            probabilities.append(weight)
        
        # Normalize probabilities
        total = sum(probabilities)
        if total > 0:
            probabilities = [p / total for p in probabilities]
        else:
            probabilities = [1.0 / len(all_files)] * len(all_files)
            
        return probabilities, [f for f, _ in all_files], [h for _, h in all_files]

    def update_history(self, mp3_file: str, is_holiday: bool) -> None:
        """
        Update play history and counts for a played song.
        
        Args:
            mp3_file: Name of the song file that was played
            is_holiday: Whether the song is a holiday song
        """
        current_time = time.time()
        self.history.append((mp3_file, current_time, is_holiday))
        if len(self.history) > HISTORY_SIZE:
            self.history.pop(0)
            
        if is_holiday:
            self.holiday_play_counts[mp3_file] = self.holiday_play_counts.get(mp3_file, 0) + 1
        else:
            self.play_counts[mp3_file] = self.play_counts.get(mp3_file, 0) + 1