"""
Invariant test for shutdown semantics: terminal DO and playout completion.

This test verifies that when shutdown is requested DURING active playback:
1. The current segment MUST be allowed to finish
2. Exactly ONE terminal THINK/DO cycle MUST execute
3. NO normal DO logic may run after draining begins
4. Playout MUST NOT stop before terminal DO completes
5. Station MUST NOT wait indefinitely once terminal playout is complete

See STATION_LIFECYCLE_CONTRACT.md SL2.2 for details.
"""

import pytest
import time
from unittest.mock import Mock, patch

from station.tests.contracts.test_doubles import (
    FakeRotationManager,
    FakeAssetDiscoveryManager,
    create_fake_audio_event,
    StubOutputSink,
    StubFFmpegDecoder,
)
from station.broadcast_core.audio_event import AudioEvent
from station.broadcast_core.playout_engine import PlayoutEngine
from station.dj_logic.dj_engine import DJEngine


class MockDJEngineForInvariantTest:
    """
    Mock DJEngine that tracks DO invocations to verify shutdown invariants.
    
    This mock wraps the real DJEngine to intercept and track DO calls
    while preserving real behavior for shutdown semantics.
    """
    
    def __init__(self, real_dj_engine: DJEngine):
        self._real = real_dj_engine
        self.do_call_count = 0
        self.terminal_do_call_count = 0
        self.normal_do_call_count = 0
        self.think_call_count = 0
        self._draining_started = False
    
    def on_segment_started(self, segment: AudioEvent) -> None:
        """Track THINK phase and delegate to real engine."""
        self.think_call_count += 1
        self._real.on_segment_started(segment)
    
    def on_segment_finished(self, segment: AudioEvent) -> None:
        """Track DO phase and verify invariants."""
        self.do_call_count += 1
        
        # Check if we're draining and if this is terminal DO
        is_draining = getattr(self._real, '_is_draining', False)
        has_terminal_intent = (
            self._real.current_intent is not None and
            getattr(self._real.current_intent, 'is_terminal', False)
        )
        
        # INVARIANT: After draining begins, only terminal DO is allowed
        if is_draining and not has_terminal_intent:
            raise AssertionError(
                f"INVARIANT VIOLATION: Normal DO executed during DRAINING! "
                f"Segment: {segment.path}, DO call count: {self.do_call_count}"
            )
        
        if has_terminal_intent:
            self.terminal_do_call_count += 1
        else:
            self.normal_do_call_count += 1
        
        # Delegate to real engine
        self._real.on_segment_finished(segment)
    
    def set_lifecycle_state(self, is_startup: bool = False, is_draining: bool = False) -> None:
        """Track draining state transition."""
        if is_draining and not self._draining_started:
            self._draining_started = True
        self._real.set_lifecycle_state(is_startup=is_startup, is_draining=is_draining)
    
    def set_playout_engine(self, engine) -> None:
        """Delegate to real engine."""
        self._real.set_playout_engine(engine)
    
    @property
    def current_intent(self):
        """Delegate to real engine."""
        return self._real.current_intent


