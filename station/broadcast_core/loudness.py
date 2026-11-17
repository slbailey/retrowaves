"""
Loudness leveling for Appalachia Radio.

Every file that airs (songs, Julie clips, station IDs, radio dramas) is
measured once with FFmpeg's EBU R128 meter and played back at a gain that
brings its integrated loudness to a common target (default -18 LUFS).

Design rules:
- Measurement happens on a background thread at idle CPU priority, never on
  the playout path. Results are cached on local disk, keyed by path, and
  re-measured when a file's size or mtime changes.
- gain_for() is a dict lookup: no filesystem access, no blocking, so it is
  safe to call from DJ DO. A file that hasn't been measured yet plays at
  unity gain, as it always did before this module existed.
- Boost is capped so the file's sample peak stays at or below max_peak_dbfs,
  so applying the gain can never clip.
"""

import json
import logging
import os
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

Measurement = Tuple[float, float]  # (integrated LUFS, sample peak dBFS)

_I_RE = re.compile(r"^\s*I:\s*(-?[\d.]+|-inf)\s*LUFS", re.MULTILINE)
_PEAK_RE = re.compile(r"^\s*Peak:\s*(-?[\d.]+|-inf)\s*dBFS", re.MULTILINE)
_SILENT_LUFS = -60.0


def _lower_priority() -> None:
    """Child-process hook: drop the station's real-time scheduling and run idle."""
    try:
        os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))
    except (AttributeError, OSError):
        pass
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass


def measure_ffmpeg(path: str, timeout: float = 300.0) -> Optional[Measurement]:
    """Measure integrated loudness and sample peak with ffmpeg's ebur128 filter."""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-i", path,
           "-af", "ebur128=peak=sample", "-f", "null", "-"]
    kwargs = {"preexec_fn": _lower_priority} if os.name == "posix" else {}
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"[LOUDNESS] Could not measure {path}: {e}")
        return None
    text = proc.stderr.decode("utf-8", "replace")
    # The summary block comes last; take the final match of each.
    i_vals, p_vals = _I_RE.findall(text), _PEAK_RE.findall(text)
    if proc.returncode != 0 or not i_vals or not p_vals:
        logger.warning(f"[LOUDNESS] No loudness summary for {path} (rc={proc.returncode})")
        return None
    lufs = float("-inf") if i_vals[-1] == "-inf" else float(i_vals[-1])
    peak = float("-inf") if p_vals[-1] == "-inf" else float(p_vals[-1])
    return lufs, peak


