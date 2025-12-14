"""
Contract tests for OS3.1 and OS3.2 — Buffer Health Events

See docs/contracts/OUTPUT_SINK_CONTRACT.md

Tests map directly to contract clauses:
- OS3.1: station_underflow event
- OS3.2: station_overflow event

Required tests:
1. station_underflow emitted when buffer depth reaches zero
2. station_underflow emitted once per underflow transition
3. station_overflow emitted when frames are dropped
4. station_overflow includes buffer_depth and frames_dropped
5. Events do not alter buffer behavior
"""

import pytest
import time
import numpy as np
from unittest.mock import Mock, MagicMock

from station.outputs.tower_pcm_sink import TowerPCMSink
from station.tests.contracts.test_doubles import create_canonical_pcm_frame


class TestOS3_1_StationUnderflowEvent:
    """Tests for OS3.1 — Station Underflow Event."""
    
    def test_os3_1_underflow_emitted_when_buffer_depth_reaches_zero(self, mock_tower_control):
        """OS3.1: Event MUST be emitted when buffer depth reaches zero."""
        # Mock get_buffer to simulate transition from non-zero to zero
        buffer_states = [
            {"count": 10, "capacity": 50},  # Initial: non-zero
            {"count": 0, "capacity": 50},   # Transition: zero (underflow)
        ]
        buffer_state_index = [0]
        
        def mock_get_buffer():
            idx = buffer_state_index[0]
            if idx < len(buffer_states):
                result = buffer_states[idx]
                buffer_state_index[0] += 1
                return result
            return buffer_states[-1]  # Stay at last state
        
        mock_tower_control.get_buffer = Mock(side_effect=mock_get_buffer)
        mock_tower_control.send_event = Mock(return_value=True)
        
        # Create sink with mocked tower_control
        sink = TowerPCMSink(
            socket_path="/fake/socket",
            tower_control=mock_tower_control
        )
        
        # Force initial state tracking (set _last_buffer_depth to non-zero)
        # This simulates a previous buffer check where depth was 10
        sink._last_buffer_depth = 10
        
        # Simulate time passing to allow buffer check (rate limiting)
        sink._last_buffer_check_time = time.monotonic() - 0.2  # Force check
        
        # Directly call buffer health check (this is what write() calls internally)
        # First call will get buffer_depth=10 (no transition), second will get buffer_depth=0 (transition)
        sink._check_buffer_health()  # First check: depth=10, updates _last_buffer_depth to 10
        buffer_state_index[0] = 1  # Move to next state (depth=0)
        sink._last_buffer_check_time = time.monotonic() - 0.2  # Force another check
        sink._check_buffer_health()  # Second check: depth=0, detects transition from 10->0
        
        # Contract OS3.1: Event MUST be emitted when buffer depth reaches zero
        underflow_calls = [c for c in mock_tower_control.send_event.call_args_list 
                          if c[1].get("event_type") == "station_underflow"]
        assert len(underflow_calls) >= 1, "station_underflow event must be emitted when buffer depth reaches zero"
        
        # Verify event metadata
        call_args = underflow_calls[0]
        metadata = call_args[1].get("metadata", {})
        assert "buffer_depth" in metadata, "Event metadata must include buffer_depth"
        assert metadata["buffer_depth"] == 0, "buffer_depth must be 0 for underflow"
        assert "frames_dropped" in metadata, "Event metadata must include frames_dropped"
        
        # Contract OS3.1: Event MUST include timestamp
        assert "timestamp" in call_args[1], "Event must include timestamp"
        timestamp = call_args[1]["timestamp"]
        assert isinstance(timestamp, float), "Timestamp must be float (time.monotonic())"
        assert timestamp > 0, "Timestamp must be valid"
    
    def test_os3_1_underflow_emitted_once_per_transition(self, mock_tower_control):
        """OS3.1: Event MUST be emitted once per underflow transition (not continuously)."""
        # Mock buffer states: non-zero -> zero -> zero (should only emit once)
        buffer_states = [
            {"count": 5, "capacity": 50},   # Initial: non-zero
            {"count": 0, "capacity": 50},   # First zero (transition - should emit)
            {"count": 0, "capacity": 50},   # Still zero (no transition - should NOT emit again)
            {"count": 3, "capacity": 50},   # Back to non-zero
            {"count": 0, "capacity": 50},   # Back to zero (new transition - should emit again)
        ]
        buffer_state_index = [0]
        
        def mock_get_buffer():
            idx = buffer_state_index[0]
            if idx < len(buffer_states):
                result = buffer_states[idx]
                buffer_state_index[0] += 1
                return result
            return buffer_states[-1]
        
        mock_tower_control.get_buffer = Mock(side_effect=mock_get_buffer)
        mock_tower_control.send_event = Mock(return_value=True)
        
        sink = TowerPCMSink(
            socket_path="/fake/socket",
            tower_control=mock_tower_control
        )
        
        # Start with non-zero state
        sink._last_buffer_depth = 5
        sink._last_buffer_check_time = time.monotonic() - 0.2
        
        # First check: non-zero state (no transition)
        sink._last_buffer_check_time = time.monotonic() - 0.2
        sink._check_buffer_health()  # Gets count=5, updates state
        
        # Second check: transition to zero (should emit)
        buffer_state_index[0] = 1
        sink._last_buffer_check_time = time.monotonic() - 0.2
        sink._check_buffer_health()  # Gets count=0, detects transition 5->0
        
        # Third check: still zero (no transition, should NOT emit)
        buffer_state_index[0] = 2
        sink._last_buffer_check_time = time.monotonic() - 0.2
        sink._check_buffer_health()  # Gets count=0, no transition (already at 0)
        
        # Fourth check: back to non-zero
        buffer_state_index[0] = 3
        sink._last_buffer_check_time = time.monotonic() - 0.2
        sink._check_buffer_health()  # Gets count=3, updates state
        
        # Fifth check: transition back to zero (should emit)
        buffer_state_index[0] = 4
        sink._last_buffer_check_time = time.monotonic() - 0.2
        sink._check_buffer_health()  # Gets count=0, detects transition 3->0
        
        # Contract OS3.1: Event MUST be emitted once per transition
        underflow_calls = [c for c in mock_tower_control.send_event.call_args_list 
                          if c[1].get("event_type") == "station_underflow"]
        assert len(underflow_calls) == 2, "station_underflow must be emitted once per transition (should be 2 transitions: first zero, and second transition from non-zero back to zero)"


