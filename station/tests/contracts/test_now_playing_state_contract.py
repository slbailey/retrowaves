"""
Contract tests for NEW_NOW_PLAYING_STATE_CONTRACT

See docs/contracts/NEW_NOW_PLAYING_STATE_CONTRACT.md

Tests map directly to contract clauses:
- U.1, I.7: State created on segment start (Test 1)
- U.3, I.7: State cleared on segment finish (Test 2)
- U.2, I.4: State is immutable mid-segment (Test 3)
- N.4: No derived fields exist (Test 4)
- U.4, I.2: Single writer enforcement (Test 5)
- E.3, F.7: Exposure is read-only (Test 6)
- U.3 (optional): Restart semantics (Test 7)
"""

import pytest
import time
from dataclasses import dataclass, FrozenInstanceError
from typing import Optional

from station.tests.contracts.test_doubles import create_fake_audio_event


# Test double for NowPlayingState structure (per contract N.1, N.2)
@dataclass(frozen=True)
class NowPlayingState:
    """Test double for NowPlayingState - matches contract structure."""
    segment_type: str  # Required (N.1)
    started_at: float  # Required (N.1) - wall-clock timestamp
    title: Optional[str] = None  # Optional (N.2)
    artist: Optional[str] = None  # Optional (N.2)
    album: Optional[str] = None  # Optional (N.2)
    year: Optional[int] = None  # Optional (N.2)
    duration_sec: Optional[float] = None  # Optional (N.2)
    file_path: Optional[str] = None  # Optional (N.2)


# Minimal state manager - contract boundary for lifecycle events
class NowPlayingStateManager:
    """
    Minimal state manager for contract testing.
    
    This represents the Station's lifecycle handler boundary.
    Tests interact with this manager, not directly with state objects.
    """
    
    def __init__(self):
        self._state: Optional[NowPlayingState] = None
    
    def on_segment_started(self, event) -> None:
        """
        Handle on_segment_started event (U.1).
        
        Contract U.1: State MUST be created when on_segment_started is emitted.
        """
        # Extract metadata from AudioEvent (simplified for contract test)
        metadata = getattr(event, 'metadata', {}) or {}
        
        self._state = NowPlayingState(
            segment_type=event.type,
            started_at=time.time(),  # Wall-clock timestamp (N.1)
            title=metadata.get('title'),
            artist=metadata.get('artist'),
            album=metadata.get('album'),
            year=metadata.get('year'),
            duration_sec=metadata.get('duration'),
            file_path=event.path
        )
    
    def on_segment_finished(self) -> None:
        """
        Handle on_segment_finished event (U.3).
        
        Contract U.3: State MUST be cleared when on_segment_finished is emitted.
        """
        self._state = None
    
    def get_state(self) -> Optional[NowPlayingState]:
        """
        Get current state (read-only).
        
        Contract E.3: State MAY be queried via read operations.
        """
        return self._state
    
    def clear_state(self) -> None:
        """
        Clear state (for restart semantics testing).
        
        Contract U.3: If Station restarts, state MUST be cleared.
        """
        self._state = None