class LoudnessIndex:
    """Cache of per-file loudness measurements plus the gain each file should play at."""

    def __init__(
        self,
        cache_path: Optional[str],
        roots: Iterable[str] = (),
        target_lufs: float = -18.0,
        max_peak_dbfs: float = -1.0,
        max_boost_db: float = 12.0,
        max_cut_db: float = 20.0,
        rescan_interval_sec: float = 3600.0,
        measure: Callable[[str], Optional[Measurement]] = measure_ffmpeg,
    ):
        self.cache_path = Path(cache_path) if cache_path else None
        self.roots = [str(r) for r in roots if r]
        self.target_lufs = target_lufs
        self.max_peak_dbfs = max_peak_dbfs
        self.max_boost_db = max_boost_db
        self.max_cut_db = max_cut_db
        self.rescan_interval_sec = rescan_interval_sec
        self._measure = measure

        self._lock = threading.Lock()
        self._entries: Dict[str, dict] = {}
        self._priority: deque = deque()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._dirty = 0
        self._load()

    @classmethod
    def from_env(cls, roots: Iterable[str]) -> Optional["LoudnessIndex"]:
        if os.getenv("LOUDNESS_ENABLED", "true").lower() in ("0", "false", "no", "off"):
            logger.info("[LOUDNESS] Disabled by LOUDNESS_ENABLED")
            return None
        return cls(
            cache_path=os.getenv("LOUDNESS_CACHE_PATH", "/var/lib/retrowaves/loudness.json"),
            roots=roots,
            target_lufs=float(os.getenv("LOUDNESS_TARGET_LUFS", "-18")),
            max_peak_dbfs=float(os.getenv("LOUDNESS_MAX_PEAK_DBFS", "-1")),
        )

    # ------------------------------------------------------------------ gain

    def gain_db_for_measurement(self, lufs: float, peak: float) -> float:
        if lufs != lufs or lufs <= _SILENT_LUFS:  # NaN, -inf or near-silent: leave alone
            return 0.0
        gain = self.target_lufs - lufs
        gain = max(-self.max_cut_db, min(self.max_boost_db, gain))
        if peak != float("-inf"):
            gain = min(gain, self.max_peak_dbfs - peak)  # never push a peak past the ceiling
        return gain

    def gain_for(self, path: str) -> float:
        """Linear gain for path; 1.0 if it hasn't been measured. Never touches the filesystem."""
        with self._lock:
            entry = self._entries.get(path)
        if not entry:
            return 1.0
        return 10.0 ** (self.gain_db_for_measurement(entry["lufs"], entry["peak"]) / 20.0)

    def is_measured(self, path: str) -> bool:
        with self._lock:
            return path in self._entries

    def request(self, paths: Iterable[str]) -> None:
        """Ask the worker to measure these soon (non-blocking)."""
        added = False
        with self._lock:
            for p in paths:
                if p and p not in self._entries and p not in self._priority:
                    self._priority.append(p)
                    added = True
        if added:
            self._wake.set()

    # ------------------------------------------------------------------ worker

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="loudness-index", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run(self) -> None:
        try:  # this thread inherits the station's SCHED_RR; it doesn't need it
            os.sched_setscheduler(0, os.SCHED_OTHER, os.sched_param(0))
        except (AttributeError, OSError):
            pass
        next_sweep = 0.0
        while not self._stop.is_set():
            self._drain_priority()
            if time.monotonic() >= next_sweep:
                self.sweep()
                next_sweep = time.monotonic() + self.rescan_interval_sec
            self._wake.wait(timeout=60)
            self._wake.clear()

    def _drain_priority(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                if not self._priority:
                    break
                path = self._priority.popleft()
            self.measure_path(path)
        self._flush()

    def sweep(self) -> int:
        """Measure every new or changed file under the roots. Returns files measured."""
        count = 0
        seen = set()
        for path in self._iter_files():
            seen.add(path)
            self._drain_priority()  # an upcoming segment always jumps the queue
            if self._stop.is_set():
                break
            if self.measure_path(path):
                count += 1
                if self._dirty >= 20:
                    self._flush()
        if not self._stop.is_set() and seen:
            with self._lock:
                gone = [p for p in self._entries if p not in seen and self._under_roots(p)]
                for p in gone:
                    del self._entries[p]
                self._dirty += len(gone)
        self._flush()
        if count:
            logger.info(f"[LOUDNESS] Measured {count} file(s); {len(self._entries)} cached")
        return count

    def measure_path(self, path: str) -> bool:
        """Measure path if it is new or changed. Returns True if a measurement was taken."""
        try:
            st = os.stat(path)
        except OSError:
            return False
        with self._lock:
            entry = self._entries.get(path)
        if entry and entry.get("size") == st.st_size and entry.get("mtime") == int(st.st_mtime):
            return False
        result = self._measure(path)
        if result is None:
            return False
        lufs, peak = result
        with self._lock:
            self._entries[path] = {"size": st.st_size, "mtime": int(st.st_mtime), "lufs": lufs, "peak": peak}
            self._dirty += 1
        logger.debug(f"[LOUDNESS] {path}: {lufs:.1f} LUFS, peak {peak:.1f} dBFS, "
                     f"gain {self.gain_db_for_measurement(lufs, peak):+.1f} dB")
        return True

    def _under_roots(self, path: str) -> bool:
        return any(path.startswith(r.rstrip("/\\") + os.sep) or path.startswith(r.rstrip("/\\") + "/")
                   for r in self.roots)

    def _iter_files(self) -> List[str]:
        files: List[str] = []
        for root in self.roots:
            for dirpath, dirs, names in os.walk(root):
                dirs[:] = sorted(d for d in dirs if not d.startswith((".", "_")))
                files.extend(os.path.join(dirpath, n) for n in sorted(names)
                             if n.lower().endswith(".mp3") and not n.startswith("."))
        return files

    # ------------------------------------------------------------------ persistence

    def _load(self) -> None:
        if not self.cache_path or not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            entries = data.get("entries", {})
            if isinstance(entries, dict):
                self._entries = {
                    k: v for k, v in entries.items()
                    if isinstance(v, dict) and {"size", "mtime", "lufs", "peak"} <= set(v)
                }
            logger.info(f"[LOUDNESS] Loaded {len(self._entries)} cached measurement(s)")
        except Exception as e:
            logger.warning(f"[LOUDNESS] Ignoring unreadable cache {self.cache_path}: {e}")

    def _flush(self) -> None:
        if not self.cache_path or not self._dirty:
            return
        with self._lock:
            snapshot = dict(self._entries)
            self._dirty = 0
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": 1, "entries": snapshot}), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except OSError as e:
            logger.warning(f"[LOUDNESS] Could not write cache {self.cache_path}: {e}")
