import logging
import os
import random
import signal
import sys
import time
from typing import List, Optional, Tuple
from .audio_player import AudioPlayer
from .playlist_manager import PlaylistManager
from .dj_manager import DJManager
from .file_manager import FileManager
from .constants import DJ_BASE_PROBABILITY, DJ_MAX_PROBABILITY, DJ_SONGS_BEFORE_INCREASE, DJ_MAX_SONGS_FOR_MAX_PROB

# Logging is configured in main.py
logger = logging.getLogger(__name__)

class MusicPlayer:
    """Main music player that orchestrates audio playback with smart playlist management."""
    
    def __init__(
        self, 
        regular_music_path: str, 
        holiday_music_path: str, 
        dj_path: str
    ) -> None:
        """
        Initialize the music player.
        
        Args:
            regular_music_path: Path to regular music directory
            holiday_music_path: Path to holiday music directory
            dj_path: Path to DJ intro/outro files directory
        """
        self.regular_music_path = regular_music_path
        self.holiday_music_path = holiday_music_path
        self.dj_path = dj_path
        self.audio_player = AudioPlayer()
        self.playlist_manager = PlaylistManager()
        self.dj_manager = DJManager(dj_path)  # Pass path to constructor
        self.file_manager = FileManager()
        
        # Track DJ talk timing for dynamic probability
        self.songs_since_last_dj_talk = 0
        
        # Validate paths exist
        self._validate_paths()
        
        self.playlist_manager.initialize_play_counts(regular_music_path, holiday_music_path)
        logger.info("MusicPlayer initialized")
    
    def _validate_paths(self) -> None:
        """Validate that all required paths exist."""
        if not os.path.exists(self.regular_music_path):
            logger.warning(f"Regular music path does not exist: {self.regular_music_path}")
        if not os.path.exists(self.holiday_music_path):
            logger.warning(f"Holiday music path does not exist: {self.holiday_music_path}")
        if not os.path.exists(self.dj_path):
            logger.warning(f"DJ path does not exist: {self.dj_path}")
    
    def _calculate_dj_probability(self) -> float:
        """
        Calculate dynamic DJ talk probability based on time since last talk.
        Probability increases the longer it's been since the DJ last talked.
        
        Returns:
            Probability value between DJ_BASE_PROBABILITY and DJ_MAX_PROBABILITY
        """
        if self.songs_since_last_dj_talk < DJ_SONGS_BEFORE_INCREASE:
            # Use base probability for first few songs (music-friendly)
            return DJ_BASE_PROBABILITY
        
        # Calculate how much to increase probability
        songs_over_base = self.songs_since_last_dj_talk - DJ_SONGS_BEFORE_INCREASE
        max_increase_songs = DJ_MAX_SONGS_FOR_MAX_PROB - DJ_SONGS_BEFORE_INCREASE
        
        # Linear increase from base to max
        if songs_over_base >= max_increase_songs:
            return DJ_MAX_PROBABILITY
        
        increase_factor = songs_over_base / max_increase_songs
        probability = DJ_BASE_PROBABILITY + (DJ_MAX_PROBABILITY - DJ_BASE_PROBABILITY) * increase_factor
        
        return min(probability, DJ_MAX_PROBABILITY)

    def _get_song_files(self) -> tuple[List[str], List[str]]:
        """
        Get MP3 files from both regular and holiday directories.
        
        Returns:
            Tuple of (regular_files, holiday_files)
        """
        regular_files = self.file_manager.get_mp3_files(self.regular_music_path)
        holiday_files = self.file_manager.get_mp3_files(self.holiday_music_path)
        return regular_files, holiday_files
    
    def _select_song(self, regular_files: List[str], holiday_files: List[str]) -> tuple[str, bool]:
        """
        Select a song based on holiday probability and weighted selection.
        
        Args:
            regular_files: List of regular song filenames
            holiday_files: List of holiday song filenames
            
        Returns:
            Tuple of (selected_song_filename, is_holiday)
        """
        holiday_probability = self.playlist_manager.get_holiday_selection_probability()
        holiday_roll = random.random()
        
        logger.info(f"🎄 Holiday prob: {holiday_probability:.1%}, rolled: {holiday_roll:.3f}", extra={'simple': True})
        
        if holiday_files and holiday_roll < holiday_probability:
            # Pick a random holiday song
            selected = random.choice(holiday_files)
            logger.info(f"🎄 Selected HOLIDAY song: {selected}", extra={'simple': True})
            return selected, True
        else:
            # Use weighted selection from regular songs
            if not regular_files:
                raise ValueError("No regular songs available")
            
            probabilities, all_files, _ = self.playlist_manager.calculate_probabilities(
                regular_files, [])  # Empty holiday list for regular-only selection
            
            selected_index = random.choices(range(len(all_files)), weights=probabilities)[0]
            selected = all_files[selected_index]
            logger.info(f"🎵 Selected REGULAR song: {selected}", extra={'simple': True})
            return selected, False
    
    def _play_dj_segment(self, mp3_file: str, segment_type: str, dj_probability: float) -> bool:
        """
        Attempt to play a DJ intro or outro segment.
        
        Args:
            mp3_file: Name of the song file
            segment_type: Either 'intro' or 'outro'
            dj_probability: Current DJ talk probability
            
        Returns:
            True if segment was played, False otherwise
        """
        check_method = self.dj_manager.check_intro_files if segment_type == 'intro' else self.dj_manager.check_outro_files
        files = check_method(mp3_file)
        
        if not files:
            logger.info(f"  📢 No {segment_type} files found", extra={'simple': True})
            return False
        
        roll = random.random()
        logger.info(f"  📢 {segment_type.capitalize()} files: {len(files)}, rolled: {roll:.3f}", extra={'simple': True})
        
        if roll < dj_probability:
            selected_file = random.choice(files)
            logger.info(f"  ✅ Playing {segment_type.upper()}: {selected_file}", extra={'simple': True})
            file_path = os.path.join(self.dj_path, selected_file)
            if self.audio_player.play(file_path):
                return True
            else:
                logger.warning(f"Failed to play {segment_type}: {selected_file}")
                return False
        else:
            logger.info(f"  ❌ {segment_type.capitalize()} skipped (roll {roll:.3f} >= prob {dj_probability:.3f})", extra={'simple': True})
            return False
    
    def play_random_mp3(self) -> bool:
        """
        Play a random MP3 file with optional intro and outro.
        
        Returns:
            True if a song was played successfully, False otherwise
        """
        # Get available files
        regular_files, holiday_files = self._get_song_files()
        
        if not regular_files and not holiday_files:
            logger.warning("No MP3 files found in the folders.")
            return False
        
        # Select song
        try:
            random_mp3, is_holiday_song = self._select_song(regular_files, holiday_files)
        except ValueError as e:
            logger.error(str(e))
            return False
        
        # Determine music path
        music_path = self.holiday_music_path if is_holiday_song else self.regular_music_path
        
        # Calculate DJ probability
        dj_probability = self._calculate_dj_probability()
        self.songs_since_last_dj_talk += 1
        
        logger.info(f"🎤 DJ prob: {dj_probability:.1%}, songs since last talk: {self.songs_since_last_dj_talk}", extra={'simple': True})
        
        # Play intro
        play_intro = self._play_dj_segment(random_mp3, 'intro', dj_probability)
        dj_talked = play_intro
        
        # Play song
        song_path = os.path.join(music_path, random_mp3)
        if not self.audio_player.play(song_path):
            logger.error(f"Failed to play song: {random_mp3}")
            return False
        
        # Play outro (only if intro didn't play)
        if not play_intro:
            play_outro = self._play_dj_segment(random_mp3, 'outro', dj_probability)
            if play_outro:
                dj_talked = True
        else:
            logger.info(f"  📢 Outro skipped (intro already played)", extra={'simple': True})
        
        # Reset counter if DJ talked
        if dj_talked:
            self.songs_since_last_dj_talk = 0
            logger.info(f"  🎤 DJ talked - resetting counter", extra={'simple': True})
        
        # Update history
        self.playlist_manager.update_history(random_mp3, is_holiday_song)
        return True

    def sigterm_handler(self, _signo: int, _stack_frame) -> None:
        """
        Handle termination signal for graceful shutdown.
        
        Args:
            _signo: Signal number
            _stack_frame: Stack frame (unused)
        """
        logger.info("Received termination signal, shutting down gracefully...")
        self.audio_player.stop()
        sys.exit(0)

def main() -> None:
    """Main entry point for the radio player."""
    from .constants import REGULAR_MUSIC_PATH, HOLIDAY_MUSIC_PATH, DJ_PATH
    
    # Create an instance of MusicPlayer
    player = MusicPlayer(REGULAR_MUSIC_PATH, HOLIDAY_MUSIC_PATH, DJ_PATH)

    # Handle SIGTERM to allow for graceful shutdown
    signal.signal(signal.SIGTERM, player.sigterm_handler)

    # Loop indefinitely to play random MP3s
    logger.info("Starting radio player...")
    while True:
        try:
            player.play_random_mp3()
        except KeyboardInterrupt:
            logger.info("Interrupted by user, shutting down...")
            player.audio_player.stop()
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            # Continue playing despite errors

if __name__ == "__main__":
    main()