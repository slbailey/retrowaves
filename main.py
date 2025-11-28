#!/usr/bin/env python3
"""Main entry point for Appalachia Radio - runs headless on Raspberry Pi."""

import argparse
import logging
import os
import select
import signal
import sys
import threading
import time
from pathlib import Path
from radio.radio import MusicPlayer
from radio.constants import REGULAR_MUSIC_PATH, HOLIDAY_MUSIC_PATH, DJ_PATH

# ANSI color codes for prettier output
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'

class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output."""
    
    COLORS = {
        'DEBUG': Colors.DIM + Colors.WHITE,
        'INFO': Colors.CYAN,
        'WARNING': Colors.YELLOW,
        'ERROR': Colors.RED,
        'CRITICAL': Colors.BOLD + Colors.RED,
    }
    
    def __init__(self, *args, **kwargs):
        # For interactive mode, use message-only format
        # For non-interactive, use standard format
        if 'fmt' not in kwargs:
            kwargs['fmt'] = '%(message)s'
        super().__init__(*args, **kwargs)
    
    def format(self, record):
        # Format the message
        if hasattr(self, '_is_interactive') and self._is_interactive:
            # For interactive mode, just return the message directly (no timestamps, no module names)
            msg = record.getMessage()
            levelname = record.levelname
            
            # Prettier format for interactive mode
            if levelname == 'INFO' and 'Playing:' in msg:
                song_name = msg.replace('Playing: ', '')
                return f"{Colors.GREEN}▶ {Colors.RESET}{Colors.BOLD}{song_name}{Colors.RESET}\r\n"
            elif levelname == 'WARNING':
                return f"{Colors.YELLOW}⚠ {msg}{Colors.RESET}\r\n"
            elif levelname == 'ERROR':
                return f"{Colors.RED}✗ {msg}{Colors.RESET}\r\n"
            elif levelname == 'INFO':
                # Just return the message as-is with proper line ending
                return f"{msg}\r\n"
            else:
                # Add color to levelname for other levels
                if levelname in self.COLORS:
                    colored_level = f"{self.COLORS[levelname]}{levelname}{Colors.RESET}"
                    return f"{colored_level} {msg}\r\n"
                return f"{msg}\r\n"
        else:
            # Standard format for file/non-interactive - use parent formatter
            return super().format(record)

# Global flags for interactive keyboard control
skip_song = False
exit_requested = False
player_instance = None

def read_keyboard():
    """Read keyboard input in a separate thread for interactive mode."""
    global skip_song, exit_requested, player_instance
    
    import termios
    import tty
    
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    
    try:
        tty.setraw(sys.stdin.fileno())
        
        while not exit_requested:
            if select.select([sys.stdin], [], [], 0.1)[0]:
                char = sys.stdin.read(1)
                
                if char == '\n' or char == '\r':  # Enter key
                    print(f"\n{Colors.YELLOW}[ENTER] Skipping to next song...{Colors.RESET}\n", flush=True)
                    skip_song = True
                    if player_instance:
                        player_instance.audio_player.stop()
                elif char == '\x1b':  # ESC key
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        sys.stdin.read(1)  # Read rest of escape sequence
                    else:
                        print(f"\n{Colors.YELLOW}[ESC] Exiting...{Colors.RESET}\n", flush=True)
                        exit_requested = True
                        skip_song = True
                        if player_instance:
                            player_instance.audio_player.stop()
                elif char == '\x03':  # Ctrl+C
                    print(f"\n{Colors.YELLOW}[Ctrl+C] Exiting...{Colors.RESET}\n", flush=True)
                    exit_requested = True
                    skip_song = True
                    if player_instance:
                        player_instance.audio_player.stop()
                    break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def setup_logging(interactive: bool = False, log_file: Path = None):
    """Setup logging with appropriate formatters."""
    handlers = []
    
    # File handler (always, with standard format)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        handlers.append(file_handler)
    
    # Console handler (with colors if interactive)
    console_handler = logging.StreamHandler(sys.stdout)
    if interactive:
        formatter = ColoredFormatter(fmt='%(message)s')
        formatter._is_interactive = True
        console_handler.setFormatter(formatter)
    else:
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
    handlers.append(console_handler)
    
    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers
    )

def main() -> None:
    """Main entry point for the radio player application."""
    global skip_song, exit_requested, player_instance
    
    parser = argparse.ArgumentParser(description='Appalachia Radio - Continuous Music Player')
    parser.add_argument(
        '--interactive', '-i',
        action='store_true',
        help='Enable interactive mode with keyboard controls (Enter to skip, ESC to exit)'
    )
    parser.add_argument(
        '--local',
        action='store_true',
        help='Use local project directories instead of configured paths (for testing)'
    )
    args = parser.parse_args()
    
    # Determine paths
    if args.local:
        project_root = Path(__file__).parent
        regular_music_path = str(project_root / 'songs')
        holiday_music_path = str(project_root / 'holiday_songs')
        dj_path = str(project_root / 'julie')
    else:
        regular_music_path = REGULAR_MUSIC_PATH
        holiday_music_path = HOLIDAY_MUSIC_PATH
        dj_path = DJ_PATH
    
    # Setup logging
    project_root = Path(__file__).parent
    log_dir = project_root / 'logs'
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / 'radio.log' if not args.interactive else None
    
    setup_logging(interactive=args.interactive, log_file=log_file)
    logger = logging.getLogger(__name__)
    
    # Startup banner
    if args.interactive:
        print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}  Appalachia Radio - Interactive Mode{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.RESET}")
        print(f"{Colors.DIM}Regular music: {regular_music_path}{Colors.RESET}")
        print(f"{Colors.DIM}Holiday music: {holiday_music_path}{Colors.RESET}")
        print(f"{Colors.DIM}DJ path: {dj_path}{Colors.RESET}")
        print(f"\n{Colors.BOLD}Controls:{Colors.RESET}")
        print(f"  {Colors.GREEN}[ENTER]{Colors.RESET} - Skip to next song")
        print(f"  {Colors.GREEN}[ESC]{Colors.RESET}   - Exit")
        print(f"  {Colors.GREEN}[Ctrl+C]{Colors.RESET} - Exit")
        print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.RESET}\n")
    else:
        logger.info("=" * 60)
        logger.info("Appalachia Radio - Starting up")
        if log_file:
            logger.info(f"Log file: {log_file}")
        logger.info(f"Regular music: {regular_music_path}")
        logger.info(f"Holiday music: {holiday_music_path}")
        logger.info(f"DJ path: {dj_path}")
        logger.info("=" * 60)
    
    # Check directories and count files
    for path_name, path in [
        ('Regular music', regular_music_path),
        ('Holiday music', holiday_music_path),
        ('DJ', dj_path)
    ]:
        if os.path.exists(path):
            mp3_count = len([f for f in os.listdir(path) if f.endswith('.mp3')])
            if args.interactive:
                print(f"{Colors.DIM}{path_name}: {mp3_count} MP3 files{Colors.RESET}")
            else:
                logger.info(f"{path_name} directory: {mp3_count} MP3 files found")
        else:
            if args.interactive:
                print(f"{Colors.YELLOW}Warning: {path_name} directory does not exist: {path}{Colors.RESET}")
            else:
                logger.warning(f"{path_name} directory does not exist: {path}")
    
    # Create an instance of MusicPlayer
    try:
        player = MusicPlayer(regular_music_path, holiday_music_path, dj_path)
        player_instance = player
    except Exception as e:
        logger.error(f"Failed to initialize MusicPlayer: {e}", exc_info=True)
        sys.exit(1)

    # Handle SIGTERM to allow for graceful shutdown
    signal.signal(signal.SIGTERM, player.sigterm_handler)
    if not args.interactive:
        # Also handle SIGHUP for systemd
        signal.signal(signal.SIGHUP, player.sigterm_handler)
    
    # Start keyboard input thread if interactive
    keyboard_thread = None
    if args.interactive:
        keyboard_thread = threading.Thread(target=read_keyboard, daemon=True)
        keyboard_thread.start()
        print(f"{Colors.CYAN}Radio player started - playing music continuously...{Colors.RESET}\n")
    else:
        logger.info("Radio player started - playing music continuously...")
    
    # Loop indefinitely to play random MP3s
    consecutive_errors = 0
    max_consecutive_errors = 10
    
    try:
        while not exit_requested:
            skip_song = False
            
            try:
                success = player.play_random_mp3()
                
                if exit_requested:
                    break
                
                if success:
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                    logger.warning(f"Failed to play song (consecutive errors: {consecutive_errors})")
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(f"Too many consecutive errors ({consecutive_errors}), exiting...")
                        exit_requested = True
                        break
            except KeyboardInterrupt:
                if args.interactive:
                    print(f"\n{Colors.YELLOW}Interrupted by user, shutting down...{Colors.RESET}")
                else:
                    logger.info("Interrupted by user, shutting down...")
                exit_requested = True
                break
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Error during playback: {e}", exc_info=True)
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(f"Too many consecutive errors ({consecutive_errors}), exiting...")
                    exit_requested = True
                    break
                # Wait a bit before retrying after an error
                time.sleep(5)
            
            # If skip was requested, continue to next song immediately
            if skip_song and not exit_requested and args.interactive:
                time.sleep(0.3)  # Brief pause before next song
                
    finally:
        player.audio_player.stop()
        if args.interactive:
            print(f"\n{Colors.CYAN}Session ended.{Colors.RESET}\n")
        else:
            logger.info("Session ended.")

if __name__ == "__main__":
    main()