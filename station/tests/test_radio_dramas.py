"""
Radio drama discovery, scheduling and DJ integration (real directories, no ffmpeg).

Owner's rules under test:
- at most one drama per hour, never back to back
- one part per slot; Part 2 always follows Part 1 (also across restarts)
- optional Julie lead-in / lead-out around each part
"""

import random
from pathlib import Path

from station.broadcast_core.audio_event import AudioEvent
from station.dj_logic.asset_discovery import AssetDiscoveryManager
from station.dj_logic.dj_engine import DJEngine
from station.dj_logic.drama_logic import DramaScheduler

SERIES = "Tales from the West Virginia Hills"


def touch(root: Path, rel: str) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"ID3")
    return str(p)


def build(root: Path) -> None:
    touch(root, "between-songs/Ink Spots - Maybe/Intro - x.mp3")
    for story in ("Flatwoods", "Grafton", "Mothman"):
        for n in (1, 2):
            touch(root, f"dramas/{SERIES}/{story} - Part {n}.mp3")
            touch(root, f"dramas/{SERIES}/Intro - {story} - Part {n}.mp3")
            touch(root, f"dramas/{SERIES}/Outtro - {story} - Part {n}.mp3" if story == "Grafton"
                  else f"dramas/{SERIES}/Outro - {story} - Part {n}.mp3")
        touch(root, f"dramas/{SERIES}/{story} - Part 1.txt")
    touch(root, "dramas/One Offs/The Lonely Road.mp3")          # single-part story, no clips
    touch(root, "dramas/One Offs/Orphan - Part 2.mp3")          # no Part 1: never airs
    touch(root, "dramas/One Offs/Gappy - Part 1.mp3")
    touch(root, "dramas/One Offs/Gappy - Part 3.mp3")           # Part 2 missing: only Part 1 airs


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


# ---------------------------------------------------------------- discovery

def test_discovers_stories_parts_and_clips(tmp_path):
    build(tmp_path)
    d = AssetDiscoveryManager(tmp_path).get_dramas()
    flat = d[f"{SERIES}/Flatwoods"]
    assert [p.number for p in flat.parts] == [1, 2]
    assert flat.parts[0].intro.endswith("Intro - Flatwoods - Part 1.mp3")
    assert flat.parts[1].outro.endswith("Outro - Flatwoods - Part 2.mp3")
    # "Outtro" spelling accepted
    assert d[f"{SERIES}/Grafton"].parts[0].outro.endswith("Outtro - Grafton - Part 1.mp3")


def test_single_part_orphan_and_gaps(tmp_path):
    build(tmp_path)
    d = AssetDiscoveryManager(tmp_path).get_dramas()
    lonely = d["One Offs/The Lonely Road"]
    assert len(lonely.parts) == 1 and lonely.parts[0].intro is None
    assert "One Offs/Orphan" not in d
    assert [p.number for p in d["One Offs/Gappy"].parts] == [1]


def test_clips_are_not_episodes(tmp_path):
    build(tmp_path)
    d = AssetDiscoveryManager(tmp_path).get_dramas()
    assert not any(k.split("/", 1)[1].lower().startswith(("intro", "outro", "outtro")) for k in d)


# ---------------------------------------------------------------- scheduler

def test_first_drama_half_an_hour_after_first_start(tmp_path):
    clock = Clock()
    s = DramaScheduler(str(tmp_path / "state.json"), clock=clock)
    for _ in range(3):
        s.record_song()
    assert not s.is_due()
    clock.t += 1800
    assert s.is_due()


def test_hourly_and_never_back_to_back(tmp_path):
    clock = Clock()
    s = DramaScheduler(str(tmp_path / "state.json"), clock=clock)
    s.mark_aired("S/A", 1, 2)
    clock.t += 4000                       # well past the hour...
    assert not s.is_due()                 # ...but no songs have aired since
    s.record_song(); s.record_song()
    assert not s.is_due()
    s.record_song()
    assert s.is_due()
    s.mark_aired("S/A", 2, 2)
    s.record_song(); s.record_song(); s.record_song()
    clock.t += 3599
    assert not s.is_due()
    clock.t += 1
    assert s.is_due()