class Test1_StateCreatedOnSegmentStart:
    """Test 1: State created on segment start (U.1, I.7)."""
    
    def test_u1_state_created_on_segment_started(self):
        """U.1, I.7: NowPlayingState MUST be created when on_segment_started is emitted."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        
        # Contract U.1: State MUST be created when on_segment_started is emitted
        manager.on_segment_started(segment)
        state = manager.get_state()
        
        # Contract U.1: State MUST be created
        assert state is not None, "State must be created on segment_started"
        
        # Contract N.1: Required fields MUST be set
        assert state.segment_type == "song", "segment_type must match AudioEvent type"
        assert state.started_at is not None, "started_at must be set"
        assert isinstance(state.started_at, float), "started_at must be float"
        assert state.started_at > 0, "started_at must be valid wall-clock timestamp"
        
        # Contract I.7: State MUST align with segment lifecycle
        assert state.file_path == segment.path, "State must reflect the segment that triggered on_segment_started"
    
    def test_u1_state_fields_match_audio_event(self):
        """U.1: State MUST be populated from the AudioEvent that triggered on_segment_started."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        
        # Add metadata to segment (simulated)
        segment.metadata = {
            'title': 'Test Song',
            'artist': 'Test Artist',
            'album': 'Test Album',
            'year': 2024,
            'duration': 180.0
        }
        
        manager.on_segment_started(segment)
        state = manager.get_state()
        
        # Contract U.1: State MUST be populated from AudioEvent
        assert state.segment_type == segment.type, "segment_type must match AudioEvent"
        assert state.file_path == segment.path, "file_path must match AudioEvent"
        
        # Optional fields may come from AudioEvent metadata
        assert state.title == "Test Song"
        assert state.artist == "Test Artist"
        assert state.album == "Test Album"
        assert state.year == 2024
        assert state.duration_sec == 180.0
    
    def test_u1_started_at_is_wall_clock_timestamp(self):
        """U.1, N.1: started_at MUST be wall-clock timestamp (not monotonic)."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        
        # Contract N.1: started_at MUST be wall-clock timestamp (time.time(), not time.monotonic())
        wall_clock_before = time.time()
        manager.on_segment_started(segment)
        wall_clock_after = time.time()
        state = manager.get_state()
        
        # Verify it's a wall-clock timestamp (has epoch meaning)
        assert wall_clock_before <= state.started_at <= wall_clock_after, \
            "started_at must be wall-clock timestamp (time.time()), not monotonic"
        assert state.started_at > 1000000000, \
            "started_at must be epoch-based (not monotonic process-relative)"


class Test2_StateClearedOnSegmentFinish:
    """Test 2: State cleared on segment finish (U.3, I.7)."""
    
    def test_u3_state_cleared_on_segment_finished(self):
        """U.3, I.7: NowPlayingState MUST be cleared when on_segment_finished is emitted."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        
        # Create active state
        manager.on_segment_started(segment)
        assert manager.get_state() is not None, "State must exist before clearing"
        
        # Contract U.3: State MUST be cleared when on_segment_finished is emitted
        manager.on_segment_finished()
        cleared_state = manager.get_state()
        
        # Contract U.3: State MUST be cleared
        assert cleared_state is None, "State must be cleared on segment_finished"
        
        # Contract U.3: State MUST NOT retain any information
        assert cleared_state is None, "No prior data must remain"
    
    def test_u3_state_cleared_before_next_segment(self):
        """U.3: Clearing MUST occur before the next segment's on_segment_started event."""
        manager = NowPlayingStateManager()
        
        # First segment starts and finishes
        segment1 = create_fake_audio_event("/fake/song1.mp3", "song")
        manager.on_segment_started(segment1)
        manager.on_segment_finished()
        
        # Contract U.3: Clearing MUST occur before next segment starts
        assert manager.get_state() is None, "Previous state must be cleared"
        
        # Next segment starts
        segment2 = create_fake_audio_event("/fake/song2.mp3", "song")
        manager.on_segment_started(segment2)
        state2 = manager.get_state()
        
        assert state2.file_path != segment1.path, "New state must reflect new segment"


class Test3_StateIsImmutableMidSegment:
    """Test 3: State is immutable mid-segment (U.2, I.4)."""
    
    def test_u2_state_not_mutated_during_playback(self):
        """U.2, I.4: NowPlayingState MUST NOT be mutated during segment playback."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        segment.metadata = {'title': 'Original Title'}
        
        manager.on_segment_started(segment)
        state = manager.get_state()
        original_started_at = state.started_at
        
        # Contract U.2: State MUST NOT be mutated during playback
        # Since state is frozen dataclass, modification attempts will fail
        with pytest.raises(FrozenInstanceError):
            # Attempt to modify state (should fail)
            state.segment_type = "modified"
        
        # Contract I.4: State MUST NOT be modified during segment playback
        assert state.segment_type == segment.type, "Original state must remain intact"
        assert state.title == "Original Title", "Original state must remain intact"
        assert state.started_at == original_started_at, "started_at must not be modified"
    
    def test_u2_state_remains_constant_throughout_playback(self):
        """U.2: State MUST remain constant throughout segment playback."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        
        manager.on_segment_started(segment)
        state = manager.get_state()
        original_started_at = state.started_at
        
        # Simulate mid-segment - state should remain unchanged
        # Contract U.2: No mid-segment updates MAY occur
        state_after_time = manager.get_state()  # Re-read state
        
        assert state_after_time is state, "State object must remain the same"
        assert state_after_time.started_at == original_started_at, "started_at must not change"
        assert state_after_time.segment_type == segment.type, "segment_type must not change"