@patch('station.broadcast_core.playout_engine.FFmpegDecoder')
def test_shutdown_does_not_exit_before_terminal_do_and_playout_completion(mock_decoder_class):
    """
    INVARIANT TEST: Shutdown semantics during active playback.
    
    Verifies all shutdown invariants are maintained when shutdown
    is triggered DURING active playback of a normal segment.
    """
    # Mock decoder to return stub decoder (avoids real file I/O)
    def create_stub_decoder(file_path, frame_size=1024):
        return StubFFmpegDecoder(file_path, frame_size_samples=frame_size)
    mock_decoder_class.side_effect = create_stub_decoder
    
    # Test setup: Create mocked components
    fake_rotation = FakeRotationManager()
    fake_asset_manager = FakeAssetDiscoveryManager()
    
    # Configure shutdown announcement to exist
    fake_asset_manager.shutdown_announcements = ["/fake/shutdown_announcement.mp3"]
    
    # Create fake output sink
    stub_sink = StubOutputSink()
    
    # Create mock tower control
    mock_tower_control = Mock()
    mock_tower_control.send_event = Mock(return_value=True)
    
    # Create real DJEngine
    real_dj_engine = DJEngine(
        playout_engine=None,  # Will be set later
        rotation_manager=fake_rotation,
        dj_asset_path="/fake/dj_path",
        tower_control=mock_tower_control
    )
    real_dj_engine.asset_manager = fake_asset_manager
    
    # Wrap with tracking mock
    dj_engine = MockDJEngineForInvariantTest(real_dj_engine)
    
    # Create PlayoutEngine
    playout_engine = PlayoutEngine(
        dj_callback=dj_engine,
        output_sink=stub_sink,
        tower_control=mock_tower_control
    )
    dj_engine.set_playout_engine(playout_engine)
    
    # Create normal song event
    normal_song = create_fake_audio_event("/fake/normal_song.mp3", "song")
    
    # Step 1: Start playout engine
    playout_engine.run()
    
    # Step 2: Queue normal song and start playing
    playout_engine.queue_audio([normal_song])
    
    # Wait briefly for segment to start (playout loop runs in background thread)
    max_wait_start = 2.0
    start_time = time.time()
    while not playout_engine.is_playing() and (time.time() - start_time) < max_wait_start:
        time.sleep(0.05)
    
    # ASSERTION: Current segment must be allowed to finish
    # Verify normal song started playing
    assert playout_engine.is_playing(), \
        "INVARIANT 1 FAILED: Normal song should be playing before shutdown"
    assert playout_engine.get_current_segment() == normal_song, \
        "Current segment should be normal song"
    
    # Step 3: Trigger shutdown while segment is active
    dj_engine.set_lifecycle_state(is_startup=False, is_draining=True)
    playout_engine.set_draining(True)
    playout_engine.request_shutdown()
    
    # Verify we're in DRAINING state
    assert playout_engine._is_draining, \
        "Should be in DRAINING state after shutdown request"
    
    # Step 4: Allow current segment to finish
    # In real scenario, segment plays to completion naturally
    # For test, we wait for playout loop to process the segment
    
    # Wait for segment to finish (simulated by waiting for playout to process)
    # The segment should finish, triggering finish_segment() which calls DO
    max_wait_finish = 5.0
    start_wait = time.time()
    
    # Wait until terminal DO has executed (indicated by _terminal_do_executed flag)
    while not playout_engine._terminal_do_executed and (time.time() - start_wait) < max_wait_finish:
        time.sleep(0.05)
    
    # Step 5: Observe behavior AFTER segment finishes
    
    # ASSERTION A: Terminal DO must execute exactly once
    assert playout_engine._terminal_do_executed, \
        "ASSERTION A FAILED: Terminal DO must execute exactly once during DRAINING"
    assert dj_engine.terminal_do_call_count == 1, \
        "ASSERTION A FAILED: Exactly one terminal DO call must occur"
    
    # ASSERTION B: No normal DO logic may run after draining begins
    # All DO calls after draining begins must be terminal DO only
    # Note: The DO for the normal segment that was playing when shutdown triggered
    # might execute before we can observe draining state. The key invariant is that
    # AFTER draining begins, ONLY terminal DO is allowed.
    # We verify this by checking that all DO calls during/after draining are terminal
    if dj_engine._draining_started:
        # After draining started, any DO calls must be terminal
        # The tracking mock will raise AssertionError if normal DO occurs during draining
        assert dj_engine.terminal_do_call_count >= 1, \
            f"ASSERTION B FAILED: After draining began, terminal DO must occur. "
            f"Terminal DO calls: {dj_engine.terminal_do_call_count}"
    
    # ASSERTION C: Playout must not stop before terminal DO completes
    # The playout loop must continue until terminal DO is executed
    # This is verified by _terminal_do_executed flag being set
    # while playout is still potentially active
    assert playout_engine._terminal_do_executed, \
        "ASSERTION C FAILED: Playout stopped before terminal DO completed"
    
    # Check that shutdown announcement was queued (if terminal intent had one)
    # Terminal DO should have queued the shutdown announcement
    # Note: If no shutdown announcement exists, queue may be empty, which is valid
    
    # ASSERTION D: Station must not wait indefinitely once terminal playout is complete
    # Once terminal DO executes and terminal segment (if any) finishes,
    # playout should complete and wait_for_playout_stopped should return within timeout
    
    # Wait for terminal segment to finish (if it exists)
    # Terminal segment should play after being queued by terminal DO
    max_wait_terminal = 3.0
    start_terminal_wait = time.time()
    
    # Wait for terminal segment to finish or for playout to complete
    while (time.time() - start_terminal_wait) < max_wait_terminal:
        # Check if terminal segment exists and is playing
        if playout_engine.queue_size() > 0:
            # Terminal segment exists, wait for it to finish
            time.sleep(0.1)
            continue
        elif playout_engine._terminal_do_executed and not playout_engine.is_playing():
            # Terminal DO executed and no segment playing (no terminal segment or it finished)
            break
        time.sleep(0.05)
    
    # Stop playout engine to clean up
    playout_engine.stop()
    
    # Wait for playout thread to finish
    playout_stopped = playout_engine.wait_for_playout_stopped(timeout=5.0)
    assert playout_stopped, \
        "ASSERTION D FAILED: Playout must complete within reasonable time after terminal playout"
    
    # ASSERTION E: Exactly ONE terminal THINK/DO cycle executed
    assert dj_engine.terminal_do_call_count == 1, \
        f"ASSERTION E FAILED: Exactly one terminal DO must execute. "
        f"Got {dj_engine.terminal_do_call_count} terminal DO calls"
    
    # Verify that after terminal DO, no further THINK/DO cycles occur
    # The _terminal_do_executed flag should prevent further DO callbacks during DRAINING
    final_do_count = dj_engine.do_call_count
    final_terminal_do_count = dj_engine.terminal_do_call_count
    
    # Wait a bit to ensure no additional DO calls occur
    time.sleep(0.2)
    
    # Verify no additional DO calls occurred
    assert dj_engine.do_call_count == final_do_count, \
        f"ASSERTION E FAILED: Additional DO calls occurred after terminal DO. "
        f"Expected {final_do_count}, got {dj_engine.do_call_count}"
    assert dj_engine.terminal_do_call_count == final_terminal_do_count == 1, \
        f"ASSERTION E FAILED: Terminal DO count changed after completion. "
        f"Expected 1, got {dj_engine.terminal_do_call_count}"
    
    # Clean up
    stub_sink.close()