def test_part_two_always_follows_part_one_even_across_restart(tmp_path):
    build(tmp_path)
    stories = AssetDiscoveryManager(tmp_path).get_dramas()
    state = str(tmp_path / "state.json")
    for seed in range(20):
        s = DramaScheduler(state, rng=random.Random(seed))
        story, part = s.pick(stories)
        if part.number != 1:            # finish whatever an earlier seed left in progress
            s.mark_aired(story.key, part.number, len(story.parts))
            story, part = s.pick(stories)
        assert part.number == 1
        s.mark_aired(story.key, 1, len(story.parts))
        if len(story.parts) == 1:
            continue
        restarted = DramaScheduler(state, rng=random.Random(seed + 100))
        story2, part2 = restarted.pick(stories)
        assert (story2.key, part2.number) == (story.key, 2)
        restarted.mark_aired(story2.key, 2, len(story2.parts))


def test_every_story_airs_before_any_repeats(tmp_path):
    build(tmp_path)
    stories = AssetDiscoveryManager(tmp_path).get_dramas()
    s = DramaScheduler(None, rng=random.Random(7))
    seen = []
    while len(seen) < len(stories):
        story, part = s.pick(stories)
        assert part.number == 1
        seen.append(story.key)
        for p in story.parts:
            s.mark_aired(story.key, p.number, len(story.parts))
    assert sorted(seen) == sorted(stories)
    nxt, _ = s.pick(stories)
    assert nxt.key != seen[-1]


def test_vanished_in_progress_story_starts_a_new_one(tmp_path):
    build(tmp_path)
    stories = AssetDiscoveryManager(tmp_path).get_dramas()
    s = DramaScheduler(None, rng=random.Random(1))
    s.mark_aired("Gone/Story", 1, 2)
    story, part = s.pick(stories)
    assert story.key in stories and part.number == 1


def test_unreadable_state_is_ignored(tmp_path):
    state = tmp_path / "state.json"
    state.write_text("{not json")
    s = DramaScheduler(str(state))
    assert s.in_progress is None


# ---------------------------------------------------------------- DJ integration

def make_dj(tmp_path, clock):
    build(tmp_path)
    import shutil
    shutil.rmtree(tmp_path / "dramas" / "One Offs")   # only two-part stories with clips here
    dj = DJEngine(dj_asset_path=str(tmp_path))
    dj.drama_scheduler = DramaScheduler(str(tmp_path / "state.json"), clock=clock, rng=random.Random(3))
    dj._select_next_song = lambda current_song_path=None: str(tmp_path / "song.mp3")
    return dj


def test_drama_break_structure(tmp_path):
    clock = Clock()
    dj = make_dj(tmp_path, clock)
    for _ in range(3):
        dj.drama_scheduler.record_song()
    clock.t += 3600
    dj.on_segment_started(AudioEvent(path=str(tmp_path / "prev.mp3"), type="song"))
    intent = dj.current_intent
    assert intent.drama is not None
    assert [e.type for e in intent.drama] == ["intro", "drama", "outro"]
    assert intent.outro is None and intent.intro is None          # no stacked Julie talk
    assert not (intent.station_ids and not intent.has_legal_id)   # no generic ID
    part = next(e for e in intent.drama if e.type == "drama")
    assert part.metadata["segment_class"] == "radio_drama"
    assert part.metadata["part_number"] == 1 and part.metadata["total_parts"] == 2
    assert all(e.intent_id == intent.intent_id for e in intent.drama)


def test_progress_advances_when_part_airs_not_when_queued(tmp_path):
    clock = Clock()
    dj = make_dj(tmp_path, clock)
    for _ in range(3):
        dj.drama_scheduler.record_song()
    clock.t += 3600
    dj.on_segment_started(AudioEvent(path=str(tmp_path / "prev.mp3"), type="song"))
    part = next(e for e in dj.current_intent.drama if e.type == "drama")
    assert dj.drama_scheduler.in_progress is None                 # queued only
    dj.on_segment_started(part)                                   # now it airs
    assert dj.drama_scheduler.in_progress == {"story": part.metadata["drama_story_key"], "next_part": 2}
    assert dj.drama_scheduler.songs_since_drama == 0


def test_no_drama_when_not_due(tmp_path):
    clock = Clock()
    dj = make_dj(tmp_path, clock)
    dj.on_segment_started(AudioEvent(path=str(tmp_path / "prev.mp3"), type="song"))
    assert dj.current_intent.drama is None


def test_disabled_without_scheduler(tmp_path):
    build(tmp_path)
    dj = DJEngine(dj_asset_path=str(tmp_path))
    dj._select_next_song = lambda current_song_path=None: str(tmp_path / "song.mp3")
    dj.on_segment_started(AudioEvent(path=str(tmp_path / "prev.mp3"), type="song"))
    assert dj.current_intent.drama is None
