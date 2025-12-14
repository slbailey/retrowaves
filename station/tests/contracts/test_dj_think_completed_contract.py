"""
Contract tests for DJ4.2 — dj_think_completed event emission

See docs/contracts/DJ_ENGINE_CONTRACT.md

Tests map directly to contract clause DJ4.2:
- Test 1: Event is emitted after THINK logic completes
- Test 2: Event is emitted exactly once per THINK cycle
- Test 3: Event metadata includes think_duration_ms
- Test 4: dj_intent is included if available, otherwise null/omitted
- Test 5: Event is NOT emitted during DO phase
"""

import pytest
import time
from unittest.mock import Mock

from station.dj_logic.dj_engine import DJEngine
from station.tests.contracts.test_doubles import (
    FakeRotationManager,
    FakeAssetDiscoveryManager,
    create_fake_audio_event,
)


class TestDJ4_2_ThinkCompletedEvent:
    """Tests for DJ4.2 — THINK Completed Event."""
    
    def test_dj4_2_event_emitted_after_think_logic_completes(self, fake_rotation_manager, fake_asset_discovery_manager, mock_tower_control):
        """DJ4.2: Event MUST be emitted after THINK logic completes."""
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
        
        # Contract DJ4.2: Event MUST be emitted after THINK logic completes
        assert mock_tower_control.send_event.called, "dj_think_completed event must be emitted after THINK logic completes"
        
        # Verify event type
        calls = [c for c in mock_tower_control.send_event.call_args_list 
                if c[1].get("event_type") == "dj_think_completed"]
        assert len(calls) >= 1, "dj_think_completed event must be emitted after THINK logic completes"
        
        # Contract DJ4.2: Event MUST be emitted after dj_think_started
        all_calls = mock_tower_control.send_event.call_args_list
        think_started_index = None
        think_completed_index = None
        
        for i, call_args in enumerate(all_calls):
            event_type = call_args[1].get("event_type")
            if event_type == "dj_think_started":
                think_started_index = i
            elif event_type == "dj_think_completed":
                think_completed_index = i
        
        assert think_started_index is not None, "dj_think_started must be emitted first"
        assert think_completed_index is not None, "dj_think_completed must be emitted"
        assert think_started_index < think_completed_index, "dj_think_completed must be emitted after dj_think_started (i.e., after THINK logic completes)"
    
    def test_dj4_2_event_emitted_exactly_once_per_think_cycle(self, fake_rotation_manager, fake_asset_discovery_manager, mock_tower_control):
        """DJ4.2: Event MUST be emitted exactly once per THINK cycle."""
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
        
        # Count dj_think_completed events
        think_completed_calls = [c for c in mock_tower_control.send_event.call_args_list 
                                if c[1].get("event_type") == "dj_think_completed"]
        assert len(think_completed_calls) == 1, "dj_think_completed must be emitted exactly once per THINK cycle"
        
        # Second THINK cycle
        mock_tower_control.reset_mock()
        engine.on_segment_started(segment2)
        
        # Count dj_think_completed events in second cycle
        think_completed_calls = [c for c in mock_tower_control.send_event.call_args_list 
                                if c[1].get("event_type") == "dj_think_completed"]
        assert len(think_completed_calls) == 1, "dj_think_completed must be emitted exactly once per THINK cycle"
    
    def test_dj4_2_event_metadata_includes_think_duration_ms(self, fake_rotation_manager, fake_asset_discovery_manager, mock_tower_control):
        """DJ4.2: Event metadata MUST include think_duration_ms."""
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
        
        # Contract DJ4.2: Event metadata MUST include think_duration_ms
        think_completed_calls = [c for c in mock_tower_control.send_event.call_args_list 
                                if c[1].get("event_type") == "dj_think_completed"]
        assert len(think_completed_calls) >= 1, "dj_think_completed event must be emitted"
        
        call_args = think_completed_calls[0]
        metadata = call_args[1].get("metadata", {})
        
        assert "think_duration_ms" in metadata, "Event metadata must include think_duration_ms"
        think_duration_ms = metadata["think_duration_ms"]
        assert isinstance(think_duration_ms, (int, float)), "think_duration_ms must be numeric"
        assert think_duration_ms >= 0, "think_duration_ms must be non-negative (duration measurement)"
        
        # Contract DJ4.2: Event MUST include timestamp
        assert "timestamp" in call_args[1], "Event must include timestamp"
        timestamp = call_args[1]["timestamp"]
        assert isinstance(timestamp, float), "Timestamp must be float (time.monotonic())"
        assert timestamp > 0, "Timestamp must be valid"
    
    def test_dj4_2_dj_intent_included_if_available_otherwise_null(self, fake_rotation_manager, fake_asset_discovery_manager, mock_tower_control):
        """DJ4.2: dj_intent is included if available, otherwise null/omitted."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path",
            tower_control=mock_tower_control
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/test_song.mp3", "song")
        
        # Trigger THINK phase (should create intent)
        engine.on_segment_started(segment)
        
        # Contract DJ4.2: dj_intent is included if available
        think_completed_calls = [c for c in mock_tower_control.send_event.call_args_list 
                                if c[1].get("event_type") == "dj_think_completed"]
        assert len(think_completed_calls) >= 1, "dj_think_completed event must be emitted"
        
        call_args = think_completed_calls[0]
        metadata = call_args[1].get("metadata", {})
        
        # dj_intent may be None or a dict with intent_id and is_terminal
        assert "dj_intent" in metadata, "Event metadata must include dj_intent field"
        dj_intent = metadata["dj_intent"]
        
        if dj_intent is not None:
            # If dj_intent is present, it must be a dict with intent_id and is_terminal
            assert isinstance(dj_intent, dict), "dj_intent must be a dictionary if not None"
            assert "intent_id" in dj_intent, "dj_intent must include intent_id if present"
            assert "is_terminal" in dj_intent, "dj_intent must include is_terminal if present"
            # intent_id may be None or a string, is_terminal may be None or bool
            # Both are optional fields per contract
        
        # Verify that when an intent exists, it's included
        if engine.current_intent is not None:
            # Intent was created, so dj_intent should be present (may have None values)
            assert dj_intent is not None, "dj_intent should be included when intent exists"
    
    def test_dj4_2_event_not_emitted_during_do_phase(self, fake_rotation_manager, fake_asset_discovery_manager, mock_tower_control):
        """DJ4.2: Event MUST NOT be emitted during DO phase."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path",
            tower_control=mock_tower_control
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        
        # Trigger THINK phase (dj_think_completed should be emitted here)
        engine.on_segment_started(segment)
        
        # Verify event was emitted during THINK
        think_completed_calls_during_think = [c for c in mock_tower_control.send_event.call_args_list 
                                             if c[1].get("event_type") == "dj_think_completed"]
        assert len(think_completed_calls_during_think) >= 1, "dj_think_completed should be emitted during THINK phase"
        
        # Reset mock to track DO phase emissions
        mock_tower_control.reset_mock()
        
        # Trigger DO phase (on_segment_finished)
        engine.on_segment_finished(segment)
        
        # Contract DJ4.2: Event MUST NOT be emitted during DO phase
        think_completed_calls_during_do = [c for c in mock_tower_control.send_event.call_args_list 
                                          if c[1].get("event_type") == "dj_think_completed"]
        assert len(think_completed_calls_during_do) == 0, "dj_think_completed must NOT be emitted during DO phase"
