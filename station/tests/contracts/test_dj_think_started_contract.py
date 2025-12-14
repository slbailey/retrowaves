"""
Contract tests for DJ4.1 — dj_think_started event emission

See docs/contracts/DJ_ENGINE_CONTRACT.md

Tests map directly to contract clause DJ4.1:
- Test 1: Event is emitted when THINK phase begins
- Test 2: Event is emitted exactly once per THINK cycle
- Test 3: Event is emitted before DO phase begins
- Test 4: Event metadata includes current_segment
- Test 5: Event does NOT persist state or emit a clear event
"""

import pytest
import time
from unittest.mock import Mock, call

from station.dj_logic.dj_engine import DJEngine
from station.tests.contracts.test_doubles import (
    FakeRotationManager,
    FakeAssetDiscoveryManager,
    create_fake_audio_event,
)


class TestDJ4_1_ThinkStartedEvent:
    """Tests for DJ4.1 — THINK Started Event."""
    
    def test_dj4_1_event_emitted_when_think_phase_begins(self, fake_rotation_manager, fake_asset_discovery_manager, mock_tower_control):
        """DJ4.1: Event MUST be emitted when THINK phase begins."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path",
            tower_control=mock_tower_control
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        
        # Trigger THINK phase
        engine.on_segment_started(segment)
        
        # Contract DJ4.1: Event MUST be emitted when THINK phase begins
        assert mock_tower_control.send_event.called, "dj_think_started event must be emitted when THINK phase begins"
        
        # Verify event type
        calls = [c for c in mock_tower_control.send_event.call_args_list 
                if c[1].get("event_type") == "dj_think_started"]
        assert len(calls) >= 1, "dj_think_started event must be emitted"
    
    def test_dj4_1_event_emitted_exactly_once_per_think_cycle(self, fake_rotation_manager, fake_asset_discovery_manager, mock_tower_control):
        """DJ4.1: Event MUST be emitted exactly once per THINK cycle."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path",
            tower_control=mock_tower_control
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment1 = create_fake_audio_event("/fake/song1.mp3", "song")
        segment2 = create_fake_audio_event("/fake/song2.mp3", "song")
        
        # First THINK cycle
        mock_tower_control.reset_mock()
        engine.on_segment_started(segment1)
        
        # Count dj_think_started events
        think_started_calls = [c for c in mock_tower_control.send_event.call_args_list 
                              if c[1].get("event_type") == "dj_think_started"]
        assert len(think_started_calls) == 1, "dj_think_started must be emitted exactly once per THINK cycle"
        
        # Second THINK cycle
        mock_tower_control.reset_mock()
        engine.on_segment_started(segment2)
        
        # Count dj_think_started events in second cycle
        think_started_calls = [c for c in mock_tower_control.send_event.call_args_list 
                              if c[1].get("event_type") == "dj_think_started"]
        assert len(think_started_calls) == 1, "dj_think_started must be emitted exactly once per THINK cycle"
    
    def test_dj4_1_event_emitted_before_do_phase_begins(self, fake_rotation_manager, fake_asset_discovery_manager, mock_tower_control):
        """DJ4.1: Event MUST be emitted before DO phase begins (i.e., before dj_think_completed)."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path",
            tower_control=mock_tower_control
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        
        # Trigger THINK phase
        engine.on_segment_started(segment)
        
        # Contract DJ4.1: Event MUST be emitted before THINK completes (before DO phase)
        # Contract DJ4.2: dj_think_completed is emitted after THINK logic completes
        # Therefore, dj_think_started must come before dj_think_completed
        
        all_calls = mock_tower_control.send_event.call_args_list
        think_started_index = None
        think_completed_index = None
        
        for i, call_args in enumerate(all_calls):
            event_type = call_args[1].get("event_type")
            if event_type == "dj_think_started":
                think_started_index = i
            elif event_type == "dj_think_completed":
                think_completed_index = i
        
        assert think_started_index is not None, "dj_think_started must be emitted"
        assert think_completed_index is not None, "dj_think_completed must be emitted (to verify ordering)"
        assert think_started_index < think_completed_index, "dj_think_started must be emitted before dj_think_completed (i.e., before DO phase)"
    
    def test_dj4_1_event_metadata_includes_current_segment(self, fake_rotation_manager, fake_asset_discovery_manager, mock_tower_control):
        """DJ4.1: Event metadata MUST include current_segment."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path",
            tower_control=mock_tower_control
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/test_song.mp3", "song")
        
        # Trigger THINK phase
        engine.on_segment_started(segment)
        
        # Contract DJ4.1: Event metadata MUST include current_segment
        think_started_calls = [c for c in mock_tower_control.send_event.call_args_list 
                              if c[1].get("event_type") == "dj_think_started"]
        assert len(think_started_calls) >= 1, "dj_think_started event must be emitted"
        
        call_args = think_started_calls[0]
        metadata = call_args[1].get("metadata", {})
        
        assert "current_segment" in metadata, "Event metadata must include current_segment"
        current_segment = metadata["current_segment"]
        assert isinstance(current_segment, dict), "current_segment must be a dictionary"
        assert "type" in current_segment, "current_segment must include type"
        assert "path" in current_segment, "current_segment must include path"
        assert current_segment["type"] == segment.type, "current_segment.type must match segment type"
        assert current_segment["path"] == segment.path, "current_segment.path must match segment path"
        
        # Contract DJ4.1: Event MUST include timestamp
        assert "timestamp" in call_args[1], "Event must include timestamp"
        timestamp = call_args[1]["timestamp"]
        assert isinstance(timestamp, float), "Timestamp must be float (time.monotonic())"
        assert timestamp > 0, "Timestamp must be valid"
    
    def test_dj4_1_event_does_not_persist_state_or_emit_clear_event(self, fake_rotation_manager, fake_asset_discovery_manager, mock_tower_control):
        """DJ4.1: Event MUST NOT persist state or emit a clear event."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path",
            tower_control=mock_tower_control
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        
        # Capture initial state
        initial_intent = engine.current_intent
        
        # Trigger THINK phase
        engine.on_segment_started(segment)
        
        # Contract DJ4.1: Event MUST NOT modify queue or state
        # Event emission should not change engine state beyond normal THINK operations
        # We verify that only expected events are emitted (no "clear" or state persistence events)
        
        all_calls = mock_tower_control.send_event.call_args_list
        event_types = [c[1].get("event_type") for c in all_calls]
        
        # Contract DJ4.1: Event MUST NOT emit clear events or state persistence events
        # Only lifecycle events (dj_think_started, dj_think_completed) should be emitted
        allowed_event_types = {"dj_think_started", "dj_think_completed"}
        for event_type in event_types:
            assert event_type in allowed_event_types, \
                f"dj_think_started must not trigger unexpected events like '{event_type}'"
        
        # Verify no "clear" events
        clear_events = [et for et in event_types if "clear" in et.lower()]
        assert len(clear_events) == 0, "dj_think_started must not emit clear events"
        
        # State changes are allowed as part of normal THINK (creating intent), but
        # the event itself must not trigger additional state persistence events
        # The intent creation is part of THINK logic, not the event emission

