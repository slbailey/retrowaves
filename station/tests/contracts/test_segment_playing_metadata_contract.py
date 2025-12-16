"""
Contract tests for segment_playing event metadata enforcement

See EVENT_INVENTORY.md and NEW_TOWER_RUNTIME_CONTRACT.md

PHASE 2: Tests only - these tests MUST FAIL until Phase 3 implementation.

Tests enforce that segment_playing events MUST include required metadata:
- segment_class (required)
- segment_role (required)
- production_type (required)

All tests must fail until implementation is updated.
"""

import pytest
import time
from unittest.mock import Mock

from station.broadcast_core.playout_engine import PlayoutEngine
from station.tests.contracts.test_doubles import create_fake_audio_event


class TestSegmentPlayingMetadataEnforcement:
    """Tests for segment_playing event metadata enforcement."""
    
    def test_sp1_segment_playing_must_include_segment_class(self, mock_dj_callback, mock_output_sink, mock_tower_control):
        """
        SP.1: segment_playing events MUST include segment_class metadata.
        
        Per EVENT_INVENTORY.md:
        - segment_playing MUST include required metadata: segment_class, segment_role, production_type
        - Missing segment_class MUST cause event emission to fail
        """
        engine = PlayoutEngine(dj_callback=mock_dj_callback, output_sink=mock_output_sink, tower_control=mock_tower_control)
        
        # Create a non-song segment (should emit segment_playing)
        segment = create_fake_audio_event("/fake/talk.mp3", "talk")
        
        # NOTE: This test will FAIL until Phase 3 implementation
        # Expected failure: segment_playing event not emitted, or emitted without segment_class
        engine.start_segment(segment)
        
        # Verify segment_playing event was emitted
        assert mock_tower_control.send_event.called, \
            "Contract violation: segment_playing event must be emitted for non-song segments"
        
        # Find segment_playing event call
        segment_playing_calls = [call for call in mock_tower_control.send_event.call_args_list 
                                 if call[1].get("event_type") == "segment_playing"]
        assert len(segment_playing_calls) > 0, \
            "Contract violation: segment_playing event must be emitted"
        
        # Verify segment_class is present in metadata
        call_args = segment_playing_calls[0]
        metadata = call_args[1].get("metadata", {})
        assert "segment_class" in metadata, \
            "Contract violation [EVENT_INVENTORY]: segment_playing MUST include segment_class metadata"
        assert metadata["segment_class"] is not None, \
            "Contract violation [EVENT_INVENTORY]: segment_class must not be None"
    
    def test_sp2_segment_playing_must_include_segment_role(self, mock_dj_callback, mock_output_sink, mock_tower_control):
        """
        SP.2: segment_playing events MUST include segment_role metadata.
        
        Per EVENT_INVENTORY.md:
        - segment_playing MUST include required metadata: segment_class, segment_role, production_type
        - Missing segment_role MUST cause event emission to fail
        """
        engine = PlayoutEngine(dj_callback=mock_dj_callback, output_sink=mock_output_sink, tower_control=mock_tower_control)
        
        # Create a non-song segment
        segment = create_fake_audio_event("/fake/talk.mp3", "talk")
        
        # NOTE: This test will FAIL until Phase 3 implementation
        engine.start_segment(segment)
        
        # Verify segment_playing event was emitted with segment_role
        segment_playing_calls = [call for call in mock_tower_control.send_event.call_args_list 
                                 if call[1].get("event_type") == "segment_playing"]
        assert len(segment_playing_calls) > 0, \
            "Contract violation: segment_playing event must be emitted"
        
        call_args = segment_playing_calls[0]
        metadata = call_args[1].get("metadata", {})
        assert "segment_role" in metadata, \
            "Contract violation [EVENT_INVENTORY]: segment_playing MUST include segment_role metadata"
        assert metadata["segment_role"] is not None, \
            "Contract violation [EVENT_INVENTORY]: segment_role must not be None"
    
    def test_sp3_segment_playing_must_include_production_type(self, mock_dj_callback, mock_output_sink, mock_tower_control):
        """
        SP.3: segment_playing events MUST include production_type metadata.
        
        Per EVENT_INVENTORY.md:
        - segment_playing MUST include required metadata: segment_class, segment_role, production_type
        - Missing production_type MUST cause event emission to fail
        """
        engine = PlayoutEngine(dj_callback=mock_dj_callback, output_sink=mock_output_sink, tower_control=mock_tower_control)
        
        # Create a non-song segment
        segment = create_fake_audio_event("/fake/talk.mp3", "talk")
        
        # NOTE: This test will FAIL until Phase 3 implementation
        engine.start_segment(segment)
        
        # Verify segment_playing event was emitted with production_type
        segment_playing_calls = [call for call in mock_tower_control.send_event.call_args_list 
                                 if call[1].get("event_type") == "segment_playing"]
        assert len(segment_playing_calls) > 0, \
            "Contract violation: segment_playing event must be emitted"
        
        call_args = segment_playing_calls[0]
        metadata = call_args[1].get("metadata", {})
        assert "production_type" in metadata, \
            "Contract violation [EVENT_INVENTORY]: segment_playing MUST include production_type metadata"
        assert metadata["production_type"] is not None, \
            "Contract violation [EVENT_INVENTORY]: production_type must not be None"
    
    def test_sp4_segment_playing_must_include_all_required_metadata(self, mock_dj_callback, mock_output_sink, mock_tower_control):
        """
        SP.4: segment_playing events MUST include all required metadata fields.
        
        Per EVENT_INVENTORY.md:
        - segment_playing MUST include: segment_class, segment_role, production_type
        - All three fields MUST be present and non-null
        """
        engine = PlayoutEngine(dj_callback=mock_dj_callback, output_sink=mock_output_sink, tower_control=mock_tower_control)
        
        # Create a non-song segment
        segment = create_fake_audio_event("/fake/talk.mp3", "talk")
        
        # NOTE: This test will FAIL until Phase 3 implementation
        engine.start_segment(segment)
        
        # Verify segment_playing event was emitted with all required metadata
        segment_playing_calls = [call for call in mock_tower_control.send_event.call_args_list 
                                 if call[1].get("event_type") == "segment_playing"]
        assert len(segment_playing_calls) > 0, \
            "Contract violation: segment_playing event must be emitted"
        
        call_args = segment_playing_calls[0]
        metadata = call_args[1].get("metadata", {})
        
        # All three required fields must be present
        assert "segment_class" in metadata, \
            "Contract violation [EVENT_INVENTORY]: segment_playing MUST include segment_class"
        assert "segment_role" in metadata, \
            "Contract violation [EVENT_INVENTORY]: segment_playing MUST include segment_role"
        assert "production_type" in metadata, \
            "Contract violation [EVENT_INVENTORY]: segment_playing MUST include production_type"
        
        # All three must be non-null
        assert metadata["segment_class"] is not None, \
            "Contract violation [EVENT_INVENTORY]: segment_class must not be None"
        assert metadata["segment_role"] is not None, \
            "Contract violation [EVENT_INVENTORY]: segment_role must not be None"
        assert metadata["production_type"] is not None, \
            "Contract violation [EVENT_INVENTORY]: production_type must not be None"
    
    def test_sp5_segment_playing_must_not_emit_dj_talking(self, mock_dj_callback, mock_output_sink, mock_tower_control):
        """
        SP.5: segment_playing MUST be emitted instead of dj_talking for non-song segments.
        
        Per EVENT_INVENTORY.md:
        - dj_talking is COMPLETELY DEPRECATED
        - segment_playing MUST be emitted for all non-song segments
        - dj_talking MUST NOT be emitted
        """
        engine = PlayoutEngine(dj_callback=mock_dj_callback, output_sink=mock_output_sink, tower_control=mock_tower_control)
        
        # Create a non-song segment (previously would have emitted dj_talking)
        segment = create_fake_audio_event("/fake/talk.mp3", "talk")
        
        # NOTE: This test will FAIL until Phase 3 implementation
        # Expected failure: dj_talking event is still emitted instead of segment_playing
        engine.start_segment(segment)
        
        # Verify segment_playing was emitted
        segment_playing_calls = [call for call in mock_tower_control.send_event.call_args_list 
                                 if call[1].get("event_type") == "segment_playing"]
        assert len(segment_playing_calls) > 0, \
            "Contract violation: segment_playing must be emitted for non-song segments"
        
        # Verify dj_talking was NOT emitted
        dj_talking_calls = [call for call in mock_tower_control.send_event.call_args_list 
                           if call[1].get("event_type") == "dj_talking"]
        assert len(dj_talking_calls) == 0, \
            "Contract violation [EVENT_INVENTORY]: dj_talking MUST NOT be emitted (use segment_playing instead)"

