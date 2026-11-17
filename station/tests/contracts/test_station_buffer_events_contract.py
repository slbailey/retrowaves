"""
Contract tests for OS3.1 and OS3.2 — Buffer Health Events (Station-local)

See docs/contracts/OUTPUT_SINK_CONTRACT.md

Since Phase 3 (segment_playing architecture) buffer health events are
Station-local observability: they are written to the station log, and are
NOT sent to Tower (Tower accepts only the four events in EVENT_INVENTORY.md
and rejects anything else).

Tests:
1. underflow is logged when buffer depth goes from non-zero to zero
2. underflow is logged once per transition, not continuously
3. overflow is logged when the buffer reaches capacity, once per transition
4. log lines carry buffer_depth and frames_dropped
5. neither event is ever sent to Tower
6. events do not alter buffer behavior
"""

import logging
import time
from unittest.mock import Mock

import pytest

from station.outputs.tower_pcm_sink import TowerPCMSink

SINK_LOGGER = "station.outputs.tower_pcm_sink"


@pytest.fixture
def sink_log(caplog):
    """Capture the sink logger directly (it may not propagate to root)."""
    lg = logging.getLogger(SINK_LOGGER)
    attach = not lg.propagate  # the module drops propagation when its file log opens
    if attach:
        lg.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger=SINK_LOGGER)
    yield caplog
    if attach:
        lg.removeHandler(caplog.handler)


def make_sink(mock_tower_control, depths, capacity=50):
    states = [{"count": d, "capacity": capacity} for d in depths]
    mock_tower_control.get_buffer = Mock(side_effect=states)
    mock_tower_control.send_event = Mock(return_value=True)
    sink = TowerPCMSink(socket_path="/fake/socket", tower_control=mock_tower_control)
    return sink


def run_checks(sink, n):
    for _ in range(n):
        sink._last_buffer_check_time = time.monotonic() - 10  # bypass rate limit
        sink._check_buffer_health()


def lines(caplog, word):
    return [r.getMessage() for r in caplog.records if f"[BUFFER] {word} detected" in r.getMessage()]


def sent_types(mock_tower_control):
    return [c.kwargs.get("event_type") for c in mock_tower_control.send_event.call_args_list]


class TestOS3_1_StationUnderflowEvent:
    def test_os3_1_underflow_logged_when_buffer_depth_reaches_zero(self, mock_tower_control, sink_log):
        sink = make_sink(mock_tower_control, [10, 0])
        run_checks(sink, 2)
        found = lines(sink_log, "Underflow")
        assert len(found) == 1
        assert "buffer_depth=0" in found[0] and "frames_dropped=" in found[0]
        assert all(r.levelno == logging.WARNING for r in sink_log.records if "Underflow" in r.getMessage())

    def test_os3_1_underflow_logged_once_per_transition(self, mock_tower_control, sink_log):
        sink = make_sink(mock_tower_control, [5, 0, 0, 3, 0])
        run_checks(sink, 5)
        assert len(lines(sink_log, "Underflow")) == 2

    def test_os3_1_no_underflow_without_prior_nonzero_depth(self, mock_tower_control, sink_log):
        sink = make_sink(mock_tower_control, [0, 0])
        run_checks(sink, 2)
        assert lines(sink_log, "Underflow") == []


class TestOS3_2_StationOverflowEvent:
    def test_os3_2_overflow_logged_when_buffer_reaches_capacity(self, mock_tower_control, sink_log):
        sink = make_sink(mock_tower_control, [40, 50])
        run_checks(sink, 2)
        found = lines(sink_log, "Overflow")
        assert len(found) == 1
        assert "buffer_depth=50" in found[0] and "frames_dropped=" in found[0]

    def test_os3_2_overflow_logged_once_per_transition(self, mock_tower_control, sink_log):
        sink = make_sink(mock_tower_control, [40, 50, 50, 30, 50])
        run_checks(sink, 5)
        assert len(lines(sink_log, "Overflow")) == 2


class TestOS3_3_StationLocalOnly:
    def test_os3_buffer_events_never_sent_to_tower(self, mock_tower_control, sink_log):
        sink = make_sink(mock_tower_control, [5, 0, 50, 0, 50])
        run_checks(sink, 5)
        assert lines(sink_log, "Underflow") and lines(sink_log, "Overflow")
        types = sent_types(mock_tower_control)
        assert "station_underflow" not in types and "station_overflow" not in types

    def test_os3_events_do_not_alter_buffer_behavior(self, mock_tower_control):
        sink = make_sink(mock_tower_control, [5, 0])
        initial = len(sink._buffer)
        run_checks(sink, 2)
        assert len(sink._buffer) == initial
        assert sink._last_buffer_depth == 0

    def test_os3_buffer_check_failure_is_silent(self, mock_tower_control):
        mock_tower_control.get_buffer = Mock(side_effect=OSError("tower down"))
        sink = TowerPCMSink(socket_path="/fake/socket", tower_control=mock_tower_control)
        run_checks(sink, 1)  # must not raise
