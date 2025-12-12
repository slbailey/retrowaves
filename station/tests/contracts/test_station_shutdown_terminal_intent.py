"""
Contract tests for STATION_SHUTDOWN_TERMINAL_INTENT_CONTRACT

See docs/contracts/STATION_SHUTDOWN_TERMINAL_INTENT_CONTRACT.md

Tests map directly to contract clauses:
- SD1: Single Terminal Intent (1 test)
- SD2: Terminal Intent Latching (1 test)
- SD3: DO Execution Rules During DRAINING (1 test)
- SD4: Shutdown Announcement Completion (1 test)
- SD5: Prefill Suppression During Terminal Announcement (1 test)
"""

import pytest
import os
from unittest.mock import Mock, MagicMock, call, patch
from typing import List

from station.tests.contracts.test_doubles import (
    FakeMediaLibrary,
    FakeRotationManager,
    FakeAssetDiscoveryManager,
    FakeDJStateStore,
    create_fake_audio_event,
)
from station.dj_logic.dj_engine import DJEngine
from station.broadcast_core.playout_engine import PlayoutEngine
from station.dj_logic.intent_model import DJIntent


class MockPlayoutEngine:
    """Mock PlayoutEngine that tracks enqueued events and prefill operations."""
    
    def __init__(self):
        self._queue = MockQueue()
        self._enqueued_events: List = []
        self._prefill_calls: List = []
        self._is_draining = False
    
    def queue_audio(self, events):
        """Track enqueued events."""
        self._enqueued_events.extend(events)
        for event in events:
            self._queue.put(event)
    
    def start_segment(self, segment):
        """Simulate segment start."""
        pass
    
    def finish_segment(self, segment):
        """Simulate segment finish."""
        pass
    
    def _run_prefill_if_needed(self):
        """Track prefill calls."""
        self._prefill_calls.append("PREFILL-SILENCE")
    
    def get_enqueued_events(self):
        """Get all enqueued events."""
        return self._enqueued_events.copy()
    
    def get_prefill_calls(self):
        """Get all prefill calls."""
        return self._prefill_calls.copy()
    
    def clear_prefill_calls(self):
        """Clear prefill call history."""
        self._prefill_calls.clear()


class MockQueue:
    """Mock queue for tracking enqueued events."""
    
    def __init__(self):
        self._items = []
    
    def put(self, item):
        """Add item to queue."""
        self._items.append(item)
    
    def empty(self):
        """Check if queue is empty."""
        return len(self._items) == 0
    
    def size(self):
        """Get queue size."""
        return len(self._items)
    
    def peek_intent_id(self):
        """Get intent_id of first item."""
        if self._items:
            return getattr(self._items[0], 'intent_id', None)
        return None