class TestOS3_2_StationOverflowEvent:
    """Tests for OS3.2 — Station Overflow Event."""
    
    def test_os3_2_overflow_emitted_when_frames_dropped(self, mock_tower_control):
        """OS3.2: Event MUST be emitted when frames are dropped (buffer at capacity)."""
        # Mock get_buffer to simulate transition to overflow (at capacity)
        buffer_states = [
            {"count": 45, "capacity": 50},  # Initial: below capacity
            {"count": 50, "capacity": 50},  # Transition: at capacity (overflow)
        ]
        buffer_state_index = [0]
        
        def mock_get_buffer():
            idx = buffer_state_index[0]
            if idx < len(buffer_states):
                result = buffer_states[idx]
                buffer_state_index[0] += 1
                return result
            return buffer_states[-1]
        
        mock_tower_control.get_buffer = Mock(side_effect=mock_get_buffer)
        mock_tower_control.send_event = Mock(return_value=True)
        
        sink = TowerPCMSink(
            socket_path="/fake/socket",
            tower_control=mock_tower_control
        )
        
        # Initialize state tracking for overflow transition
        sink._last_buffer_at_capacity = False
        sink._last_buffer_check_time = time.monotonic() - 0.2
        
        # First check: below capacity (no transition)
        sink._check_buffer_health()  # Gets count=45, updates state
        
        # Second check: transition to capacity (should emit)
        buffer_state_index[0] = 1
        sink._last_buffer_check_time = time.monotonic() - 0.2
        sink._check_buffer_health()  # Gets count=50, detects transition to capacity
        
        # Contract OS3.2: Event MUST be emitted when overflow occurs
        overflow_calls = [c for c in mock_tower_control.send_event.call_args_list 
                         if c[1].get("event_type") == "station_overflow"]
        assert len(overflow_calls) >= 1, "station_overflow event must be emitted when frames are dropped"
        
        # Verify event metadata
        call_args = overflow_calls[0]
        metadata = call_args[1].get("metadata", {})
        assert "buffer_depth" in metadata, "Event metadata must include buffer_depth"
        assert metadata["buffer_depth"] == 50, "buffer_depth must be at capacity for overflow"
        assert "frames_dropped" in metadata, "Event metadata must include frames_dropped"
        assert metadata["frames_dropped"] >= 1, "frames_dropped must be at least 1 when overflow occurs"
        
        # Contract OS3.2: Event MUST include timestamp
        assert "timestamp" in call_args[1], "Event must include timestamp"
        timestamp = call_args[1]["timestamp"]
        assert isinstance(timestamp, float), "Timestamp must be float (time.monotonic())"
        assert timestamp > 0, "Timestamp must be valid"
    
    def test_os3_2_overflow_includes_buffer_depth_and_frames_dropped(self, mock_tower_control):
        """OS3.2: Event metadata MUST include buffer_depth and frames_dropped."""
        # Mock buffer states: below capacity -> at capacity (overflow transition)
        buffer_states = [
            {"count": 95, "capacity": 100},  # Below capacity
            {"count": 100, "capacity": 100},  # At capacity (overflow)
        ]
        buffer_state_index = [0]
        
        def mock_get_buffer():
            idx = buffer_state_index[0]
            if idx < len(buffer_states):
                result = buffer_states[idx]
                buffer_state_index[0] += 1
                return result
            return buffer_states[-1]
        
        mock_tower_control.get_buffer = Mock(side_effect=mock_get_buffer)
        mock_tower_control.send_event = Mock(return_value=True)
        
        sink = TowerPCMSink(
            socket_path="/fake/socket",
            tower_control=mock_tower_control
        )
        
        # Initialize state tracking for overflow transition
        sink._last_buffer_at_capacity = False
        sink._last_buffer_check_time = time.monotonic() - 0.2
        
        # First check: below capacity (no transition)
        sink._check_buffer_health()  # Gets count=95, updates state
        
        # Second check: transition to capacity (should emit)
        buffer_state_index[0] = 1
        sink._last_buffer_check_time = time.monotonic() - 0.2
        sink._check_buffer_health()  # Gets count=100, detects transition to capacity
        
        # Contract OS3.2: Event metadata MUST include buffer_depth and frames_dropped
        overflow_calls = [c for c in mock_tower_control.send_event.call_args_list 
                         if c[1].get("event_type") == "station_overflow"]
        assert len(overflow_calls) >= 1, "station_overflow event must be emitted"
        
        call_args = overflow_calls[0]
        metadata = call_args[1].get("metadata", {})
        
        assert "buffer_depth" in metadata, "Event metadata must include buffer_depth"
        assert isinstance(metadata["buffer_depth"], int), "buffer_depth must be integer"
        assert metadata["buffer_depth"] > 0, "buffer_depth must be positive when at capacity"
        
        assert "frames_dropped" in metadata, "Event metadata must include frames_dropped"
        assert isinstance(metadata["frames_dropped"], (int, float)), "frames_dropped must be numeric"
        assert metadata["frames_dropped"] >= 1, "frames_dropped must be at least 1 when overflow occurs"


