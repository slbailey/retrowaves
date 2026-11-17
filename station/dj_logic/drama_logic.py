"""
Radio drama scheduling for Appalachia Radio.

Rules (owner's requirements):
- At most one drama part per hour (DRAMA_INTERVAL_SEC, default 3600).
- Never two drama slots back to back: at least DRAMA_MIN_SONGS_BETWEEN songs
  (default 3) must air between them, on top of the interval.
- One part per slot, and the next slot after Part N of a story is always
  Part N+1 of that story, until the story is finished.
- A new story is picked at random from those not aired recently, so every
  story airs once before any story repeats.

Progress is written to its own small JSON file (DRAMA_STATE_PATH) the moment
a part starts airing, so a crash or restart between Part 1 and Part 2 can't
lose the place. The DJ state file is only written on a clean shutdown
(SL2.3.1), which isn't enough to guarantee Part 2 follows Part 1.
"""

import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from station.dj_logic.asset_discovery import DramaPart, DramaStory

logger = logging.getLogger(__name__)


class DramaScheduler:
    def __init__(
        self,
        state_path: Optional[str],
        interval_sec: float = 3600.0,
        min_songs_between: int = 3,
        clock: Callable[[], float] = time.time,
        rng: Optional[random.Random] = None,
    ):
        self.state_path = Path(state_path) if state_path else None
        self.interval_sec = interval_sec
        self.min_songs_between = min_songs_between
        self._clock = clock
        self._rng = rng or random.Random()

        self.last_aired: Optional[float] = None
        self.in_progress: Optional[Dict] = None   # {"story": key, "next_part": n}
        self.recent: list = []                    # story keys, oldest first
        self.songs_since_drama = 0                # in memory only; a restart starts at 0
        self._load()
        if self.last_aired is None:
            # Never aired on this station: first drama about half an interval from now.
            self.last_aired = self._clock() - self.interval_sec / 2
            self._save()

    @classmethod
    def from_env(cls) -> Optional["DramaScheduler"]:
        if os.getenv("DRAMA_ENABLED", "true").lower() in ("0", "false", "no", "off"):
            logger.info("[DRAMA] Disabled by DRAMA_ENABLED")
            return None
        return cls(
            state_path=os.getenv("DRAMA_STATE_PATH", "/var/lib/retrowaves/drama_state.json"),
            interval_sec=float(os.getenv("DRAMA_INTERVAL_SEC", "3600")),
            min_songs_between=int(os.getenv("DRAMA_MIN_SONGS_BETWEEN", "3")),
        )

    # ------------------------------------------------------------------ decisions

    def is_due(self) -> bool:
        if self.songs_since_drama < self.min_songs_between:
            return False
        return (self._clock() - (self.last_aired or 0)) >= self.interval_sec

    def pick(self, stories: Dict[str, DramaStory]) -> Optional[Tuple[DramaStory, DramaPart]]:
        """The part that should air in the next drama slot (does not change state)."""
        if not stories:
            return None
        if self.in_progress:
            story = stories.get(self.in_progress.get("story"))
            n = int(self.in_progress.get("next_part", 0))
            if story and 1 <= n <= len(story.parts):
                return story, story.parts[n - 1]
            logger.warning(f"[DRAMA] In-progress story {self.in_progress} is no longer in the library; "
                           f"starting a new story")
        # Candidates: stories not aired within the last (len - 1) picks, so everything
        # airs once before anything repeats. Never repeat the story that just finished.
        window = max(len(stories) - 1, 0)
        recent = set(self.recent[-window:]) if window else set()
        candidates = sorted(k for k in stories if k not in recent) or sorted(stories)
        if len(candidates) > 1 and self.recent:
            candidates = [k for k in candidates if k != self.recent[-1]] or candidates
        key = self._rng.choice(candidates)
        return stories[key], stories[key].parts[0]

    # ------------------------------------------------------------------ state updates

    def record_song(self) -> None:
        self.songs_since_drama += 1

    def mark_aired(self, story_key: str, part_number: int, total_parts: int) -> None:
        """Called when a drama part starts airing."""
        self.last_aired = self._clock()
        self.songs_since_drama = 0
        if part_number < total_parts:
            self.in_progress = {"story": story_key, "next_part": part_number + 1}
        else:
            self.in_progress = None
        if part_number == 1:
            self.recent = [k for k in self.recent if k != story_key] + [story_key]
            self.recent = self.recent[-50:]
        self._save()
        logger.info(f"[DRAMA] Aired {story_key} part {part_number}/{total_parts}; "
                    f"next: {self.in_progress or 'new story'}")

    # ------------------------------------------------------------------ persistence

    def _load(self) -> None:
        if not self.state_path or not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.last_aired = data.get("last_aired")
            ip = data.get("in_progress")
            self.in_progress = ip if isinstance(ip, dict) and ip.get("story") else None
            self.recent = [k for k in data.get("recent", []) if isinstance(k, str)]
            logger.info(f"[DRAMA] Restored state: in_progress={self.in_progress}, "
                        f"{len(self.recent)} recent stories")
        except Exception as e:
            logger.warning(f"[DRAMA] Ignoring unreadable state {self.state_path}: {e}")

    def _save(self) -> None:
        if not self.state_path:
            return
        data = {"last_aired": self.last_aired, "in_progress": self.in_progress, "recent": self.recent}
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError as e:
            logger.warning(f"[DRAMA] Could not save state {self.state_path}: {e}")
