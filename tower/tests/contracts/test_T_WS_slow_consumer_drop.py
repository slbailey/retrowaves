"""
Contract tests for T-WS4: Slow-Consumer Drop Semantics

See docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md section T-WS

T-WS4: Slow-consumer detection and disconnection MUST apply only when an actual send operation stalls.
- A client MUST be considered slow only when a non-blocking send operation fails or indicates the socket buffer is full
- A client MUST NOT be disconnected based solely on connection age or idle time
- A client MUST be disconnected if a send operation cannot complete within a bounded timeout (implementation-defined, typically ≤250ms for send operations)
- Slow-consumer drop MUST NOT affect other clients
"""

import pytest
import time
import subprocess
import json
import sys
import os
import socket
import threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from tests.contracts._tower_harness import start_tower
from tower.tests.websocket_client import (
    create_websocket_upgrade_request,
    read_websocket_response,
    read_websocket_messages,
)


class TestWSSlowConsumerDrop:
    """Tests for T-WS4: Slow-Consumer Drop Semantics."""
    
    def test_t_ws4_slow_consumer_dropped_only_on_send_stall(self):
        """
        Test T-WS4: slow-consumer drop only on actual send stall.
        
        Steps:
        - Start Tower
        - Connect two WS clients:
          - good client continuously reads messages
          - bad client NEVER reads (causes real socket backpressure)
        - Trigger multiple broadcasts with large payloads to fill bad client's send buffer
        - Assert:
          - bad client is disconnected AFTER broadcast attempts (not during idle)
          - good client remains connected and receives events
          - no client is disconnected before broadcasts occur
        """
        process, port = start_tower()
        try:
            # Connect good client (will continuously read messages)
            good_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            good_sock.settimeout(5.0)
            # Ensure TCP_NODELAY is disabled for proper backpressure behavior
            good_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 0)
            good_sock.connect(("127.0.0.1", port))
            
            good_request, good_key = create_websocket_upgrade_request(
                "/tower/events",
                host="127.0.0.1",
                port=port
            )
            good_sock.sendall(good_request)
            good_status, good_headers, good_body = read_websocket_response(good_sock, timeout=2.0)
            assert good_status == 101, "Good client should connect successfully"
            
            # Start good client reading in background thread
            good_messages = []
            good_reading = threading.Event()
            good_reading.set()
            
            def good_client_reader():
                """Continuously read from good client socket."""
                good_sock.settimeout(1.0)
                while good_reading.is_set():
                    try:
                        data = good_sock.recv(4096)
                        if not data:
                            break
                        # Try to decode WebSocket frames
                        try:
                            from tower.tests.websocket_client import decode_websocket_frame
                            buffer = data
                            while len(buffer) >= 2:
                                opcode, payload, consumed = decode_websocket_frame(buffer)
                                if opcode is None:
                                    break
                                if opcode == 0x1:  # Text frame
                                    try:
                                        msg = json.loads(payload.decode('utf-8'))
                                        good_messages.append(msg)
                                    except Exception:
                                        pass
                                buffer = buffer[consumed:]
                        except Exception:
                            pass
                    except socket.timeout:
                        continue
                    except (OSError, ConnectionError, BrokenPipeError):
                        break
            
            good_thread = threading.Thread(target=good_client_reader, daemon=True)
            good_thread.start()
            
            # Connect bad client (will NEVER read - causes real socket backpressure)
            bad_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            bad_sock.settimeout(5.0)
            # Ensure TCP_NODELAY is disabled for proper backpressure behavior
            bad_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 0)
            bad_sock.connect(("127.0.0.1", port))
            
            bad_request, bad_key = create_websocket_upgrade_request(
                "/tower/events",
                host="127.0.0.1",
                port=port
            )
            bad_sock.sendall(bad_request)
            bad_status, bad_headers, bad_body = read_websocket_response(bad_sock, timeout=2.0)
            assert bad_status == 101, "Bad client should connect successfully"
            
            # Bad client: DO NOT read - this causes real socket buffer to fill
            # The socket buffer will fill as server sends events, causing send stall
            
            # Both clients connected - wait a bit to ensure they're not dropped during idle
            time.sleep(1.0)
            
            # Verify both clients are still connected (idle period should not disconnect)
            try:
                bad_sock.settimeout(0.1)
                # Try to peek - should timeout (socket open but no data read) or raise if closed
                try:
                    data = bad_sock.recv(1, socket.MSG_PEEK)
                    if data == b'':
                        pytest.fail("Bad client disconnected during idle period (should not happen)")
                except socket.timeout:
                    # Timeout is expected - socket is open, just no data read
                    pass
            except (OSError, ConnectionError, BrokenPipeError):
                pytest.fail("Bad client disconnected during idle period (should not happen)")
            
            # Trigger multiple broadcasts with large payloads to fill bad client's send buffer
            # Large payloads (2-4KB each) will fill the socket buffer faster
            # Multiple broadcasts ensure buffer fills before server can detect stall
            for i in range(50):
                event_data = {
                    "event_type": "now_playing",
                    "timestamp": time.time(),
                    "metadata": {
                        "test": "slow_consumer",
                        "seq": i,
                        "large_payload": "x" * 3000  # 3KB payload to fill buffer faster
                    }
                }
                event_json = json.dumps(event_data)
                http_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                http_sock.settimeout(5.0)
                http_sock.connect(("127.0.0.1", port))
                request = (
                    f"POST /__test__/broadcast HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{port}\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(event_json)}\r\n"
                    f"Connection: close\r\n"
                    f"\r\n"
                    f"{event_json}"
                )
                http_sock.sendall(request.encode('utf-8'))
                
                # Read response
                response_data = b''
                while True:
                    chunk = http_sock.recv(4096)
                    if not chunk:
                        break
                    response_data += chunk
                    if b'\r\n\r\n' in response_data:
                        break
                http_sock.close()
                # Check status (should be 200)
                if response_data:
                    status_line = response_data.split(b'\r\n')[0].decode('utf-8', errors='ignore')
                    assert '200' in status_line, f"Broadcast endpoint should succeed, got: {status_line}"
                
                # Small delay to allow buffer to accumulate
                time.sleep(0.02)
            
            # Wait for broadcast to attempt delivery and slow consumer to be detected
            # The server's select.select() will detect socket as non-writable when buffer fills
            # Poll for disconnect with timeout
            bad_disconnected = False
            start_check = time.time()
            check_timeout = 3.0  # Give up after 3 seconds
            
            while time.time() - start_check < check_timeout:
                try:
                    bad_sock.settimeout(0.1)
                    # Try to read - server may have sent a close frame
                    data = bad_sock.recv(1024)
                    if data == b'':
                        # Empty data means connection closed
                        bad_disconnected = True
                        break
                    elif len(data) >= 2:
                        # Check if it's a close frame (opcode 0x8)
                        opcode = data[0] & 0x0F
                        if opcode == 0x8:
                            bad_disconnected = True
                            break
                except (OSError, ConnectionError, BrokenPipeError) as e:
                    # Socket error means connection was closed
                    bad_disconnected = True
                    break
                except socket.timeout:
                    # Timeout - connection might still be open, check by trying to send
                    try:
                        bad_sock.send(b'\x89\x00')  # Try to send ping
                    except (OSError, ConnectionError, BrokenPipeError):
                        bad_disconnected = True
                        break
                    # If send succeeded, connection is still open - wait a bit more
                    time.sleep(0.1)
            
            assert bad_disconnected, "Bad client should be disconnected after send stall"
            
            # Stop good client reading thread
            good_reading.clear()
            good_thread.join(timeout=1.0)
            
            # Verify good client is still connected and received events
            good_sock.settimeout(1.0)
            
            # Good client should have received events
            event_received = False
            for msg in good_messages:
                if isinstance(msg, dict) and msg.get("event_type") == "now_playing":
                    event_received = True
                    break
            
            assert event_received, "Good client should receive the broadcast event"
            
            # Verify good client is still connected
            try:
                good_sock.settimeout(0.1)
                # Socket should still be open
                data = good_sock.recv(1, socket.MSG_PEEK)
                # If we get here without exception, socket is still open
            except socket.timeout:
                # Timeout is fine - socket is open, just no more data
                pass
            except (OSError, ConnectionError, BrokenPipeError):
                pytest.fail("Good client should remain connected")
            
            good_sock.close()
            try:
                bad_sock.close()
            except Exception:
                pass  # May already be closed
            
        finally:
            # Terminate Tower process
            try:
                process.terminate()
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
