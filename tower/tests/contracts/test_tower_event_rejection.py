"""
Contract tests for NEW_TOWER_RUNTIME_CONTRACT.md - Event Rejection

See tower/docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1, T-EVENTS7

PHASE 2: Tests only - these tests MUST FAIL until Phase 3 implementation.

Category E: Forbidden Event Rejection Tests
- Tower MUST reject now_playing events
- Tower MUST reject station_starting_up events
- Tower MUST reject station_shutting_down events
- Tower MUST reject dj_talking events (DEPRECATED - use segment_playing)
- Tower MUST reject unknown event types
- Tower MUST accept segment_playing events (with required metadata)
- Tower MUST reject segment_playing events missing required metadata
"""

import pytest
import time
import http.client
import json
import threading

from tower.service import TowerService


class TestE_ForbiddenEventRejection:
    """Category E: Forbidden Event Rejection Tests (T-EVENTS1, T-EVENTS7)."""
    
    @pytest.fixture
    def service(self):
        """Create TowerService instance for testing with cleanup."""
        service = TowerService(encoder_enabled=False)
        yield service
        try:
            service.stop()
            if hasattr(service, 'audio_pump') and service.audio_pump is not None:
                if hasattr(service.audio_pump, 'thread'):
                    service.audio_pump.thread.join(timeout=2.0)
                elif hasattr(service.audio_pump, '_thread'):
                    service.audio_pump._thread.join(timeout=2.0)
        except Exception:
            pass
        del service
    
    def test_e1_tower_rejects_now_playing(self, service):
        """
        E.1: Tower MUST reject now_playing events with validation error.
        
        Per NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1, T-EVENTS7:
        - now_playing is DEPRECATED and FORBIDDEN
        - Tower MUST reject with validation error
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send deprecated now_playing event
            deprecated_event = {
                "event_type": "now_playing",
                "timestamp": time.monotonic(),
                "metadata": {
                    "segment_type": "song",
                    "file_path": "/path/to/file.mp3",
                    "started_at": time.time()
                }
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(deprecated_event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract T-EVENTS7: Tower MUST reject deprecated events with validation error
            # Expected: 400 Bad Request or similar validation error
            assert response.status == 400, \
                f"Contract violation [T-EVENTS7]: Tower MUST reject now_playing events with validation error. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [T-EVENTS7]: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    def test_e2_tower_rejects_station_starting_up(self, service):
        """
        E.2: Tower MUST reject station_starting_up events with validation error.
        
        Per NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1, T-EVENTS7:
        - station_starting_up is DEPRECATED and FORBIDDEN
        - Tower MUST reject with validation error
        - New event type is station_startup (without "_ing")
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send deprecated station_starting_up event
            deprecated_event = {
                "event_type": "station_starting_up",
                "timestamp": time.monotonic(),
                "metadata": {}
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(deprecated_event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract T-EVENTS7: Tower MUST reject deprecated events with validation error
            assert response.status == 400, \
                f"Contract violation [T-EVENTS7]: Tower MUST reject station_starting_up events with validation error. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [T-EVENTS7]: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    def test_e3_tower_rejects_station_shutting_down(self, service):
        """
        E.3: Tower MUST reject station_shutting_down events with validation error.
        
        Per NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1, T-EVENTS7:
        - station_shutting_down is DEPRECATED and FORBIDDEN
        - Tower MUST reject with validation error
        - New event type is station_shutdown (without "_ing")
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send deprecated station_shutting_down event
            deprecated_event = {
                "event_type": "station_shutting_down",
                "timestamp": time.monotonic(),
                "metadata": {}
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(deprecated_event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract T-EVENTS7: Tower MUST reject deprecated events with validation error
            assert response.status == 400, \
                f"Contract violation [T-EVENTS7]: Tower MUST reject station_shutting_down events with validation error. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [T-EVENTS7]: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    def test_e4_tower_rejects_dj_talking(self, service):
        """
        E.4: Tower MUST reject dj_talking events with validation error.
        
        Per NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1, T-EVENTS7:
        - dj_talking is DEPRECATED and FORBIDDEN
        - Tower MUST reject with validation error (400 Bad Request)
        - Use segment_playing with segment_class="dj_talk" instead
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send deprecated dj_talking event
            deprecated_event = {
                "event_type": "dj_talking",
                "timestamp": time.monotonic(),
                "metadata": {}
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(deprecated_event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract T-EVENTS7: Tower MUST reject deprecated dj_talking events with validation error
            assert response.status == 400, \
                f"Contract violation [T-EVENTS7]: Tower MUST reject dj_talking events with validation error. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [T-EVENTS7]: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    def test_e5_tower_rejects_unknown_event_types(self, service):
        """
        E.5: Tower MUST reject unknown event types with validation error.
        
        Per NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1, T-EVENTS7:
        - Only four event types are accepted: station_startup, station_shutdown, song_playing, segment_playing
        - Any other event type MUST be rejected
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send unknown event type
            unknown_event = {
                "event_type": "unknown_event_type",
                "timestamp": time.monotonic(),
                "metadata": {}
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(unknown_event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract T-EVENTS7: Tower MUST reject unknown event types
            assert response.status == 400, \
                f"Contract violation [T-EVENTS7]: Tower MUST reject unknown event types with validation error. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [T-EVENTS7]: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    def test_e6_tower_accepts_station_startup(self, service):
        """
        E.5: Tower MUST accept station_startup events (new event type).
        
        Per NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1:
        - station_startup is the new accepted event type (replaces station_starting_up)
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send new station_startup event
            new_event = {
                "event_type": "station_startup",
                "timestamp": time.monotonic(),
                "metadata": {}
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(new_event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract T-EVENTS1: Tower MUST accept station_startup events
            # Expected: 200, 201, or 204 (not 400)
            assert response.status != 400, \
                f"Contract violation [T-EVENTS1]: Tower MUST accept station_startup events. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [T-EVENTS1]: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    def test_e7_tower_accepts_station_shutdown(self, service):
        """
        E.6: Tower MUST accept station_shutdown events (new event type).
        
        Per NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1:
        - station_shutdown is the new accepted event type (replaces station_shutting_down)
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send new station_shutdown event
            new_event = {
                "event_type": "station_shutdown",
                "timestamp": time.monotonic(),
                "metadata": {}
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(new_event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract T-EVENTS1: Tower MUST accept station_shutdown events
            assert response.status != 400, \
                f"Contract violation [T-EVENTS1]: Tower MUST accept station_shutdown events. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [T-EVENTS1]: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    def test_e8_tower_accepts_song_playing(self, service):
        """
        E.7: Tower MUST accept song_playing events (new event type).
        
        Per NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1:
        - song_playing is the new accepted event type (replaces now_playing)
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send new song_playing event
            new_event = {
                "event_type": "song_playing",
                "timestamp": time.monotonic(),
                "metadata": {
                    "segment_type": "song",
                    "file_path": "/path/to/file.mp3",
                    "started_at": time.time(),
                    "title": "Test Song",
                    "artist": "Test Artist"
                }
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(new_event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract T-EVENTS1: Tower MUST accept song_playing events
            assert response.status != 400, \
                f"Contract violation [T-EVENTS1]: Tower MUST accept song_playing events. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [T-EVENTS1]: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    def test_e9_tower_accepts_segment_playing_with_required_metadata(self, service):
        """
        E.9: Tower MUST accept segment_playing events with required metadata.
        
        Per NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1:
        - segment_playing is an accepted event type (replaces dj_talking)
        - segment_playing MUST include required metadata: segment_class, segment_role, production_type
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send segment_playing event with required metadata
            event = {
                "event_type": "segment_playing",
                "timestamp": time.monotonic(),
                "metadata": {
                    "segment_class": "dj_talk",
                    "segment_role": "interstitial",
                    "production_type": "live_dj"
                }
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract T-EVENTS1: Tower MUST accept segment_playing events with required metadata
            # NOTE: This test will FAIL until Phase 3 implementation
            # Expected failure: 400 Bad Request (Tower doesn't yet accept segment_playing)
            assert response.status != 400, \
                f"Contract violation [T-EVENTS1]: Tower MUST accept segment_playing events with required metadata. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [T-EVENTS1]: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    @pytest.mark.xfail(reason="Tower treats metadata as opaque per NEW_TOWER_RUNTIME_CONTRACT T-EVENTS3.4; metadata validation is Station-only")
    def test_e10_tower_rejects_segment_playing_missing_segment_class(self, service):
        """
        E.10: Tower MUST reject segment_playing events missing segment_class.
        
        NOTE: This test is marked xfail because Tower treats metadata as opaque per
        NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS3.4. Metadata validation is Station-only.
        Tower only validates event_type and broadcasts metadata verbatim.
        
        Per EVENT_INVENTORY.md and NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1:
        - segment_playing MUST include required metadata: segment_class, segment_role, production_type
        - Missing segment_class MUST be rejected (by Station, not Tower)
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send segment_playing event missing segment_class
            event = {
                "event_type": "segment_playing",
                "timestamp": time.monotonic(),
                "metadata": {
                    # Missing segment_class
                    "segment_role": "interstitial",
                    "production_type": "live_dj"
                }
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract: Tower MUST reject segment_playing missing required metadata
            # NOTE: This test will FAIL until Phase 3 implementation
            # Expected failure: Tower doesn't yet validate segment_playing metadata
            assert response.status == 400, \
                f"Contract violation: Tower MUST reject segment_playing missing segment_class. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    @pytest.mark.xfail(reason="Tower treats metadata as opaque per NEW_TOWER_RUNTIME_CONTRACT T-EVENTS3.4; metadata validation is Station-only")
    def test_e11_tower_rejects_segment_playing_missing_segment_role(self, service):
        """
        E.11: Tower MUST reject segment_playing events missing segment_role.
        
        NOTE: This test is marked xfail because Tower treats metadata as opaque per
        NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS3.4. Metadata validation is Station-only.
        Tower only validates event_type and broadcasts metadata verbatim.
        
        Per EVENT_INVENTORY.md and NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1:
        - segment_playing MUST include required metadata: segment_class, segment_role, production_type
        - Missing segment_role MUST be rejected (by Station, not Tower)
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send segment_playing event missing segment_role
            event = {
                "event_type": "segment_playing",
                "timestamp": time.monotonic(),
                "metadata": {
                    "segment_class": "dj_talk",
                    # Missing segment_role
                    "production_type": "live_dj"
                }
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract: Tower MUST reject segment_playing missing required metadata
            # NOTE: This test will FAIL until Phase 3 implementation
            assert response.status == 400, \
                f"Contract violation: Tower MUST reject segment_playing missing segment_role. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    @pytest.mark.xfail(reason="Tower treats metadata as opaque per NEW_TOWER_RUNTIME_CONTRACT T-EVENTS3.4; metadata validation is Station-only")
    def test_e12_tower_rejects_segment_playing_missing_production_type(self, service):
        """
        E.12: Tower MUST reject segment_playing events missing production_type.
        
        NOTE: This test is marked xfail because Tower treats metadata as opaque per
        NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS3.4. Metadata validation is Station-only.
        Tower only validates event_type and broadcasts metadata verbatim.
        
        Per EVENT_INVENTORY.md and NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS1:
        - segment_playing MUST include required metadata: segment_class, segment_role, production_type
        - Missing production_type MUST be rejected (by Station, not Tower)
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send segment_playing event missing production_type
            event = {
                "event_type": "segment_playing",
                "timestamp": time.monotonic(),
                "metadata": {
                    "segment_class": "dj_talk",
                    "segment_role": "interstitial"
                    # Missing production_type
                }
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract: Tower MUST reject segment_playing missing required metadata
            # NOTE: This test will FAIL until Phase 3 implementation
            assert response.status == 400, \
                f"Contract violation: Tower MUST reject segment_playing missing production_type. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)
    
    @pytest.mark.xfail(reason="Tower treats metadata as opaque per NEW_TOWER_RUNTIME_CONTRACT T-EVENTS3.4; metadata validation is Station-only")
    def test_e13_tower_rejects_empty_metadata_events(self, service):
        """
        E.13: Tower MUST NOT accept empty metadata events to signal "end of segment".
        
        NOTE: This test is marked xfail because Tower treats metadata as opaque per
        NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS3.4. Metadata validation is Station-only.
        Tower only validates event_type and broadcasts metadata verbatim.
        
        Per NEW_TOWER_RUNTIME_CONTRACT.md T-EVENTS3:
        - Events MUST NOT include empty metadata to signal "end of segment"
        - Events are edge-triggered transitions only (no "end" or "clear" events)
        - However, Tower does not validate metadata content (Station enforces this)
        """
        # Start HTTP server
        import random
        test_port = random.randint(8001, 9000)
        service.http_server.port = test_port
        
        server_thread = threading.Thread(target=service.http_server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.2)
        
        try:
            conn = http.client.HTTPConnection("localhost", test_port, timeout=2.0)
            
            # Send event with empty metadata (attempting to signal "end of segment")
            empty_metadata_event = {
                "event_type": "song_playing",
                "timestamp": time.monotonic(),
                "metadata": {}  # Empty metadata - should be rejected
            }
            
            conn.request("POST", "/tower/events/ingest",
                        json.dumps(empty_metadata_event).encode('utf-8'),
                        {"Content-Type": "application/json"})
            response = conn.getresponse()
            
            # Contract T-EVENTS3: Tower MUST NOT accept empty metadata events
            # For song_playing, metadata should include at least segment_type, file_path, started_at
            # Empty metadata should be rejected
            assert response.status == 400, \
                f"Contract violation [T-EVENTS3]: Tower MUST reject empty metadata events. Got {response.status}"
            
            response.read()
            conn.close()
            
        except (ConnectionRefusedError, OSError) as e:
            pytest.fail(f"Contract violation [T-EVENTS3]: Event ingestion endpoint not accessible: {e}")
        finally:
            service.http_server.stop()
            server_thread.join(timeout=1.0)

