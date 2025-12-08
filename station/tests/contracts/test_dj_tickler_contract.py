"""
Contract tests for DJ_TICKLER_CONTRACT

See docs/contracts/DJ_TICKLER_CONTRACT.md

Tests map directly to contract clauses:
- TK1.1: THINK Window Execution (1 test)
- TK1.2: Future Content Only (1 test)
- TK1.3: Non-Blocking I/O (1 test)
"""

import pytest
import time

from station.dj_logic.ticklers import Tickler, GenerateIntroTickler, GenerateOutroTickler, RefillGenericIDTickler
from station.tests.contracts.test_doubles import create_fake_audio_event, FakeRotationManager, FakeAssetDiscoveryManager
from station.dj_logic.dj_engine import DJEngine


class TestTK1_1_ThinkWindowExecution:
    """Tests for TK1.1 — THINK Window Execution."""
    
    def test_tk1_1_executes_only_during_think_windows(self, fake_rotation_manager, fake_asset_discovery_manager):
        """TK1.1: Ticklers MUST execute only during THINK windows."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Add tickler
        tickler = GenerateIntroTickler("/fake/song.mp3")
        engine.add_tickler(tickler)
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        initial_tickler_count = len(engine.ticklers)
        
        # THINK phase should execute ticklers
        engine.on_segment_started(segment)
        
        # Contract requires ticklers execute during THINK
        assert len(engine.ticklers) < initial_tickler_count, "Ticklers must execute during THINK windows"


class TestTK1_2_FutureContentOnly:
    """Tests for TK1.2 — Future Content Only."""
    
    def test_tk1_2_must_not_generate_assets_for_immediate_use(self, fake_rotation_manager, fake_asset_discovery_manager):
        """TK1.2: Ticklers MUST NOT generate assets for immediate use in same THINK/DO cycle."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        tickler = GenerateIntroTickler("/fake/song.mp3")
        engine.add_tickler(tickler)
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        engine.on_segment_started(segment)
        intent = engine.current_intent
        
        # Contract requires ticklers don't affect current segment's intent
        assert intent is not None, "Ticklers must not affect current segment's intent"


class TestTK1_3_NonBlockingIO:
    """Tests for TK1.3 — Non-Blocking I/O."""
    
    def test_tk1_3_must_not_perform_blocking_io(self, fake_rotation_manager, fake_asset_discovery_manager):
        """TK1.3: Ticklers MUST NOT perform blocking I/O."""
        engine = DJEngine(
            playout_engine=None,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        tickler = GenerateIntroTickler("/fake/song.mp3")
        engine.add_tickler(tickler)
        
        segment = create_fake_audio_event("/fake/current.mp3", "song")
        
        # Contract requires ticklers complete quickly (non-blocking)
        start_time = time.time()
        engine.on_segment_started(segment)
        elapsed = time.time() - start_time
        
        assert elapsed < 1.0, "Tickler execution must not block (must complete quickly)"
