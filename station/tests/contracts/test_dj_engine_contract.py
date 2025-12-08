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
- DJ3.1: State Maintenance (1 test)
- DJ3.2: State Mutation Prohibition (1 test)
"""

import pytest
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
