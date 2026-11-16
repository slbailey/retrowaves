"""
Filesystem tests for AssetDiscoveryManager (real directories, no fakes).

Covers the v2 directory-categorized layout (ADM1.2), the legacy flat layout,
atomic cache replacement (ADM2.1), legacy outtro spelling (ADM2.2), lifecycle
pools (ADM2.4), and DJEngine station-ID selection from the cache.
"""

import random
from pathlib import Path

from station.dj_logic.asset_discovery import AssetDiscoveryManager


def touch(root: Path, rel: str) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"ID3")
    return str(p)


def build_v2(root: Path) -> None:
    touch(root, "between-songs/Ink Spots - Maybe/Intro - 0059B47B_1 - Next up.mp3")
    touch(root, "between-songs/Ink Spots - Maybe/Intro - 0059C975_1 - So it seems.mp3")
    touch(root, "between-songs/Ink Spots - Maybe/Outro - 0059B455_1 - Timeless.mp3")
    touch(root, "between-songs/Gene Autry - Rudolph The Red Nosed Reindeer/Outtro - holiday-01.mp3")
    touch(root, "between-songs/Ink Spots - Maybe/notes.txt")
    touch(root, "generic/Intro - 0059C7ED_1 - Whether Appalachia.mp3")
    touch(root, "station-ids/legal/0059BF56_1 - Super Stimpak.mp3")
    touch(root, "station-ids/generic/0059BF51_1 - Enduring source.mp3")
    touch(root, "station-ids/generic/legacy - generic_id_002.mp3")
    touch(root, "station-ids/sequences/collectron/02 - concrete.mp3")
    touch(root, "station-ids/sequences/collectron/01 - setup.mp3")
    touch(root, "station-ids/sequences/collectron/03 - goofball.mp3")
    touch(root, "lifecycle/startup/StationOnline1.mp3")
    touch(root, "lifecycle/shutdown/StationOffline1.mp3")
    touch(root, "story/01 - 0059B7EA_1 - Hey friends.mp3")
    touch(root, "archive/generic5.mp3")


class TestV2Layout:
    def test_detects_v2(self, tmp_path):
        build_v2(tmp_path)
        assert AssetDiscoveryManager(tmp_path).layout == "v2"

    def test_per_song_clips_keyed_by_folder_name(self, tmp_path):
        build_v2(tmp_path)
        m = AssetDiscoveryManager(tmp_path)
        song = "/mnt/media/appalachia-radio-v2/music/regular/Ink Spots - Maybe.mp3"
        assert len(m.get_intros_for_song(song)) == 2
        assert len(m.get_outtros_for_song(song)) == 1
        assert all(p.endswith(".mp3") for p in m.get_intros_for_song(song))

    def test_outtro_spelling_accepted(self, tmp_path):
        build_v2(tmp_path)
        m = AssetDiscoveryManager(tmp_path)
        song = "/x/music/holiday/Gene Autry - Rudolph The Red Nosed Reindeer.mp3"
        assert len(m.get_outtros_for_song(song)) == 1

    def test_unknown_song_has_no_clips(self, tmp_path):
        build_v2(tmp_path)
        m = AssetDiscoveryManager(tmp_path)
        assert m.get_intros_for_song("/x/music/regular/Nobody - Nothing.mp3") == []

    def test_generic_pool(self, tmp_path):
        build_v2(tmp_path)
        m = AssetDiscoveryManager(tmp_path)
        assert len(m.generic_intros) == 1 and m.generic_outros == []

    def test_station_ids_and_sequence_order(self, tmp_path):
        build_v2(tmp_path)
        m = AssetDiscoveryManager(tmp_path)
        assert len(m.get_station_ids(legal=True)) == 1
        generic = m.get_station_ids(legal=False)
        assert len(generic) == 3  # two single-file IDs + one sequence
        seq = [entry for entry in generic if len(entry) > 1]
        assert len(seq) == 1
        assert [Path(p).name[:2] for p in seq[0]] == ["01", "02", "03"]

    def test_lifecycle_pools(self, tmp_path):
        build_v2(tmp_path)
        m = AssetDiscoveryManager(tmp_path)
        assert len(m.startup_announcements) == 1
        assert len(m.shutdown_announcements) == 1

    def test_story_and_archive_never_discovered(self, tmp_path):
        build_v2(tmp_path)
        m = AssetDiscoveryManager(tmp_path)
        everything = (
            [p for v in m.intros_per_song.values() for p in v]
            + [p for v in m.outtros_per_song.values() for p in v]
            + m.generic_intros + m.generic_outros
            + [p for e in m.legal_ids + m.generic_ids for p in e]
            + m.startup_announcements + m.shutdown_announcements
        )
        assert not any("/story/" in p.replace("\\", "/") or "/archive/" in p.replace("\\", "/") for p in everything)


