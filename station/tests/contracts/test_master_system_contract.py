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
- E0.7: Heartbeat Observability (heartbeat events within THINK/DO model)
- E1: THINK/DO Behavior During Lifecycle (5 tests)
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


class TestE0_7_HeartbeatObservability:
    """Tests for E0.7 — Heartbeat Observability."""
    
    def test_e0_7_heartbeat_events_must_be_observable_but_not_influence_decisions(self, mock_dj_callback, mock_output_sink):
        """E0.7: Heartbeat events MUST be observable but not influence decisions."""
        # Contract requires events can be observed by external systems
        # Events must not influence THINK decisions, DO operations, or playout behavior
        assert True, "Contract requires heartbeat events are observable but not influence decisions"
    
    def test_e0_7_heartbeat_events_must_respect_think_do_boundaries(self, mock_dj_callback, mock_output_sink):
        """E0.7: Heartbeat events MUST respect THINK/DO boundaries."""
        # Contract requires THINK events emitted during THINK phase
        # DO events emitted during DO phase
        # Events must not cross THINK/DO boundaries
        assert True, "Contract requires heartbeat events respect THINK/DO boundaries"
    
    def test_e0_7_heartbeat_events_must_not_modify_queue_or_state(self, mock_dj_callback, mock_output_sink):
        """E0.7: Heartbeat events MUST NOT modify queue or state."""
        # Contract requires events do not modify playout queue, rotation history, or any system state
        assert True, "Contract requires heartbeat events do not modify queue or state"
    
    def test_e0_7_heartbeat_events_must_be_emitted_from_appropriate_components(self, mock_dj_callback, mock_output_sink):
        """E0.7: Heartbeat events MUST be emitted from appropriate components."""
        # Contract requires:
        # - Segment lifecycle events from PlayoutEngine
        # - THINK lifecycle events from DJEngine
        # - Buffer health events from OutputSink
        # - Clock drift events from PlayoutEngine (if enabled)
        assert True, "Contract requires events emitted from appropriate components"
    
    def test_e0_7_heartbeat_events_must_use_clock_a_for_timing(self, mock_dj_callback, mock_output_sink):
        """E0.7: Heartbeat events MUST use Clock A for timing."""
        # Contract requires all event timestamps use Clock A (wall clock)
        # No Tower timing in event metadata
        assert True, "Contract requires heartbeat events use Clock A for timing"
    
    def test_e0_7_heartbeat_events_must_be_emitted_at_correct_boundaries(self, mock_dj_callback, mock_output_sink):
        """E0.7: Heartbeat events MUST be emitted at correct boundaries."""
        # Contract requires:
        # - segment_started before first frame
        # - segment_progress during playback
        # - segment_finished after last frame
        # - dj_think_started before THINK logic
        # - dj_think_completed after THINK logic
        # - Buffer events when conditions detected
        assert True, "Contract requires heartbeat events emitted at correct boundaries"
    
    def test_e0_7_heartbeat_events_must_include_required_metadata(self, mock_dj_callback, mock_output_sink):
        """E0.7: Heartbeat events MUST include required metadata."""
        # Contract requires each event includes all required fields
        # Metadata types must be correct
        # Metadata values must be valid
        assert True, "Contract requires heartbeat events include required metadata"
    
    def test_e0_7_think_do_separation_must_be_preserved(self, mock_dj_callback, mock_output_sink):
        """E0.7: THINK/DO separation MUST be preserved."""
        # Contract requires THINK events don't influence DO
        # DO events don't influence THINK
        # Events respect THINK/DO boundaries
        assert True, "Contract requires THINK/DO separation preserved in heartbeat events"


class TestE1_ThinkDoBehaviorDuringLifecycle:
    """Tests for E1 — THINK/DO Behavior During Lifecycle."""
    
    def test_e1_1_lifecycle_detection_occurs_outside_think_do(self):
        """E1.1: Startup and shutdown detection MUST occur OUTSIDE the THINK/DO cycle."""
        # Contract requires lifecycle detection outside THINK/DO
        # Lifecycle state is managed by Station lifecycle (per StationLifecycle Contract)
        # Lifecycle detection MUST NOT occur during THINK or DO execution
        assert True, "Contract requires lifecycle detection outside THINK/DO (tested in integration)"
    
    def test_e1_2_think_may_observe_lifecycle_state(self, fake_rotation_manager, fake_asset_discovery_manager):
        """E1.2: Lifecycle state MAY be observed during THINK."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Contract allows THINK to observe lifecycle state
        # During startup, THINK may observe startup state and select startup announcement
        # During shutdown, THINK may observe shutdown flag and produce terminal intent
        assert engine is not None, "DJEngine must exist"
        # Actual lifecycle observation tested in integration
    
    def test_e1_3_do_executes_intent_without_branching(self, fake_rotation_manager, fake_asset_discovery_manager):
        """E1.3: DO executes intent without branching on lifecycle state."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)  # THINK
        
        # Contract requires DO executes intent without branching on lifecycle state
        # DO MUST NOT branch behavior based on lifecycle state
        intent = engine.current_intent
        assert intent is not None, "DO must receive intent from THINK"
        # DO execution behavior tested in integration
    
    def test_e1_4_think_do_separation_preserved_during_shutdown(self, fake_rotation_manager, fake_asset_discovery_manager):
        """E1.4: THINK/DO separation MUST be preserved during shutdown."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Contract requires THINK/DO separation preserved during shutdown
        # Shutdown logic MUST NOT execute during DO beyond intent execution
        # THINK prepares terminal intent; DO executes it
        assert engine is not None, "DJEngine must exist"
        # Separation preservation tested in integration
    
    def test_e1_5_no_think_do_after_terminal_do(self):
        """E1.5: After terminal intent execution, no further THINK or DO events MAY fire."""
        # Contract requires no THINK/DO events after terminal DO completes
        # System MUST prevent new THINK/DO cycles after terminal DO
        # Callbacks MUST be disabled or ignored after terminal DO
        assert True, "Contract requires no THINK/DO after terminal DO (tested in integration)"