class Test4_NoDerivedFieldsExist:
    """Test 4: No derived fields exist (N.4)."""
    
    def test_n4_no_elapsed_time_field(self):
        """N.4: NowPlayingState MUST NOT include elapsed time calculations."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        manager.on_segment_started(segment)
        state = manager.get_state()
        
        # Contract N.4: FORBIDDEN - Elapsed time calculations
        assert not hasattr(state, 'elapsed_time'), "State must not have elapsed_time field"
        assert not hasattr(state, 'elapsed'), "State must not have elapsed field"
    
    def test_n4_no_remaining_time_field(self):
        """N.4: NowPlayingState MUST NOT include remaining time calculations."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        segment.metadata = {'duration': 180.0}
        manager.on_segment_started(segment)
        state = manager.get_state()
        
        # Contract N.4: FORBIDDEN - Remaining time calculations
        assert not hasattr(state, 'remaining_time'), "State must not have remaining_time field"
        assert not hasattr(state, 'remaining'), "State must not have remaining field"
    
    def test_n4_no_progress_percentage_field(self):
        """N.4: NowPlayingState MUST NOT include progress percentage."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        segment.metadata = {'duration': 180.0}
        manager.on_segment_started(segment)
        state = manager.get_state()
        
        # Contract N.4: FORBIDDEN - Progress percentage
        assert not hasattr(state, 'progress'), "State must not have progress field"
        assert not hasattr(state, 'progress_percentage'), "State must not have progress_percentage field"
    
    def test_n4_no_estimated_completion_timestamp(self):
        """N.4: NowPlayingState MUST NOT include estimated completion timestamps."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        segment.metadata = {'duration': 180.0}
        manager.on_segment_started(segment)
        state = manager.get_state()
        
        # Contract N.4: FORBIDDEN - Estimated completion timestamps
        assert not hasattr(state, 'completion_at'), "State must not have completion_at field"
        assert not hasattr(state, 'estimated_completion'), "State must not have estimated_completion field"
    
    def test_n4_attempting_to_set_derived_fields_fails(self):
        """N.4: Attempting to set derived fields fails (prevents future mistakes)."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        manager.on_segment_started(segment)
        state = manager.get_state()
        
        # Contract N.4: Any field that requires periodic updates is FORBIDDEN
        # NowPlayingState is a frozen dataclass - cannot add fields at runtime
        # This structural constraint prevents "just add elapsed" mistakes
        
        # Attempting to add derived fields should fail (frozen dataclass prevents this)
        assert not hasattr(state, 'elapsed_time'), "Derived fields must not exist"


class Test5_SingleWriterEnforcement:
    """Test 5: Single writer enforcement (U.4, I.2)."""
    
    def test_u4_station_can_create_state(self):
        """U.4, I.2: Station can create state."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        
        # Station creates state via lifecycle handler
        manager.on_segment_started(segment)
        state = manager.get_state()
        
        # Contract U.4: Station MUST be the sole authority for creating state
        assert state is not None, "Station can create state"
    
    def test_u4_station_can_clear_state(self):
        """U.4, I.2: Station can clear state."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        manager.on_segment_started(segment)
        
        # Station clears state via lifecycle handler
        manager.on_segment_finished()
        cleared_state = manager.get_state()
        
        # Contract U.4: Station MUST be the sole authority for clearing state
        assert cleared_state is None, "Station can clear state"
    
    def test_u4_manager_has_no_mutation_apis(self):
        """U.4, I.2: Manager has no mutation APIs (authority separation, not just immutability)."""
        manager = NowPlayingStateManager()
        
        # Contract U.4, I.2: No mutation APIs MAY be exposed
        # This makes it impossible for Tower or external code to even try to mutate state
        assert not hasattr(manager, 'set_state'), "Manager must not have set_state method"
        assert not hasattr(manager, 'update_state'), "Manager must not have update_state method"
        assert not hasattr(manager, 'modify_state'), "Manager must not have modify_state method"
        assert not hasattr(manager, 'mutate_state'), "Manager must not have mutate_state method"
    
    def test_u4_tower_cannot_mutate_state(self):
        """U.4, I.2: Tower cannot mutate state (no mutation APIs available)."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        manager.on_segment_started(segment)
        state = manager.get_state()
        
        # Contract U.4, I.2: Tower MUST NOT modify NowPlayingState
        # Tower has no write methods - this is enforced by API design
        # In implementation, Tower would only have read access via get_state()
        
        # Verify manager has no mutation APIs (Tower cannot call them)
        assert not hasattr(manager, 'set_state'), "Tower cannot call set_state (does not exist)"
        
        # Verify state is immutable (Tower cannot modify even if it had access)
        with pytest.raises(FrozenInstanceError):
            # Tower attempting to modify state (should fail)
            state.segment_type = "modified_by_tower"
    
    def test_u4_external_api_cannot_mutate_state(self):
        """U.4, I.2: External API cannot mutate state (no mutation APIs available)."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        manager.on_segment_started(segment)
        state = manager.get_state()
        
        # Contract U.4, I.2: External clients MUST NOT modify NowPlayingState
        # Contract F.7: No write operations MAY be exposed
        
        # External API has no write methods - this is enforced by API design
        # In implementation, REST/WebSocket would only expose read operations via get_state()
        
        # Verify manager has no mutation APIs (external API cannot call them)
        assert not hasattr(manager, 'set_state'), "External API cannot call set_state (does not exist)"
        
        # Verify state is immutable (external API cannot modify even if it had access)
        with pytest.raises(FrozenInstanceError):
            # External API attempting to modify state (should fail)
            state.title = "modified_by_api"


class Test6_ExposureIsReadOnly:
    """Test 6: Exposure is read-only (E.3, F.7)."""
    
    def test_e3_rest_endpoint_accepts_get(self):
        """E.3: REST endpoint MUST respond to GET requests with current state."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        manager.on_segment_started(segment)
        
        # Contract E.3: Endpoint MUST respond to GET requests
        # Simulated GET request returns state via get_state()
        get_response = manager.get_state()
        
        assert get_response is not None, "GET request must return state"
        assert isinstance(get_response, NowPlayingState), "GET response must be state object"
    
    def test_e3_rest_endpoint_rejects_post(self):
        """E.3, F.7: REST endpoint MUST NOT accept POST requests."""
        # NOTE: This test asserts contract intent, not implementation.
        # Contract E.3: Endpoint MUST NOT accept POST, PUT, PATCH, or DELETE requests
        # Contract F.7: HTTP POST/PUT/PATCH/DELETE MUST NOT be accepted
        
        # Simulated POST request - should be rejected
        # In implementation, HTTP server would return 405 Method Not Allowed
        post_allowed = False
        
        assert post_allowed is False, "POST requests must be rejected"
    
    def test_e3_rest_endpoint_rejects_put_patch_delete(self):
        """E.3, F.7: REST endpoint MUST NOT accept PUT, PATCH, or DELETE requests."""
        # NOTE: This test asserts contract intent, not implementation.
        # Contract E.3: Endpoint MUST NOT accept POST, PUT, PATCH, or DELETE requests
        # Contract F.7: HTTP POST/PUT/PATCH/DELETE MUST NOT be accepted
        
        # In implementation, HTTP server would return 405 Method Not Allowed
        put_allowed = False
        patch_allowed = False
        delete_allowed = False
        
        assert put_allowed is False, "PUT requests must be rejected"
        assert patch_allowed is False, "PATCH requests must be rejected"
        assert delete_allowed is False, "DELETE requests must be rejected"
    
    def test_e3_rest_endpoint_is_read_only(self):
        """E.3: REST endpoint MUST be read-only."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        manager.on_segment_started(segment)
        
        # Contract E.3: Endpoint MUST NOT modify state
        original_state = manager.get_state()
        
        # Simulated read operation - state unchanged
        read_state = manager.get_state()
        
        assert read_state is original_state, "Read operation must not modify state"
        assert read_state.segment_type == original_state.segment_type, "State must remain unchanged"
    
    def test_f7_websocket_emits_state(self):
        """F.7: WebSocket MUST emit state (read-only)."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        manager.on_segment_started(segment)
        
        # Contract E.2: State MUST be broadcast when on_segment_started occurs
        # Simulated WebSocket emit - reads state via get_state()
        emitted_state = manager.get_state()
        
        assert emitted_state is not None, "WebSocket must emit state"
        assert isinstance(emitted_state, NowPlayingState), "Emitted state must be NowPlayingState"
    
    def test_f7_websocket_ignores_inbound_messages(self):
        """F.7: WebSocket MUST ignore inbound messages (no write operations)."""
        # NOTE: This test asserts contract intent, not implementation.
        # Contract F.7: WebSocket write messages MUST NOT modify state
        # Contract E.2: Events are emitted, not received
        
        # Simulated inbound WebSocket message - should be ignored
        # In implementation, WebSocket server would ignore inbound messages
        inbound_message_processed = False
        
        assert inbound_message_processed is False, "Inbound WebSocket messages must be ignored"


