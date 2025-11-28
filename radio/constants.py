"""Configuration constants for the radio player."""

import os
from typing import Final

# Directory paths (expands ~ to full home directory path)
REGULAR_MUSIC_PATH: Final[str] = os.path.expanduser('~/radio/songs')
HOLIDAY_MUSIC_PATH: Final[str] = os.path.expanduser('~/radio/holiday_songs')
DJ_PATH: Final[str] = os.path.expanduser('~/radio/julie')

# DJ file limits
MAX_INTRO_FILES: Final[int] = 5
MAX_OUTRO_FILES: Final[int] = 5

# Playlist management
HISTORY_SIZE: Final[int] = 48  # Number of recent songs to track
IMMEDIATE_REPEAT_PENALTY: Final[float] = 0.01  # Weight multiplier for the very last song (almost eliminated)
RECENT_PLAY_WINDOW: Final[int] = 20  # Number of recent songs to apply penalties to
RECENT_PLAY_BASE_PENALTY: Final[float] = 0.1  # Base penalty for songs in recent window
RECENT_PLAY_DECAY: Final[float] = 0.15  # How quickly penalty decreases (higher = faster recovery)
NEVER_PLAYED_BONUS: Final[float] = 3.0  # Weight multiplier for unplayed songs
MAX_TIME_BONUS: Final[float] = 2.0  # Maximum time-based weight bonus

# DJ intro/outro probability (dynamic - increases over time)
DJ_BASE_PROBABILITY: Final[float] = 0.2  # Base chance to play intro/outro (music-friendly)
DJ_MAX_PROBABILITY: Final[float] = 0.85  # Maximum chance after long silence
DJ_SONGS_BEFORE_INCREASE: Final[int] = 3  # Number of songs before probability starts increasing
DJ_MAX_SONGS_FOR_MAX_PROB: Final[int] = 8  # Songs without DJ talk to reach max probability

# Holiday season settings
HOLIDAY_BOOST: Final[float] = 1.5  # Weight multiplier for holiday songs during season (reduced from 3.0)