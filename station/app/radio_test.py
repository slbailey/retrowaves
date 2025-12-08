import os
from typing import Optional

from station.music_logic.media_library import MediaLibrary
from station.music_logic.rotation_manager import RotationManager


def _load_dotenv_simple(dotenv_path: Optional[str] = None) -> None:
    """
    Minimal .env loader (no external dependencies).
    - Supports KEY=VALUE lines
    - Ignores comments (#) and blank lines
    - Does not handle quotes or escapes
    """
    path = dotenv_path or os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key and value and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        # Silent fallback if .env cannot be read
        pass


def main() -> None:
    # Load environment variables
    _load_dotenv_simple()

    # Initialize media library
    library = MediaLibrary.from_env()

    # Initialize rotation manager (phase 1 simplified)
    rotation = RotationManager(regular_tracks=library.regular_tracks, holiday_tracks=library.holiday_tracks)

    # Print discovery summary
    print(f"Discovered {len(library.regular_tracks)} regular songs, {len(library.holiday_tracks)} holiday songs")
    print("Rotation picks:")

    # Select and print 5 songs
    for _ in range(5):
        song = rotation.select_next_song()
        print(f" - {song}")


if __name__ == "__main__":
    main()


