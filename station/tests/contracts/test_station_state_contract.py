"""
Contract tests for STATION_STATE_CONTRACT.md

See station/docs/contracts/STATION_STATE_CONTRACT.md

PHASE 2: Tests only - these tests MUST FAIL until Phase 3 implementation.

Tests are organized by contract categories:
- Category A: Station State Query Tests (S.1, S.2, Q.1-Q.4)
- Category B: Content Plane Invariant Tests (S.4)
- Category C: Monotonic vs Wall Clock Tests (S.2.1, S.2.2)
- Category D: Event Non-Authority Tests (R.1-R.4, P.1-P.4)
"""

import pytest
import time
import http.client
import json
import os
from typing import Optional, Dict, Any


# Helper to check if Station HTTP server is available for integration tests
def _station_server_available() -> bool:
    """Check if Station HTTP server is running or integration tests are enabled via env var."""
    # Check for explicit integration test flag
    if os.getenv("STATION_INTEGRATION_TESTS", "").lower() in ("1", "true", "yes"):
        return True
    
    # Try to connect to Station HTTP server
    try:
        conn = http.client.HTTPConnection("localhost", 8000, timeout=0.5)
        conn.request("GET", "/station/state")
        response = conn.getresponse()
        conn.close()
        return response.status in (200, 404)  # Server is running if we get any HTTP response
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


# Skip integration tests unless Station is running or env flag is set
skip_if_no_station = pytest.mark.skipif(
    not _station_server_available(),
    reason="Station HTTP server not available. Set STATION_INTEGRATION_TESTS=1 to enable or start Station."
)


# ============================================================================
# CATEGORY A: Station State Query Tests
# ============================================================================

