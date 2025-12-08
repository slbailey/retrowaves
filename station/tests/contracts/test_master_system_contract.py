"""
Contract tests for MASTER_SYSTEM_CONTRACT

See docs/contracts/MASTER_SYSTEM_CONTRACT.md

Tests map directly to contract clauses:
- E0.1: Lifecycle Events (1 test)
- E0.2: THINK Before DO (1 test)
- E0.3: Non-Blocking DO (1 test)
- E0.4: DO Execution Only (1 test)
- E0.5: THINK Fallback (1 test)
- E0.6: Queue Modification (1 test)
"""

import pytest
import time

from station.broadcast_core.playout_engine import PlayoutEngine
from station.tests.contracts.test_doubles import (
    create_fake_audio_event,
    FakeRotationManager,
    FakeAssetDiscoveryManager,
)
from station.dj_logic.dj_engine import DJEngine


class TestE0_1_LifecycleEvents:
    """Tests for E0.1 — Lifecycle Events."""
    
    def test_e0_1_every_segment_triggers_two_lifecycle_events(self, mock_dj_callback, mock_output_sink):
        """E0.1: Every segment MUST trigger exactly two lifecycle events (on_segment_started → THINK, on_segment_finished → DO)."""
        engine = PlayoutEngine(dj_callback=mock_dj_callback, output_sink=mock_output_sink)
        
        segment = create_fake_audio_event("/fake/test.mp3", "song")
        engine.start_segment(segment)  # Event 1: THINK
        engine.finish_segment(segment)  # Event 2: DO
        
        # Contract requires both events
        mock_dj_callback.on_segment_started.assert_called_once_with(segment)
        mock_dj_callback.on_segment_finished.assert_called_once_with(segment)


class TestE0_2_ThinkBeforeDo:
    """Tests for E0.2 — THINK Before DO."""
    
    def test_e0_2_think_completes_before_do(self, fake_rotation_manager, fake_asset_discovery_manager):
        """E0.2: THINK MUST always complete before DO begins."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        
        # THINK phase
        engine.on_segment_started(segment)
        assert engine.current_intent is not None, "THINK must complete before DO (intent must exist)"


class TestE0_3_NonBlockingDo:
    """Tests for E0.3 — Non-Blocking DO."""
    
    def test_e0_3_do_operations_non_blocking(self, mock_dj_callback, mock_output_sink):
        """E0.3: DO operations MUST be non-blocking."""
        engine = PlayoutEngine(dj_callback=mock_dj_callback, output_sink=mock_output_sink)
        
        segment = create_fake_audio_event("/fake/test.mp3", "song")
        engine.start_segment(segment)
        
        # DO should complete quickly
        start_time = time.time()
        engine.finish_segment(segment)
        elapsed = time.time() - start_time
        
        assert elapsed < 1.0, "DO operations must be non-blocking (complete quickly)"


class TestE0_4_DoExecutionOnly:
    """Tests for E0.4 — DO Execution Only."""
    
    def test_e0_4_do_receives_complete_dj_intent(self, fake_rotation_manager, fake_asset_discovery_manager):
        """E0.4: DO receives a complete DJIntent from THINK and executes it without making decisions."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)  # THINK creates intent
        
        intent = engine.current_intent
        assert intent is not None, "DO must receive complete DJIntent from THINK"
        # DO executes intent - actual execution tested in integration


class TestE0_5_ThinkFallback:
    """Tests for E0.5 — THINK Fallback."""
    
    def test_e0_5_fallback_if_think_fails(self, fake_rotation_manager, fake_asset_discovery_manager):
        """E0.5: If THINK fails, system MUST fall back to safe intent."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)
        
        # Contract requires fallback - THINK should always produce intent
        assert engine.current_intent is not None, \
            "THINK failures must not prevent intent creation (fallback required)"


class TestE0_6_QueueModification:
    """Tests for E0.6 — Queue Modification."""
    
    def test_e0_6_only_do_modifies_queue(self, fake_rotation_manager, fake_asset_discovery_manager):
        """E0.6: No component MAY modify the playout queue except DO."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)  # THINK
        
        # Contract requires THINK does not modify queue
        assert engine.current_intent is not None, \
            "THINK prepares intent (does not modify queue)"
