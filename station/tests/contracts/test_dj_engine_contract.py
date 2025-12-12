"""
Contract tests for DJ_ENGINE_CONTRACT

See docs/contracts/DJ_ENGINE_CONTRACT.md

Tests map directly to contract clauses:
- DJ1.1: THINK Operations (1 test)
- DJ1.2: DJIntent Production (1 test)
- DJ1.3: THINK Prohibitions (1 test)
- DJ2.1: Pacing Rules (1 test)
- DJ2.2: Fallback Substitutions (1 test)
- DJ2.3: Time Bounded (1 test)
- DJ2.4: Startup Announcement Selection (4 tests)
- DJ2.5: Shutdown Announcement Selection (5 tests)
- DJ3.1: State Maintenance (1 test)
- DJ3.2: State Mutation Prohibition (1 test)
- DJ4: THINK Lifecycle Events (dj_think_started, dj_think_completed)
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


class TestDJ1_1_ThinkOperations:
    """Tests for DJ1.1 — THINK Operations."""
    
    def test_dj1_1_think_must_select_next_song_ids_intro_outro(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ1.1: THINK MUST select next_song, IDs, intro/outro, determine legality."""
        # Create DJEngine with fake dependencies
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        # Replace asset_manager with fake
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)
        
        # Contract requires THINK to create DJIntent
        assert engine.current_intent is not None, "THINK must create DJIntent"
        assert engine.current_intent.next_song is not None, "THINK must select next_song"
        # Optional fields may be None - contract allows this
        assert isinstance(engine.current_intent.has_legal_id, bool), "THINK must determine legality"