class TestOS3_EventsDoNotAlterBufferBehavior:
    """Tests that events do not alter buffer behavior."""
    
    def test_os3_events_do_not_alter_buffer_behavior(self, mock_tower_control):
        """OS3: Events MUST NOT alter buffer behavior or state."""
        # Mock buffer state
        mock_tower_control.get_buffer = Mock(return_value={"count": 25, "capacity": 50})
        mock_tower_control.send_event = Mock(return_value=True)
        
        sink = TowerPCMSink(
            socket_path="/fake/socket",
            tower_control=mock_tower_control
        )
        
        # Initialize state
        sink._last_buffer_depth = 25
        sink._last_buffer_at_capacity = False
        sink._last_buffer_check_time = time.monotonic() - 0.2
        
        # Capture initial buffer state
        initial_buffer_state = sink._last_buffer_depth
        
        # Directly call buffer health check (no transition expected)
        sink._check_buffer_health()
        
        # Contract OS3.3: Events MUST NOT alter buffer behavior
        # Verify that no events were emitted (no transition)
        all_events = [c[1].get("event_type") for c in mock_tower_control.send_event.call_args_list]
        buffer_events = [et for et in all_events if et in ("station_underflow", "station_overflow")]
        assert len(buffer_events) == 0, "No events should be emitted when no transition occurs"
        
        # Verify buffer state tracking is unchanged (events don't affect internal state)
        assert sink._last_buffer_depth == initial_buffer_state, "Events must not alter buffer state tracking"
        
        # Contract OS3.3: Events MUST NOT block PCM output
        # Buffer health check should complete immediately (non-blocking)
        start_time = time.monotonic()
        sink._check_buffer_health()
        elapsed = time.monotonic() - start_time
        assert elapsed < 0.1, "Event emission must not block buffer health check"