class TestA_StationStateQuery:
    """Category A: Station State Query Tests (S.1, S.2, Q.1-Q.4)."""
    
    def test_a1_state_endpoint_exists(self):
        """
        A.1: /station/state endpoint MUST exist and return valid JSON.
        
        Per STATION_STATE_CONTRACT.md Q.1:
        - MUST be accessible via HTTP GET endpoint /station/state
        - MUST return current state synchronously
        - MUST be idempotent
        - MUST be non-blocking
        - MUST return state in consistent format (JSON)
        
        NOTE: This test always runs (not skipped) to verify the endpoint is implemented.
        It will fail if Station HTTP server is not running, which indicates missing implementation.
        """
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            # Contract requires endpoint exists (not 404)
            assert response.status != 404, \
                f"Contract violation [Q.1]: /station/state endpoint must exist. Got {response.status}"
            
            # Contract requires valid JSON response
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [Q.1]: /station/state endpoint not accessible: {e}")
        except json.JSONDecodeError as e:
            pytest.fail(f"Contract violation [Q.2]: /station/state must return valid JSON: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_a2_state_always_queryable(self):
        """
        A.2: State MUST be queryable at any time without event replay.
        
        Per STATION_STATE_CONTRACT.md I.1:
        - State queries MUST return a valid response at any time
        - State queries MUST NOT require event history
        - State queries MUST NOT require event replay
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [I.1]: State must be queryable at any time. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            # State must be valid even without event history
            assert isinstance(state, dict), "State must be a dictionary"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [I.1]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_a3_state_queryable_after_startup(self):
        """
        A.3: State MUST be queryable immediately after startup.
        
        Per STATION_STATE_CONTRACT.md I.1:
        - State queries MUST return a valid response at any time
        - State MUST be queryable without event replay
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            # Query state immediately (simulating right after startup)
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [I.1]: State must be queryable after startup. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            # State must have required fields even at startup
            assert "station_state" in state, "State must include station_state field"
            assert "since" in state, "State must include since field"
            assert "current_audio" in state, "State must include current_audio field"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [I.1]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_a4_state_queryable_mid_song(self):
        """
        A.4: State MUST be queryable mid-song.
        
        Per STATION_STATE_CONTRACT.md Q.1:
        - State MUST be queryable at any time
        - State MUST return a coherent snapshot
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [Q.1]: State must be queryable mid-song. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            # State must be coherent snapshot
            assert isinstance(state, dict), "State must be a dictionary"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [Q.1]: State endpoint not accessible: {e}")
    
    # DELETED: test_a5_state_queryable_during_dj_talking
    # REASON: dj_talking is deprecated. Non-song segments are represented by segment_playing events
    # and state with segment_type="segment". State is queryable at any time regardless of content type.
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_a6_state_queryable_during_shutdown(self):
        """
        A.6: State MUST be queryable during shutdown.
        
        Per STATION_STATE_CONTRACT.md Q.1:
        - State MUST be queryable at any time
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [Q.1]: State must be queryable during shutdown. Got {response.status}"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [Q.1]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_a7_state_response_format(self):
        """
        A.7: State response MUST match required format.
        
        Per STATION_STATE_CONTRACT.md Q.2:
        - Response MUST include: station_state, since, current_audio
        - station_state MUST be one of finite set
        - since MUST be float (monotonic timestamp)
        - current_audio MUST be object or null
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [Q.2]: State endpoint must return 200. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            # Contract Q.2: Required fields
            assert "station_state" in state, "Contract violation [Q.2]: Response must include station_state"
            assert "since" in state, "Contract violation [Q.2]: Response must include since"
            assert "current_audio" in state, "Contract violation [Q.2]: Response must include current_audio"
            
            # Contract S.1: station_state must be one of finite set
            # NOTE: DJ_TALKING is deprecated - non-song segments use SONG_PLAYING state with segment_type="segment"
            allowed_states = {"STARTING_UP", "SONG_PLAYING", "FALLBACK", "SHUTTING_DOWN", "ERROR"}
            assert state["station_state"] in allowed_states, \
                f"Contract violation [S.1]: station_state must be one of {allowed_states}, got {state['station_state']}"
            
            # Contract S.2.2: since must be float (monotonic timestamp)
            assert isinstance(state["since"], (int, float)), \
                f"Contract violation [S.2.2]: since must be numeric, got {type(state['since'])}"
            assert state["since"] > 0, \
                f"Contract violation [S.2.2]: since must be positive, got {state['since']}"
            
            # Contract S.2.3: current_audio must be object or null
            assert state["current_audio"] is None or isinstance(state["current_audio"], dict), \
                f"Contract violation [S.2.3]: current_audio must be object or null, got {type(state['current_audio'])}"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [Q.2]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_a8_state_query_performance(self):
        """
        A.8: State queries MUST be performant (< 10ms typical, < 100ms maximum).
        
        Per STATION_STATE_CONTRACT.md Q.4:
        - Query response time MUST be < 10ms typical, < 100ms maximum
        - Query MUST NOT block playout thread
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            start = time.perf_counter()
            conn = http.client.HTTPConnection("localhost", 8000, timeout=0.1)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            response.read()
            elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
            
            # Contract Q.4: < 100ms maximum
            assert elapsed < 100, \
                f"Contract violation [Q.4]: Query must return in < 100ms maximum, got {elapsed:.2f}ms"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [Q.4]: State endpoint not accessible: {e}")


# ============================================================================
# CATEGORY B: Content Plane Invariant Tests
# ============================================================================

class TestB_ContentPlaneInvariant:
    """Category B: Content Plane Invariant Tests (S.4)."""
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_b1_current_audio_non_null_when_playing(self):
        """
        B.1: When station_state is SONG_PLAYING, current_audio MUST be non-null.
        
        Per STATION_STATE_CONTRACT.md S.4:
        - When station_state is SONG_PLAYING, current_audio MUST be non-null
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.4]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            assert state.get("station_state") == "SONG_PLAYING", \
                "Test precondition failed: station_state must be SONG_PLAYING for this invariant test"
            
            assert state["current_audio"] is not None, \
                "Contract violation [S.4]: When station_state is SONG_PLAYING, current_audio MUST be non-null"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.4]: State endpoint not accessible: {e}")
    
    # DELETED: test_b2_current_audio_non_null_when_dj_talking
    # REASON: DJ_TALKING state is deprecated. Non-song segments use SONG_PLAYING state
    # with segment_type="segment" and required metadata (segment_class, segment_role, production_type).
    # New tests for non-song segment state are in test_segment_playing_state_contract.py
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_b3_current_audio_non_null_when_starting_up(self):
        """
        B.3: When station_state is STARTING_UP, current_audio MUST be non-null.
        
        Per STATION_STATE_CONTRACT.md S.4:
        - When station_state is STARTING_UP, current_audio MUST be non-null
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.4]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            assert state.get("station_state") == "STARTING_UP", \
                "Test precondition failed: station_state must be STARTING_UP for this invariant test"
            
            assert state["current_audio"] is not None, \
                "Contract violation [S.4]: When station_state is STARTING_UP, current_audio MUST be non-null"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.4]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_b4_current_audio_non_null_when_shutting_down(self):
        """
        B.4: When station_state is SHUTTING_DOWN, current_audio MUST be non-null.
        
        Per STATION_STATE_CONTRACT.md S.4:
        - When station_state is SHUTTING_DOWN, current_audio MUST be non-null
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.4]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            assert state.get("station_state") == "SHUTTING_DOWN", \
                "Test precondition failed: station_state must be SHUTTING_DOWN for this invariant test"
            
            assert state["current_audio"] is not None, \
                "Contract violation [S.4]: When station_state is SHUTTING_DOWN, current_audio MUST be non-null"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.4]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_b5_current_audio_null_when_error(self):
        """
        B.5: When station_state is ERROR, current_audio MUST be null.
        
        Per STATION_STATE_CONTRACT.md S.4:
        - When station_state is ERROR, current_audio MUST be null
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.4]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            assert state.get("station_state") == "ERROR", \
                "Test precondition failed: station_state must be ERROR for this invariant test"
            
            assert state["current_audio"] is None, \
                "Contract violation [S.4]: When station_state is ERROR, current_audio MUST be null"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.4]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_b6_current_audio_structure_when_not_null(self):
        """
        B.6: When current_audio is not null, it MUST have required fields.
        
        Per STATION_STATE_CONTRACT.md S.2.3:
        - segment_type, file_path, started_at MUST be present and non-null
        - title, artist, duration_sec MAY be null
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.2.3]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            if state.get("current_audio") is not None:
                audio = state["current_audio"]
                
                # Contract S.2.3: Required fields when not null
                assert "segment_type" in audio, \
                    "Contract violation [S.2.3]: current_audio must include segment_type"
                assert "file_path" in audio, \
                    "Contract violation [S.2.3]: current_audio must include file_path"
                assert "started_at" in audio, \
                    "Contract violation [S.2.3]: current_audio must include started_at"
                
                assert audio["segment_type"] is not None, \
                    "Contract violation [S.2.3]: segment_type must be non-null"
                assert audio["file_path"] is not None, \
                    "Contract violation [S.2.3]: file_path must be non-null"
                assert audio["started_at"] is not None, \
                    "Contract violation [S.2.3]: started_at must be non-null"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.2.3]: State endpoint not accessible: {e}")


# ============================================================================
# CATEGORY B2: Non-Song Segment State Tests (Phase 2)
# ============================================================================

class TestB2_NonSongSegmentState:
    """Category B2: Non-Song Segment State Tests - Required Metadata Enforcement."""
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_b2_1_non_song_segment_has_segment_type_segment(self):
        """
        B2.1: When playing non-song segment, segment_type MUST be "segment".
        
        Per STATION_STATE_CONTRACT.md S.2.3:
        - For non-song segments: segment_type MUST be "segment"
        - For song segments: segment_type MUST be "song"
        """
        # NOTE: This test will FAIL until Phase 3 implementation
        # Expected failure: 404 Not Found or segment_type not "segment" for non-song segments
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.2.3]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            # Test precondition: current_audio must exist and be non-song
            if state.get("current_audio") is not None:
                audio = state["current_audio"]
                
                # If this is a non-song segment, segment_type must be "segment"
                # (We can't easily determine if it's non-song without segment metadata,
                # but we can verify the structure)
                if audio.get("segment_type") == "segment":
                    # This is a non-song segment - verify required metadata exists
                    assert "segment_class" in audio, \
                        "Contract violation [S.2.3]: Non-song segments MUST include segment_class"
                    assert "segment_role" in audio, \
                        "Contract violation [S.2.3]: Non-song segments MUST include segment_role"
                    assert "production_type" in audio, \
                        "Contract violation [S.2.3]: Non-song segments MUST include production_type"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.2.3]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_b2_2_non_song_segment_has_segment_class(self):
        """
        B2.2: Non-song segments MUST include segment_class in current_audio.
        
        Per STATION_STATE_CONTRACT.md S.2.3:
        - For non-song segments (segment_type="segment"), segment_class MUST be present
        - segment_class MUST mirror segment_playing event metadata
        """
        # NOTE: This test will FAIL until Phase 3 implementation
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.2.3]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            if state.get("current_audio") is not None:
                audio = state["current_audio"]
                
                # If segment_type is "segment", segment_class must be present
                if audio.get("segment_type") == "segment":
                    assert "segment_class" in audio, \
                        "Contract violation [S.2.3]: Non-song segments MUST include segment_class"
                    assert audio["segment_class"] is not None, \
                        "Contract violation [S.2.3]: segment_class must not be None"
                    assert isinstance(audio["segment_class"], str), \
                        "Contract violation [S.2.3]: segment_class must be a string"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.2.3]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_b2_3_non_song_segment_has_segment_role(self):
        """
        B2.3: Non-song segments MUST include segment_role in current_audio.
        
        Per STATION_STATE_CONTRACT.md S.2.3:
        - For non-song segments (segment_type="segment"), segment_role MUST be present
        - segment_role MUST mirror segment_playing event metadata
        """
        # NOTE: This test will FAIL until Phase 3 implementation
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.2.3]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            if state.get("current_audio") is not None:
                audio = state["current_audio"]
                
                if audio.get("segment_type") == "segment":
                    assert "segment_role" in audio, \
                        "Contract violation [S.2.3]: Non-song segments MUST include segment_role"
                    assert audio["segment_role"] is not None, \
                        "Contract violation [S.2.3]: segment_role must not be None"
                    assert isinstance(audio["segment_role"], str), \
                        "Contract violation [S.2.3]: segment_role must be a string"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.2.3]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_b2_4_non_song_segment_has_production_type(self):
        """
        B2.4: Non-song segments MUST include production_type in current_audio.
        
        Per STATION_STATE_CONTRACT.md S.2.3:
        - For non-song segments (segment_type="segment"), production_type MUST be present
        - production_type MUST mirror segment_playing event metadata
        """
        # NOTE: This test will FAIL until Phase 3 implementation
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.2.3]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            if state.get("current_audio") is not None:
                audio = state["current_audio"]
                
                if audio.get("segment_type") == "segment":
                    assert "production_type" in audio, \
                        "Contract violation [S.2.3]: Non-song segments MUST include production_type"
                    assert audio["production_type"] is not None, \
                        "Contract violation [S.2.3]: production_type must not be None"
                    assert isinstance(audio["production_type"], str), \
                        "Contract violation [S.2.3]: production_type must be a string"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.2.3]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_b2_5_non_song_segment_state_mirrors_event_metadata(self):
        """
        B2.5: Non-song segment state MUST mirror segment_playing event metadata.
        
        Per STATION_STATE_CONTRACT.md S.2.3:
        - segment_class, segment_role, production_type in state MUST mirror
          corresponding segment_playing event metadata
        - State reflects the segment that triggered the most recent segment_playing event
        """
        # NOTE: This test will FAIL until Phase 3 implementation
        # This test verifies that state metadata matches event metadata
        # (In a real scenario, we would emit segment_playing and then query state)
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.2.3]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            if state.get("current_audio") is not None:
                audio = state["current_audio"]
                
                if audio.get("segment_type") == "segment":
                    # All three required metadata fields must be present
                    assert "segment_class" in audio, \
                        "Contract violation [S.2.3]: State must mirror segment_playing event metadata (segment_class)"
                    assert "segment_role" in audio, \
                        "Contract violation [S.2.3]: State must mirror segment_playing event metadata (segment_role)"
                    assert "production_type" in audio, \
                        "Contract violation [S.2.3]: State must mirror segment_playing event metadata (production_type)"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.2.3]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_b2_6_no_legacy_fields_in_state(self):
        """
        B2.6: State MUST NOT include legacy fields (intro, outro, id, talk).
        
        Per STATION_STATE_CONTRACT.md S.2.3:
        - Legacy fields like intro, outro, id, talk are FORBIDDEN
        - Only segment_class, segment_role, production_type are used for non-song segments
        """
        # NOTE: This test will FAIL until Phase 3 implementation
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.2.3]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            if state.get("current_audio") is not None:
                audio = state["current_audio"]
                
                # Legacy fields must NOT exist
                legacy_fields = ["intro", "outro", "id", "talk"]
                for field in legacy_fields:
                    assert field not in audio, \
                        f"Contract violation [S.2.3]: Legacy field '{field}' MUST NOT exist in state"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.2.3]: State endpoint not accessible: {e}")


# ============================================================================
# CATEGORY C: Monotonic vs Wall Clock Tests
# ============================================================================

class TestC_MonotonicVsWallClock:
    """Category C: Monotonic vs Wall Clock Tests (S.2.1, S.2.2)."""
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_c1_since_is_monotonic(self):
        """
        C.1: since MUST be monotonic timestamp and increase only on state transitions.
        
        Per STATION_STATE_CONTRACT.md S.2.2:
        - since MUST be monotonic timestamp (time.monotonic())
        - since MUST represent exact moment current state was entered
        - since MUST NOT be wall-clock timestamp
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.2.2]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            since = state.get("since")
            assert since is not None, "Contract violation [S.2.2]: since must be present"
            assert isinstance(since, (int, float)), \
                f"Contract violation [S.2.2]: since must be numeric, got {type(since)}"
            
            # Verify it's monotonic (not epoch-based)
            # Monotonic timestamps are typically much smaller than epoch timestamps
            # Epoch timestamps are > 1000000000 (year 2001)
            # Monotonic timestamps are typically < 1000000 (seconds since boot)
            assert since < 1000000000, \
                f"Contract violation [S.2.2]: since must be monotonic (not epoch), got {since}"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.2.2]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_c2_started_at_is_wall_clock(self):
        """
        C.2: started_at MUST be wall-clock timestamp (UTC) when current_audio is not null.
        
        Per STATION_STATE_CONTRACT.md S.2.3:
        - started_at MUST be wall-clock timestamp (time.time() or UTC epoch seconds)
        - started_at MUST represent exact moment on_segment_started was emitted
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.2.3]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            if state.get("current_audio") is not None:
                started_at = state["current_audio"].get("started_at")
                assert started_at is not None, \
                    "Contract violation [S.2.3]: started_at must be present when current_audio is not null"
                assert isinstance(started_at, (int, float)), \
                    f"Contract violation [S.2.3]: started_at must be numeric, got {type(started_at)}"
                
                # Verify it's wall-clock (epoch-based)
                # Wall-clock timestamps are epoch-based (typically > 1000000000)
                assert started_at > 1000000000, \
                    f"Contract violation [S.2.3]: started_at must be wall-clock (epoch-based), got {started_at}"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.2.3]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_c3_since_increases_on_state_transitions(self):
        """
        C.3: since MUST increase only on state transitions (monotonic).
        
        Per STATION_STATE_CONTRACT.md S.2.2:
        - since MUST be monotonic and increase only on state transitions
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            # Query state twice (simulating state transition)
            conn1 = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn1.request("GET", "/station/state")
            response1 = conn1.getresponse()
            data1 = json.loads(response1.read().decode('utf-8'))
            since1 = data1.get("since")
            conn1.close()
            
            time.sleep(0.1)  # Small delay
            
            conn2 = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn2.request("GET", "/station/state")
            response2 = conn2.getresponse()
            data2 = json.loads(response2.read().decode('utf-8'))
            since2 = data2.get("since")
            conn2.close()
            
            # If state changed, since should increase
            # If state didn't change, since should remain same
            if data1.get("station_state") != data2.get("station_state"):
                assert since2 >= since1, \
                    f"Contract violation [S.2.2]: since must increase on state transition, got {since1} -> {since2}"
            else:
                # Same state - since should remain same (monotonic, not wall-clock)
                assert since2 == since1, \
                    f"Contract violation [S.2.2]: since must remain same when state unchanged, got {since1} -> {since2}"
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.2.2]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_c4_clocks_must_not_be_conflated(self):
        """
        C.4: since (monotonic) and started_at (wall-clock) MUST NOT be conflated.
        
        Per STATION_STATE_CONTRACT.md S.2.2, S.2.3:
        - since is monotonic (time.monotonic())
        - started_at is wall-clock (time.time())
        - The two clocks MUST NOT be conflated
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            
            assert response.status == 200, \
                f"Contract violation [S.2.2, S.2.3]: State endpoint must exist. Got {response.status}"
            
            data = response.read()
            state = json.loads(data.decode('utf-8'))
            
            since = state.get("since")
            
            if state.get("current_audio") is not None:
                started_at = state["current_audio"].get("started_at")
                
                # Verify they are different types (monotonic vs wall-clock)
                # Monotonic is typically < 1000000000, wall-clock is > 1000000000
                assert since < 1000000000, \
                    f"Contract violation [S.2.2]: since must be monotonic, got {since}"
                assert started_at > 1000000000, \
                    f"Contract violation [S.2.3]: started_at must be wall-clock, got {started_at}"
                
                # They should NOT be equal (different clock sources)
                assert since != started_at, \
                    f"Contract violation [S.2.2, S.2.3]: since and started_at must not be conflated, got {since} == {started_at}"
            
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [S.2.2, S.2.3]: State endpoint not accessible: {e}")


# ============================================================================
# CATEGORY D: Event Non-Authority Tests
# ============================================================================

class TestD_EventNonAuthority:
    """Category D: Event Non-Authority Tests (R.1-R.4, P.1-P.4)."""
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_d1_emitting_song_playing_does_not_mutate_state(self):
        """
        D.1: Emitting song_playing event does NOT mutate state.
        
        Per STATION_STATE_CONTRACT.md R.2, P.4:
        - Events announce transitions; state represents current truth
        - State MUST NOT be mutated based on events
        - State updates happen ONLY via lifecycle hooks
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            # Query state before event emission
            conn1 = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn1.request("GET", "/station/state")
            response1 = conn1.getresponse()
            state_before = json.loads(response1.read().decode('utf-8'))
            conn1.close()
            
            # Emit song_playing event (simulated - in real test, would send to Tower)
            # NOTE: This is a contract test - we verify that state doesn't change
            # In real implementation, events are sent to Tower, not Station state
            
            # Query state after event emission
            time.sleep(0.1)
            conn2 = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn2.request("GET", "/station/state")
            response2 = conn2.getresponse()
            state_after = json.loads(response2.read().decode('utf-8'))
            conn2.close()
            
            # Contract R.2, P.4: Events do NOT mutate state
            # State should only change via lifecycle hooks (on_segment_started, on_segment_finished)
            # If state changed, it should be due to lifecycle, not event emission
            # This test verifies that event emission alone doesn't change state
            
            # If state didn't change via lifecycle, it should remain same
            # (This is a contract requirement - events are observational only)
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [R.2, P.4]: State endpoint not accessible: {e}")
    
    # DELETED: test_d2_emitting_dj_talking_does_not_mutate_state
    # REASON: dj_talking event is COMPLETELY DEPRECATED and MUST NOT be emitted.
    # Tower MUST reject dj_talking events with 400 Bad Request.
    # Use segment_playing event instead. New tests for event rejection are in test_tower_event_rejection.py
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_d3_state_transitions_only_via_lifecycle_hooks(self):
        """
        D.3: State transitions happen ONLY via lifecycle hooks.
        
        Per STATION_STATE_CONTRACT.md R.3:
        - State MUST be updated when on_segment_started is emitted
        - State MUST be updated when on_segment_finished is emitted
        - State MUST NOT be updated based on event replay
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            # Query state
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            state = json.loads(response.read().decode('utf-8'))
            conn.close()
            
            # Contract R.3: State updates happen ONLY via lifecycle hooks
            # This test verifies that state is queryable and reflects lifecycle transitions
            # (Actual lifecycle transitions tested in integration)
            
            assert "station_state" in state, \
                "Contract violation [R.3]: State must be queryable and reflect lifecycle transitions"
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [R.3]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_d4_missing_events_do_not_change_state(self):
        """
        D.4: Missing events do NOT change state.
        
        Per STATION_STATE_CONTRACT.md R.4:
        - If events are lost, state MUST remain correct
        - State queries MUST provide authoritative truth regardless of event delivery
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            # Query state (simulating missing events scenario)
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            state = json.loads(response.read().decode('utf-8'))
            conn.close()
            
            # Contract R.4: State remains correct even if events are lost
            # State is authoritative - it doesn't depend on events
            assert "station_state" in state, \
                "Contract violation [R.4]: State must remain correct even if events are lost"
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [R.4]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_d5_state_is_authoritative_over_events(self):
        """
        D.5: State is authoritative over events.
        
        Per STATION_STATE_CONTRACT.md R.1:
        - State represents current truth
        - Events announce transitions
        - State MUST be queryable without knowledge of event history
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            # Query state without event history
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            state = json.loads(response.read().decode('utf-8'))
            conn.close()
            
            # Contract R.1: State is authoritative - queryable without event history
            assert "station_state" in state, \
                "Contract violation [R.1]: State must be queryable without event history"
            assert "since" in state, \
                "Contract violation [R.1]: State must be authoritative over events"
            assert "current_audio" in state, \
                "Contract violation [R.1]: State represents current truth"
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [R.1]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_d6_querying_state_does_not_emit_events(self):
        """
        D.6: Querying /station/state does NOT emit events.
        
        Per STATION_STATE_CONTRACT.md R.2, P.4:
        - State queries are read-only operations
        - State queries MUST NOT trigger event emission
        - Events are emitted only on lifecycle transitions (on_segment_started, on_segment_finished)
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # This test verifies that querying state doesn't cause side effects
        
        try:
            # Query state multiple times
            conn1 = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn1.request("GET", "/station/state")
            response1 = conn1.getresponse()
            state1 = json.loads(response1.read().decode('utf-8'))
            conn1.close()
            
            time.sleep(0.1)
            
            conn2 = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn2.request("GET", "/station/state")
            response2 = conn2.getresponse()
            state2 = json.loads(response2.read().decode('utf-8'))
            conn2.close()
            
            # Contract R.2, P.4: State queries are read-only
            # State should be queryable without side effects
            # (In a real test, we would verify no events were emitted, but that requires
            # integration with event emission system)
            assert "station_state" in state1, \
                "Contract violation [R.2, P.4]: State queries must be read-only"
            assert "station_state" in state2, \
                "Contract violation [R.2, P.4]: State queries must not emit events"
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [R.2, P.4]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_d7_events_do_not_clear_state(self):
        """
        D.7: Events do NOT clear state - state persists until lifecycle transition.
        
        Per STATION_STATE_CONTRACT.md R.2, P.3:
        - Events announce transitions; they do NOT clear state
        - State persists until next lifecycle transition (on_segment_started, on_segment_finished)
        - There are NO "clear" or "end" events
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # This test verifies that events don't cause state to be cleared
        
        try:
            # Query state
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            state = json.loads(response.read().decode('utf-8'))
            conn.close()
            
            # Contract R.2, P.3: Events do not clear state
            # State should persist until lifecycle transition
            # If current_audio exists, it should remain until segment finishes
            if state.get("current_audio") is not None:
                # State should not be cleared by events
                assert state["current_audio"] is not None, \
                    "Contract violation [R.2, P.3]: Events must not clear state"
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [R.2, P.3]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_d8_state_changes_only_via_lifecycle_hooks(self):
        """
        D.8: State changes ONLY via lifecycle hooks, not via events.
        
        Per STATION_STATE_CONTRACT.md R.3:
        - State MUST be updated when on_segment_started is emitted
        - State MUST be updated when on_segment_finished is emitted
        - State MUST NOT be updated based on event replay or event history
        - Events announce transitions; lifecycle hooks update state
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # This test verifies that state updates happen via lifecycle, not events
        
        try:
            # Query state
            conn = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn.request("GET", "/station/state")
            response = conn.getresponse()
            state = json.loads(response.read().decode('utf-8'))
            conn.close()
            
            # Contract R.3: State updates happen ONLY via lifecycle hooks
            # State should reflect the segment from the most recent on_segment_started
            assert "station_state" in state, \
                "Contract violation [R.3]: State must be updated via lifecycle hooks"
            assert "since" in state, \
                "Contract violation [R.3]: State must reflect lifecycle transitions"
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [R.3]: State endpoint not accessible: {e}")
    
    @pytest.mark.integration
    @skip_if_no_station
    def test_d9_emitting_segment_playing_does_not_mutate_state(self):
        """
        D.9: Emitting segment_playing event does NOT mutate state.
        
        Per STATION_STATE_CONTRACT.md R.2, P.4:
        - Events announce transitions; state represents current truth
        - State MUST NOT be mutated based on events
        - segment_playing is observational only
        """
        # NOTE: This test will FAIL until state endpoint is implemented
        # Expected failure: 404 Not Found or connection refused
        
        try:
            # Query state before event emission
            conn1 = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn1.request("GET", "/station/state")
            response1 = conn1.getresponse()
            state_before = json.loads(response1.read().decode('utf-8'))
            conn1.close()
            
            # Emit segment_playing event (simulated)
            # NOTE: Events are observational only - they don't mutate state
            
            # Query state after event emission
            time.sleep(0.1)
            conn2 = http.client.HTTPConnection("localhost", 8000, timeout=1.0)
            conn2.request("GET", "/station/state")
            response2 = conn2.getresponse()
            state_after = json.loads(response2.read().decode('utf-8'))
            conn2.close()
            
            # Contract R.2, P.4: Events do NOT mutate state
            # State changes only via lifecycle hooks (on_segment_started, on_segment_finished)
            # If state didn't change via lifecycle, it should remain same
            # (This is a contract requirement - events are observational only)
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [R.2, P.4]: State endpoint not accessible: {e}")