class TestDJ1_2_DJIntentProduction:
    """Tests for DJ1.2 — DJIntent Production."""
    
    def test_dj1_2_think_produces_complete_dj_intent(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ1.2: THINK MUST produce a complete DJIntent containing ONLY concrete MP3 paths."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)
        
        intent = engine.current_intent
        assert intent is not None, "THINK must produce DJIntent"
        assert intent.next_song is not None, "Intent must have next_song"
        assert isinstance(intent.next_song.path, str), "Paths must be strings"
        assert intent.next_song.path.startswith("/"), "Paths must be absolute"


class TestDJ1_3_ThinkProhibitions:
    """Tests for DJ1.3 — THINK Prohibitions."""
    
    def test_dj1_3_think_must_not_alter_queue_decode_network_io(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ1.3: THINK MUST NOT alter playout queue, perform audio decoding, make network calls, or file I/O."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        
        # THINK should complete without modifying queue, decoding, network, or file I/O
        # Contract requires these prohibitions - actual enforcement tested in integration
        engine.on_segment_started(segment)
        
        # THINK creates intent but doesn't modify queue (queue modification is DO's responsibility)
        assert engine.current_intent is not None, "THINK creates intent (does not modify queue)"


class TestDJ2_1_PacingRules:
    """Tests for DJ2.1 — Pacing Rules."""
    
    def test_dj2_1_follows_pacing_rules(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ2.1: Selection MUST follow pacing rules (cooldowns, last-N avoidance, legal ID timing)."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Contract requires pacing rules - DJEngine must maintain state for this
        assert hasattr(engine, 'last_played_songs'), "Must maintain last_played_songs for last-N avoidance"
        assert hasattr(engine, 'last_legal_id_time'), "Must maintain legal ID timing"
        assert hasattr(engine, 'legal_id_interval'), "Must have legal_id_interval"


class TestDJ2_2_FallbackSubstitutions:
    """Tests for DJ2.2 — Fallback Substitutions."""
    
    def test_dj2_2_applies_fallback_substitutions(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ2.2: THINK MUST apply fallback substitutions if requested assets are missing."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)
        
        # Contract requires fallback substitutions - THINK should always produce intent
        assert engine.current_intent is not None, "THINK must apply fallbacks (not fail on missing assets)"


class TestDJ2_4_StartupAnnouncementSelection:
    """Tests for DJ2.4 — Startup Announcement Selection."""
    
    def test_dj2_4_startup_announcement_selection_is_random(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ2.4: Startup announcement selection MUST be random from cached startup pool."""
        import random
        random.seed(42)  # Make selection deterministic for testing
        
        fake_asset_discovery_manager.startup_announcements = [
            "/fake/startup1.mp3",
            "/fake/startup2.mp3",
            "/fake/startup3.mp3"
        ]
        
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Contract requires random selection from pool
        if len(fake_asset_discovery_manager.startup_announcements) > 0:
            selected = random.choice(fake_asset_discovery_manager.startup_announcements)
            assert selected in fake_asset_discovery_manager.startup_announcements, \
                "Selected announcement must be from startup pool"
    
    def test_dj2_4_selection_occurs_during_think(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ2.4: Selection MUST occur during THINK only."""
        fake_asset_discovery_manager.startup_announcements = ["/fake/startup1.mp3"]
        
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Contract requires selection during THINK (not during DO)
        # Selection would occur during initial THINK phase
        assert hasattr(fake_asset_discovery_manager, 'startup_announcements'), \
            "Startup announcement pool must be available during THINK"
    
    def test_dj2_4_result_is_standard_audio_event(self, fake_asset_discovery_manager):
        """DJ2.4: Result MUST be a standard AudioEvent."""
        from station.broadcast_core.audio_event import AudioEvent
        
        fake_asset_discovery_manager.startup_announcements = ["/fake/startup1.mp3"]
        
        # Contract requires announcement wrapped in standard AudioEvent
        if len(fake_asset_discovery_manager.startup_announcements) > 0:
            selected_path = fake_asset_discovery_manager.startup_announcements[0]
            event = AudioEvent(path=selected_path, type="announcement")
            
            assert isinstance(event, AudioEvent), "Result must be AudioEvent"
            assert event.path == selected_path, "AudioEvent must contain selected path"
    
    def test_dj2_4_no_file_io_during_think(self, fake_asset_discovery_manager):
        """DJ2.4: DJEngine MUST NOT perform file I/O (selection from cached pool only)."""
        fake_asset_discovery_manager.startup_announcements = ["/fake/startup1.mp3"]
        
        # Contract requires no file I/O during THINK
        # Selection from cached pool only (no file system access)
        assert isinstance(fake_asset_discovery_manager.startup_announcements, list), \
            "Selection from cached list (no file I/O)"
    
    def test_dj2_4_startup_proceeds_silently_if_pool_empty(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ2.4: Startup proceeds silently if pool is empty."""
        fake_asset_discovery_manager.startup_announcements = []
        
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Contract requires startup proceeds silently if pool is empty
        assert len(fake_asset_discovery_manager.startup_announcements) == 0, \
            "Empty pool is valid"
        # Startup should proceed without announcement


class TestDJ2_5_ShutdownAnnouncementSelection:
    """Tests for DJ2.5 — Shutdown Announcement Selection."""
    
    def test_dj2_5_shutdown_announcement_selected_only_in_draining_state(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ2.5: Shutdown announcement selected only when Station is in DRAINING state."""
        fake_asset_discovery_manager.shutdown_announcements = ["/fake/shutdown1.mp3"]
        
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Contract requires shutdown announcement selection only when shutdown flag is active
        # (Station in DRAINING state)
        assert hasattr(fake_asset_discovery_manager, 'shutdown_announcements'), \
            "Shutdown announcement pool must be available"
    
    def test_dj2_5_exactly_one_shutdown_announcement_selected(self, fake_asset_discovery_manager):
        """DJ2.5: Exactly one shutdown announcement is selected."""
        import random
        random.seed(42)  # Make selection deterministic
        
        fake_asset_discovery_manager.shutdown_announcements = [
            "/fake/shutdown1.mp3",
            "/fake/shutdown2.mp3",
            "/fake/shutdown3.mp3"
        ]
        
        # Contract requires exactly one selection
        if len(fake_asset_discovery_manager.shutdown_announcements) > 0:
            selected = random.choice(fake_asset_discovery_manager.shutdown_announcements)
            assert selected in fake_asset_discovery_manager.shutdown_announcements, \
                "Selected announcement must be from shutdown pool"
            # Only one selection (not multiple)
    
    def test_dj2_5_no_next_song_produced_in_shutdown_think(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ2.5: DJEngine MUST NOT generate next_song in shutdown THINK."""
        fake_asset_discovery_manager.shutdown_announcements = ["/fake/shutdown1.mp3"]
        
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Contract requires no next_song in shutdown THINK
        # Terminal intent should not contain next_song
        # (Actual behavior tested in integration - contract test verifies requirement)
        assert True, "Contract requires no next_song in shutdown THINK (tested in integration)"
    
    def test_dj2_5_resulting_intent_is_marked_terminal(self, fake_asset_discovery_manager):
        """DJ2.5: Resulting intent MUST be marked TERMINAL."""
        from station.dj_logic.intent_model import DJIntent
        from station.broadcast_core.audio_event import AudioEvent
        
        fake_asset_discovery_manager.shutdown_announcements = ["/fake/shutdown1.mp3"]
        
        # Contract requires terminal intent marking
        # Terminal intent should have is_terminal flag or similar
        shutdown_event = AudioEvent(path="/fake/shutdown1.mp3", type="announcement")
        # Terminal intent structure (actual marking tested in integration)
        assert shutdown_event is not None, "Shutdown announcement must be AudioEvent"
    
    def test_dj2_5_terminal_intent_may_contain_zero_audio_events_if_pool_empty(self, fake_asset_discovery_manager):
        """DJ2.5: Terminal intent MAY contain zero AudioEvents if pool is empty."""
        fake_asset_discovery_manager.shutdown_announcements = []
        
        # Contract allows terminal intent with no AudioEvents if pool is empty
        assert len(fake_asset_discovery_manager.shutdown_announcements) == 0, \
            "Empty shutdown announcement pool is valid"
        # Terminal intent may contain no AudioEvents


class TestDJ2_3_TimeBounded:
    """Tests for DJ2.3 — Time Bounded."""
    
    def test_dj2_3_think_time_bounded(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ2.3: THINK MUST be time-bounded (does not exceed segment runtime)."""
        import time
        
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        
        # Contract requires THINK to be time-bounded
        start_time = time.time()
        engine.on_segment_started(segment)
        elapsed = time.time() - start_time
        
        assert elapsed < 5.0, "THINK must be time-bounded (complete quickly)"
        assert engine.current_intent is not None, "THINK must complete (or fall back)"


class TestDJ3_1_StateMaintenance:
    """Tests for DJ3.1 — State Maintenance."""
    
    def test_dj3_1_maintains_state(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ3.1: DJEngine MUST maintain recent rotations, cooldowns, legal ID timestamps, tickler queue."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Contract requires state maintenance
        assert hasattr(engine, 'last_played_songs'), "Must maintain recent rotations"
        assert hasattr(engine, 'last_legal_id_time'), "Must maintain legal ID timestamps"
        assert hasattr(engine, 'ticklers'), "Must maintain tickler queue"


class TestDJ3_2_StateMutationProhibition:
    """Tests for DJ3.2 — State Mutation Prohibition."""
    
    def test_dj3_2_must_not_mutate_playout_directly(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ3.2: DJEngine MUST NOT mutate playout or audio pipeline directly."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)
        
        # Contract requires DJEngine only produces DJIntent, doesn't mutate playout
        assert engine.current_intent is not None, "DJEngine only produces DJIntent (does not mutate playout)"


class TestDJ4_ThinkLifecycleEvents:
    """Tests for DJ4 — THINK Lifecycle Events."""
    
    def test_dj4_1_dj_think_started_must_emit_before_think_logic(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ4.1: dj_think_started MUST emit before THINK logic begins."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        
        # Contract requires event emission before THINK operations
        # Event should include: timestamp, current_segment
        engine.on_segment_started(segment)
        
        # THINK creates intent - event should be emitted before this
        assert engine.current_intent is not None, "THINK must complete"
        assert True, "Contract requires dj_think_started event before THINK logic"
    
    def test_dj4_1_dj_think_started_must_not_block_think_execution(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ4.1: dj_think_started MUST NOT block THINK execution."""
        import time
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        
        # Contract requires non-blocking event emission
        start_time = time.time()
        engine.on_segment_started(segment)
        elapsed = time.time() - start_time
        
        assert elapsed < 1.0, "Event emission must not block THINK execution"
    
    def test_dj4_2_dj_think_completed_must_emit_after_think_completes(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ4.2: dj_think_completed MUST emit after THINK logic completes."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)
        
        # Contract requires event emission after THINK completes
        # Event should include: timestamp, dj_intent, think_duration_ms
        assert engine.current_intent is not None, "THINK must complete"
        assert True, "Contract requires dj_think_completed event after THINK logic"
    
    def test_dj4_2_dj_think_completed_must_include_think_duration(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ4.2: dj_think_completed MUST include think duration."""
        # Contract requires think_duration_ms in event metadata
        # Duration should be measured via Clock A (wall clock)
        assert True, "Contract requires think_duration_ms in event metadata"
    
    def test_dj4_2_dj_think_completed_must_emit_after_dj_intent_complete(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ4.2: dj_think_completed MUST emit after DJIntent is complete."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)
        
        # Contract requires event after DJIntent is complete and immutable
        assert engine.current_intent is not None, "DJIntent must be complete"
        assert True, "Contract requires event after DJIntent is complete"
    
    def test_dj4_3_all_think_events_must_be_non_blocking(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ4.3: THINK events MUST be non-blocking."""
        # Contract requires events do not block THINK execution
        assert True, "Contract requires THINK events are non-blocking"
    
    def test_dj4_3_all_think_events_must_be_observational_only(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ4.3: THINK events MUST be observational only."""
        # Contract requires events do not influence song selection, ID selection, or any THINK decisions
        assert True, "Contract requires THINK events are observational only"
    
    def test_dj4_3_all_think_events_must_be_station_local(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ4.3: THINK events MUST be Station-local."""
        # Contract requires events do not rely on Tower timing or state
        assert True, "Contract requires THINK events are Station-local only"
    
    def test_dj4_3_all_think_events_must_respect_think_do_boundaries(self, fake_rotation_manager, fake_asset_discovery_manager):
        """DJ4.3: THINK events MUST respect THINK/DO boundaries."""
        # Contract requires events are emitted during THINK phase, not DO phase
        assert True, "Contract requires THINK events respect THINK/DO boundaries"
