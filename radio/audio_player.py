import logging
import os
import pygame
from pygame import mixer
from typing import Optional

logger = logging.getLogger(__name__)

class AudioPlayer:
    """Handles audio playback using pygame mixer."""
    
    TICK_RATE = 10  # Frames per second for the playback loop
    
    def __init__(self, frequency: int = 48000, buffer_size: int = 2048) -> None:
        """
        Initialize the audio player.
        
        Args:
            frequency: Audio frequency in Hz (default: 48000)
            buffer_size: Audio buffer size (default: 2048)
        """
        try:
            # Set dummy video driver for headless environments (WSL, servers, etc.)
            if 'DISPLAY' not in os.environ:
                os.environ['SDL_VIDEODRIVER'] = 'dummy'
            
            pygame.mixer.pre_init(frequency=frequency, buffer=buffer_size)
            pygame.mixer.init()
            
            # Initialize display for headless environments (required by pygame)
            if not pygame.display.get_init():
                pygame.display.init()
                # Create a minimal dummy surface (required but not used)
                pygame.display.set_mode((1, 1), flags=pygame.HIDDEN)
            
            logger.info("Audio player initialized successfully")
        except pygame.error as e:
            logger.error(f"Failed to initialize audio player: {e}")
            raise
    
    def play(self, mp3_file: str) -> bool:
        """
        Play an MP3 file using pygame.
        
        Args:
            mp3_file: Path to the MP3 file to play
            
        Returns:
            True if playback started successfully, False otherwise
        """
        if not os.path.exists(mp3_file):
            logger.error(f"Audio file not found: {mp3_file}")
            return False
        
        try:
            pygame.mixer.music.load(mp3_file)
            pygame.mixer.music.play()
            logger.info(f"Playing: {os.path.basename(mp3_file)}")
            
            clock = pygame.time.Clock()
            while pygame.mixer.music.get_busy():
                clock.tick(self.TICK_RATE)
                # Allow for interruption by checking events
                pygame.event.pump()
            
            logger.debug(f"Finished playing: {os.path.basename(mp3_file)}")
            return True
        except pygame.error as e:
            logger.error(f"Error playing {mp3_file}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error playing {mp3_file}: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the currently playing music."""
        try:
            pygame.mixer.music.stop()
            logger.info("Playback stopped")
        except pygame.error as e:
            logger.error(f"Error stopping playback: {e}")
    
    def is_playing(self) -> bool:
        """Check if music is currently playing."""
        try:
            return pygame.mixer.music.get_busy()
        except pygame.error:
            return False