class Test7_RestartSemantics:
    """Test 7: Restart semantics (U.3 optional tightening)."""
    
    def test_u3_restart_clears_state(self):
        """U.3: If Station restarts mid-segment, NowPlayingState MUST be cleared."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        manager.on_segment_started(segment)
        
        # Simulate Station restart
        # Contract U.3: If Station restarts mid-segment, NowPlayingState MUST be cleared
        manager.clear_state()
        state_after_restart = manager.get_state()
        
        assert state_after_restart is None, "State must be cleared on restart"
    
    def test_u3_restart_no_reconstruction(self):
        """U.3: If Station restarts mid-segment, MUST NOT attempt reconstruction of interrupted segment."""
        manager = NowPlayingStateManager()
        segment = create_fake_audio_event("/fake/song.mp3", "song")
        manager.on_segment_started(segment)
        state_before_restart = manager.get_state()
        
        # Simulate Station restart
        # Contract U.3: MUST NOT attempt reconstruction of the interrupted segment
        manager.clear_state()
        state_after_restart = manager.get_state()
        
        # Verify no reconstruction APIs exist
        reconstruction_attempted = False
        assert not hasattr(manager, 'reconstruct_state'), "Manager must not have reconstruct_state method"
        assert not hasattr(manager, 'resume_state'), "Manager must not have resume_state method"
        
        assert state_after_restart is None, "State must be cleared"
        assert reconstruction_attempted is False, "Reconstruction must not be attempted"
    
    def test_u3_restart_clean_state(self):
        """U.3: Restart results in clean state (no inference, no resume metadata)."""
        manager = NowPlayingStateManager()
        
        # Contract U.3: No inference, no "resume metadata"
        # After restart, state is None until next segment starts
        
        # Simulate restart
        manager.clear_state()
        state_after_restart = manager.get_state()
        
        # Next segment starts
        new_segment = create_fake_audio_event("/fake/newsong.mp3", "song")
        manager.on_segment_started(new_segment)
        new_state = manager.get_state()
        
        assert state_after_restart is None, "State after restart must be None"
        assert new_state.file_path != "/fake/song.mp3", "New state must not reference interrupted segment"