def build_legacy(root: Path) -> None:
    touch(root, "mus_radio_76_general_inkspots_maybe_intro1.mp3")
    touch(root, "mus_radio_76_general_inkspots_maybe_outtro.mp3")
    touch(root, "mus_radio_76_general_inkspots_maybe_outro2.mp3")
    touch(root, "generic_intro1.mp3")
    touch(root, "JulieScene01-pt1.mp3")
    touch(root, "ids/legal/legal_id.mp3")
    touch(root, "ids/generic/generic_id_001.mp3")
    touch(root, "station_starting_up/StationOnline1.mp3")
    touch(root, "station_shutting_down/StationOffline1.mp3")


class TestLegacyLayout:
    def test_legacy_still_works(self, tmp_path):
        build_legacy(tmp_path)
        m = AssetDiscoveryManager(tmp_path)
        assert m.layout == "legacy"
        song = "/x/songs/mus_radio_76_general_inkspots_maybe.mp3"
        assert len(m.get_intros_for_song(song)) == 1
        assert len(m.get_outtros_for_song(song)) == 2  # outtro + outro (ADM2.2)
        assert len(m.generic_intros) == 1
        assert len(m.get_station_ids(True)) == 1 and len(m.get_station_ids(False)) == 1
        assert len(m.startup_announcements) == 1 and len(m.shutdown_announcements) == 1


class TestAtomicRescan:
    def test_rescan_replaces_cache(self, tmp_path):
        v2 = tmp_path / "v2"
        legacy = tmp_path / "legacy"
        build_v2(v2)
        build_legacy(legacy)
        m = AssetDiscoveryManager(v2)
        assert "Ink Spots - Maybe" in m.intros_per_song
        m.dj_path = legacy  # rollback = repoint DJ_PATH
        m._scan()
        assert m.layout == "legacy"
        assert "Ink Spots - Maybe" not in m.intros_per_song
        assert "mus_radio_76_general_inkspots_maybe" in m.intros_per_song

    def test_missing_path_yields_empty_cache(self, tmp_path):
        m = AssetDiscoveryManager(tmp_path / "nope")
        assert m.layout == "none" and m.intros_per_song == {} and m.generic_ids == []


class TestDJEngineStationIdSelection:
    def _engine(self, manager, dj_path):
        from station.dj_logic.dj_engine import DJEngine
        engine = DJEngine.__new__(DJEngine)  # bypass heavy __init__; only these attrs are used
        engine.asset_manager = manager
        engine.dj_asset_path = Path(dj_path)
        return engine

    def test_sequence_returns_all_parts_in_order(self, tmp_path):
        build_v2(tmp_path)
        m = AssetDiscoveryManager(tmp_path)
        m.generic_ids = [e for e in m.generic_ids if len(e) > 1]  # force the sequence
        paths = self._engine(m, tmp_path)._select_station_ids(count=1, legal=False)
        assert [Path(p).name[:2] for p in paths] == ["01", "02", "03"]

    def test_legal_id_from_cache(self, tmp_path):
        build_v2(tmp_path)
        m = AssetDiscoveryManager(tmp_path)
        paths = self._engine(m, tmp_path)._select_station_ids(count=1, legal=True)
        assert len(paths) == 1 and "station-ids" in paths[0].replace("\\", "/")

    def test_falls_back_to_legacy_dirs_when_cache_empty(self, tmp_path):
        build_legacy(tmp_path)

        class NoCache:
            pass

        random.seed(1)
        paths = self._engine(NoCache(), tmp_path)._select_station_ids(count=1, legal=False)
        assert len(paths) == 1 and paths[0].endswith("generic_id_001.mp3")
