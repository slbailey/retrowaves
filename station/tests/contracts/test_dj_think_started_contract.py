"""
Contract tests for DJ4.1 / DJ4.2 — THINK started / completed events (Station-local)

See docs/contracts/DJ_ENGINE_CONTRACT.md

Since Phase 3 (segment_playing architecture) the THINK lifecycle events are
Station-local observability: they are written to the station log, and are
NOT sent to Tower (Tower accepts only the four events in EVENT_INVENTORY.md
and rejects anything else).

Tests:
- DJ4.1: "THINK started" logged exactly once per THINK cycle, with the
  current segment's type and path, before THINK logic runs
- DJ4.2: "THINK completed" logged exactly once per THINK cycle, after
  "THINK started", with think duration (ms) and the DJIntent id
- Neither is logged for non-song segments (no THINK runs) or during DO
- Neither is ever sent to Tower; THINK sends nothing to Tower at all
"""

import logging
import re

import pytest

from station.dj_logic.dj_engine import DJEngine
from station.tests.contracts.test_doubles import create_fake_audio_event

DJ_LOGGER = "station.dj_logic.dj_engine"
STARTED = re.compile(r"\[DJ\] THINK started(?: \(\w+\))?: segment=(\S+) path=(.*)$")
COMPLETED = re.compile(r"\[DJ\] THINK completed(?: \(\w+\))?: duration=([\d.]+)ms intent_id=(\S+) is_terminal=(\S+)$")


@pytest.fixture
def dj_log(caplog):
    """Capture the DJ logger directly (it may not propagate to root)."""
    lg = logging.getLogger(DJ_LOGGER)
    attach = not lg.propagate  # the module drops propagation when its file log opens
    if attach:
        lg.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger=DJ_LOGGER)
    yield caplog
    if attach:
        lg.removeHandler(caplog.handler)


@pytest.fixture
def engine(fake_rotation_manager, fake_asset_discovery_manager, mock_tower_control):
    e = DJEngine(playout_engine=None, rotation_manager=fake_rotation_manager,
                 dj_asset_path="/fake/dj_path", tower_control=mock_tower_control)
    e.asset_manager = fake_asset_discovery_manager
    return e


def messages(caplog):
    return [r.getMessage() for r in caplog.records]


def matches(caplog, pattern):
    return [m for m in (pattern.search(msg) for msg in messages(caplog)) if m]


class TestDJ4_1_ThinkStarted:
    def test_dj4_1_logged_once_per_think_cycle(self, engine, dj_log):
        for path in ("/fake/song1.mp3", "/fake/song2.mp3"):
            dj_log.clear()
            engine.on_segment_started(create_fake_audio_event(path, "song"))
            found = matches(dj_log, STARTED)
            assert len(found) == 1
            assert found[0].group(1) == "song" and found[0].group(2) == path

    def test_dj4_1_logged_before_think_logic(self, engine, dj_log):
        engine.on_segment_started(create_fake_audio_event("/fake/current.mp3", "song"))
        msgs = messages(dj_log)
        started = next(i for i, m in enumerate(msgs) if STARTED.search(m))
        decide = next(i for i, m in enumerate(msgs) if "Deciding break structure" in m)
        assert started < decide


class TestDJ4_2_ThinkCompleted:
    def test_dj4_2_logged_once_after_started(self, engine, dj_log):
        engine.on_segment_started(create_fake_audio_event("/fake/current.mp3", "song"))
        msgs = messages(dj_log)
        started = [i for i, m in enumerate(msgs) if STARTED.search(m)]
        completed = [i for i, m in enumerate(msgs) if COMPLETED.search(m)]
        assert len(started) == 1 and len(completed) == 1
        assert started[0] < completed[0]

    def test_dj4_2_includes_duration_and_intent_id(self, engine, dj_log):
        engine.on_segment_started(create_fake_audio_event("/fake/current.mp3", "song"))
        (m,) = matches(dj_log, COMPLETED)
        assert float(m.group(1)) >= 0
        assert engine.current_intent is not None
        assert m.group(2) == str(engine.current_intent.intent_id)
        assert m.group(3) == "False"

    def test_dj4_2_logged_after_intent_committed(self, engine, dj_log):
        engine.on_segment_started(create_fake_audio_event("/fake/current.mp3", "song"))
        msgs = messages(dj_log)
        committed = next(i for i, m in enumerate(msgs) if "DJIntent committed" in m)
        completed = next(i for i, m in enumerate(msgs) if COMPLETED.search(m))
        assert committed < completed


class TestDJ4_StationLocalOnly:
    def test_dj4_no_think_for_non_song_segments(self, engine, dj_log):
        for kind in ("intro", "outro", "id"):
            engine.on_segment_started(create_fake_audio_event(f"/fake/{kind}.mp3", kind))
        assert not matches(dj_log, STARTED) and not matches(dj_log, COMPLETED)

    def test_dj4_not_logged_during_do(self, engine, dj_log):
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)
        dj_log.clear()
        engine.on_segment_finished(segment)
        assert not matches(dj_log, STARTED) and not matches(dj_log, COMPLETED)

    def test_dj4_never_sent_to_tower(self, engine, mock_tower_control):
        engine.on_segment_started(create_fake_audio_event("/fake/current.mp3", "song"))
        types = [c.kwargs.get("event_type") for c in mock_tower_control.send_event.call_args_list]
        assert "dj_think_started" not in types and "dj_think_completed" not in types
        assert types == [], f"THINK must not send events to Tower, sent: {types}"