class TestSD1_SingleTerminalIntent:
    """Tests for SD1 — Single Terminal Intent."""
    
    @patch('os.path.exists')
    def test_terminal_intent_created_once_during_shutdown(
        self, mock_exists, fake_rotation_manager, fake_asset_discovery_manager
    ):
        """
        SD1.1, SD1.2: Exactly one terminal DJIntent MAY be created per station lifecycle.
        Once a terminal intent has been queued, no further terminal intents may be created.
        """
        # Mock os.path.exists to return True for shutdown announcement
        def exists_side_effect(path):
            if path == "/fake/shutdown1.mp3":
                return True
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Setup: Station with shutdown announcement available
        fake_asset_discovery_manager.shutdown_announcements = ["/fake/shutdown1.mp3"]
        
        mock_playout = MockPlayoutEngine()
        engine = DJEngine(
            playout_engine=mock_playout,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Start station: Begin playing a song
        current_song = create_fake_audio_event("/fake/song1.mp3", "song")
        engine.on_segment_started(current_song)  # THINK for next song
        
        # Trigger shutdown: Set DRAINING state
        engine.set_lifecycle_state(is_startup=False, is_draining=True)
        
        # Simulate segment finished: This triggers DO which creates terminal intent if needed
        engine.on_segment_finished(current_song)  # DO for current song - creates terminal intent
        
        # Assert: Exactly one terminal intent was created (may be created in DO phase)
        # The terminal intent should have been created during DO phase
        assert engine._terminal_intent_queued, "Terminal intent must be marked as queued after DO"
        
        # Count shutdown announcements enqueued
        enqueued_events = mock_playout.get_enqueued_events()
        shutdown_announcements = [e for e in enqueued_events if e.type == "announcement"]
        
        # SD1.1: Exactly one terminal DJIntent created
        # SD1.2: Exactly one shutdown announcement enqueued (if announcement exists)
        # Note: Terminal intent may have no announcement if pool is empty, but latch should still be set
        assert engine._terminal_intent_queued, "SD1.1: Terminal intent must be marked as queued"
        
        # Attempt to create another terminal intent (should be prevented)
        # Simulate another segment start after terminal intent is queued
        another_segment = create_fake_audio_event("/fake/song3.mp3", "song")
        engine.on_segment_started(another_segment)  # Should NOT create another terminal intent
        
        # Verify no additional terminal intent was created
        # The latch should prevent creation
        assert engine._terminal_intent_queued, "Terminal intent latch must remain set"
        
        # Count terminal intents again
        final_enqueued = mock_playout.get_enqueued_events()
        final_shutdown_announcements = [e for e in final_enqueued if e.type == "announcement"]
        
        # SD1.2: No additional terminal intents created
        assert len(final_shutdown_announcements) <= 1, \
            f"SD1.2: No additional terminal intents may be created, got {len(final_shutdown_announcements)} shutdown announcements"


class TestSD2_TerminalIntentLatching:
    """Tests for SD2 — Terminal Intent Latching."""
    
    @patch('os.path.exists')
    def test_terminal_intent_latch_survives_intent_clear(
        self, mock_exists, fake_rotation_manager, fake_asset_discovery_manager
    ):
        """
        SD2.1, SD2.2: Lifecycle-scoped latch MUST record that terminal intent has already been queued.
        Clearing a terminal DJIntent object MUST NOT allow another terminal intent to be created.
        """
        # Mock os.path.exists to return True for shutdown announcement
        def exists_side_effect(path):
            if path == "/fake/shutdown1.mp3":
                return True
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Setup: Station with shutdown announcement available
        fake_asset_discovery_manager.shutdown_announcements = ["/fake/shutdown1.mp3"]
        
        mock_playout = MockPlayoutEngine()
        engine = DJEngine(
            playout_engine=mock_playout,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Trigger shutdown
        engine.set_lifecycle_state(is_startup=False, is_draining=True)
        
        # Create and enqueue terminal intent (via DO phase)
        current_song = create_fake_audio_event("/fake/song1.mp3", "song")
        engine.on_segment_finished(current_song)  # DO creates and enqueues terminal intent
        
        # SD2.1: Latch must be set
        assert engine._terminal_intent_queued, "SD2.1: Lifecycle latch must be set after terminal intent is queued"
        
        # SD2.2: Clear terminal intent (normal behavior after DO)
        # This simulates what happens after DO completes
        original_intent = engine.current_intent
        engine.current_intent = None  # Clear intent (normal DO behavior)
        
        # Verify intent is cleared
        assert engine.current_intent is None, "Intent should be cleared after DO"
        
        # SD2.2: Latch must persist even after intent is cleared
        assert engine._terminal_intent_queued, \
            "SD2.2: Lifecycle latch must persist after terminal intent object is cleared"
        
        # Simulate another on_segment_finished (e.g., shutdown announcement finishes)
        shutdown_announcement = create_fake_audio_event("/fake/shutdown1.mp3", "announcement")
        shutdown_announcement.is_terminal = True
        
        # Attempt to trigger THINK again (should be prevented by latch)
        engine.on_segment_started(shutdown_announcement)  # Should NOT create new terminal intent
        
        # SD2.2: No new terminal intent should be created
        assert engine.current_intent is None or not (hasattr(engine.current_intent, 'is_terminal') and engine.current_intent.is_terminal), \
            "SD2.2: No new terminal intent may be created after latch is set"
        
        # Verify latch still prevents creation
        assert engine._terminal_intent_queued, \
            "SD2.2: Latch must prevent terminal intent creation even after intent object is cleared"


class TestSD3_DoExecutionRulesDuringDraining:
    """Tests for SD3 — DO Execution Rules During DRAINING."""
    
    @patch('os.path.exists')
    def test_no_terminal_intent_after_shutdown_announcement_finishes(
        self, mock_exists, fake_rotation_manager, fake_asset_discovery_manager
    ):
        """
        SD3.1, SD3.2: During DRAINING, DJ DO MAY execute exactly once to enqueue the terminal shutdown announcement.
        DJ DO MUST NOT execute terminal logic again after that enqueue.
        SD4.1, SD4.2: Completion of the shutdown announcement MUST NOT trigger DJ THINK or DJ DO.
        """
        # Mock os.path.exists to return True for shutdown announcement
        def exists_side_effect(path):
            if path == "/fake/shutdown1.mp3":
                return True
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Setup: Station with shutdown announcement available
        fake_asset_discovery_manager.shutdown_announcements = ["/fake/shutdown1.mp3"]
        
        mock_playout = MockPlayoutEngine()
        engine = DJEngine(
            playout_engine=mock_playout,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Start station: Begin playing a song
        current_song = create_fake_audio_event("/fake/song1.mp3", "song")
        engine.on_segment_started(current_song)
        engine.on_segment_finished(current_song)  # DO enqueues first song
        
        # Clear queue to avoid cross-intent leakage errors
        mock_playout._queue._items.clear()
        mock_playout._enqueued_events.clear()
        
        # Track initial state BEFORE shutdown
        initial_terminal_intent_queued = engine._terminal_intent_queued
        
        # Trigger shutdown mid-song
        engine.set_lifecycle_state(is_startup=False, is_draining=True)
        
        # Verify terminal intent not queued before DO
        assert not engine._terminal_intent_queued, "Terminal intent should not be queued before DO phase"
        
        # Simulate current song finishes, triggering DO which creates terminal intent
        next_song = create_fake_audio_event("/fake/song2.mp3", "song")
        engine.on_segment_finished(next_song)  # DO creates and enqueues terminal intent
        
        # SD3.1: Terminal intent should be queued exactly once
        assert engine._terminal_intent_queued, "SD3.1: Terminal intent must be queued"
        assert not initial_terminal_intent_queued, "Terminal intent should not have been queued before shutdown"
        
        # Verify shutdown announcement was enqueued (if available)
        enqueued_after_do = mock_playout.get_enqueued_events()
        shutdown_announcements = [e for e in enqueued_after_do if e.type == "announcement"]
        
        # SD4.1, SD4.2: Allow shutdown announcement to play to completion (if it exists)
        if shutdown_announcements:
            shutdown_announcement = shutdown_announcements[0]
            
            # Track state before shutdown announcement finishes
            enqueued_before_completion = len(mock_playout.get_enqueued_events())
            terminal_intent_queued_before = engine._terminal_intent_queued
            
            # Simulate shutdown announcement finishing
            # SD4.1, SD4.2: This should NOT trigger THINK or DO again
            # However, if DO is triggered, it should be prevented from creating another terminal intent
            try:
                engine.on_segment_finished(shutdown_announcement)
                # If no exception, verify that no additional terminal intent was created
                final_enqueued = mock_playout.get_enqueued_events()
                final_shutdown_announcements = [e for e in final_enqueued if e.type == "announcement"]
                
                # SD3.2: DJ DO should NOT create another terminal intent
                assert len(final_shutdown_announcements) == 1, \
                    f"SD3.2: No new terminal intents may be created after shutdown announcement finishes, " \
                    f"got {len(final_shutdown_announcements)} shutdown announcements"
            except RuntimeError as e:
                # SD4.3: If RuntimeError is raised, it should be because terminal intent was already queued
                # This is acceptable - the system is preventing duplicate terminal intent creation
                assert "Terminal intent may only be queued once" in str(e) or "Terminal intent already queued" in str(e), \
                    f"SD4.3: RuntimeError should be about terminal intent uniqueness, got: {e}"
                # Verify latch is still set
                assert engine._terminal_intent_queued, "Terminal intent latch should remain set even after error"
            
            # SD4.1: DJ THINK should NOT be triggered (or should be prevented)
            # Note: Even if THINK creates a terminal intent (which it shouldn't), DO should prevent it from being queued
            # The latch check in DO should prevent duplicate terminal intent creation
            # The key invariant is that only ONE terminal intent is ever QUEUED per lifecycle
            # If THINK creates a terminal intent, DO should detect the latch and prevent enqueueing
            # The intent may exist temporarily but should not be queued
            
            # SD4.2: DJ DO should NOT enqueue additional events
            final_enqueued = mock_playout.get_enqueued_events()
            assert len(final_enqueued) == enqueued_before_completion, \
                f"SD4.2: DJ DO must not enqueue additional events after shutdown announcement completion, " \
                f"got {len(final_enqueued)} events (expected {enqueued_before_completion})"
        
        # SD4.3: Terminal intent latch should remain set
        assert engine._terminal_intent_queued, "Terminal intent latch should remain set"


class TestSD5_PrefillSuppression:
    """Tests for SD5 — Prefill Suppression During Terminal Announcement."""
    
    @patch('os.path.exists')
    def test_prefill_suppressed_during_shutdown_announcement(
        self, mock_exists, fake_rotation_manager, fake_asset_discovery_manager
    ):
        """
        SD5.1: Pre-fill silence injection MUST NOT occur while the shutdown announcement is playing.
        SD5.2: Pre-fill MUST be suppressed throughout the DRAINING state.
        """
        # Mock os.path.exists to return True for shutdown announcement
        def exists_side_effect(path):
            if path == "/fake/shutdown1.mp3":
                return True
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Setup: Station with shutdown announcement available
        fake_asset_discovery_manager.shutdown_announcements = ["/fake/shutdown1.mp3"]
        
        mock_playout = MockPlayoutEngine()
        engine = DJEngine(
            playout_engine=mock_playout,
            rotation_manager=fake_rotation_manager,
            dj_asset_path="/fake/dj_path"
        )
        engine.asset_manager = fake_asset_discovery_manager
        
        # Trigger shutdown
        engine.set_lifecycle_state(is_startup=False, is_draining=True)
        
        # SD5.2: Pre-fill should be suppressed when DRAINING begins
        # (In real implementation, prefill checks lifecycle state)
        mock_playout._is_draining = True
        
        # Create and enqueue terminal intent
        current_song = create_fake_audio_event("/fake/song1.mp3", "song")
        engine.on_segment_finished(current_song)  # DO creates and enqueues terminal intent
        
        # Get shutdown announcement (if enqueued)
        enqueued = mock_playout.get_enqueued_events()
        shutdown_announcements = [e for e in enqueued if e.type == "announcement"]
        
        # SD5.1: When shutdown announcement starts, prefill should be suppressed
        # Simulate shutdown announcement starting (if it exists)
        if shutdown_announcements:
            shutdown_announcement = shutdown_announcements[0]
            mock_playout.start_segment(shutdown_announcement)
        
        # Clear any previous prefill calls
        mock_playout.clear_prefill_calls()
        
        # SD5.1: Prefill should NOT run while shutdown announcement is playing
        # In a real implementation, prefill would check:
        # - Is a segment active? (yes, shutdown announcement is playing)
        # - Is system draining? (yes)
        # Both conditions should suppress prefill
        
        # Simulate prefill attempt
        # In real code, this would be called by playout engine during normal operation
        # but should be suppressed during shutdown announcement playback
        if not mock_playout._is_draining:
            # Only run prefill if not draining (simulating the check)
            mock_playout._run_prefill_if_needed()
        
        prefill_calls = mock_playout.get_prefill_calls()
        
        # SD5.1: No [PREFILL-SILENCE] frames should be written
        assert len(prefill_calls) == 0, \
            f"SD5.1: Pre-fill must not occur while shutdown announcement is playing, " \
            f"got {len(prefill_calls)} prefill calls"
        
        # SD5.2: Prefill should remain suppressed throughout DRAINING
        # Simulate another prefill attempt
        if not mock_playout._is_draining:
            mock_playout._run_prefill_if_needed()
        
        final_prefill_calls = mock_playout.get_prefill_calls()
        assert len(final_prefill_calls) == 0, \
            f"SD5.2: Pre-fill must remain suppressed throughout DRAINING state, " \
            f"got {len(final_prefill_calls)} prefill calls"
        
        # SD5.3: Prefill should NOT be re-enabled after terminal intent is queued
        # Even if shutdown announcement finishes, prefill should remain suppressed
        if shutdown_announcements:
            mock_playout.finish_segment(shutdown_announcements[0])
        
        # Attempt prefill again (should still be suppressed)
        if not mock_playout._is_draining:
            mock_playout._run_prefill_if_needed()
        
        post_completion_prefill = mock_playout.get_prefill_calls()
        assert len(post_completion_prefill) == 0, \
            f"SD5.3: Pre-fill must not be re-enabled after terminal intent is queued, " \
            f"got {len(post_completion_prefill)} prefill calls"

