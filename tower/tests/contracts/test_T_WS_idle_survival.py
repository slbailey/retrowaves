"""
Contract tests for T-WS2: Idle Connection Survival

See docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md section T-WS

T-WS2: TowerRuntime MUST allow WebSocket connections to remain idle
(no data frames sent) for extended periods.
- Idle connections MUST NOT be disconnected based solely on lack of data transfer
- Idle connections MAY remain open indefinitely as long as the connection is healthy
"""

"""
Contract tests for T-WS2: Idle Connection Survival

See docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md section T-WS
"""

import pytest
import time
import subprocess
import sys
import os
import socket
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from tests.contracts._tower_harness import start_tower
from tower.tests.websocket_client import (
    create_websocket_upgrade_request,
    read_websocket_response,
    decode_websocket_frame,
)


class TestWSIdleSurvival:
    """Tests for T-WS2: Idle Connection Survival."""
    
    def test_t_ws2_idle_connection_remains_open(self):
        """
        Test T-WS2: A quiet WebSocket subscriber stays connected.
        
        Steps:
        - Start Tower via harness
        - Connect to ws://127.0.0.1:<port>/tower/events
        - Do not send or receive events
        - Sleep ~5 seconds
        - Assert:
          - connection is still open
          - ping() does not raise
          - no close callback fired
        """
        process, port = start_tower()
        try:
            # Connect WebSocket using raw socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(("127.0.0.1", port))
            
            # Send WebSocket upgrade request
            request, key = create_websocket_upgrade_request(
                "/tower/events",
                host="127.0.0.1",
                port=port
            )
            sock.sendall(request)
            
            # Read upgrade response
            status_code, headers, body = read_websocket_response(sock, timeout=2.0)
            assert status_code == 101, f"Expected 101 Switching Protocols, got {status_code}"
            assert "upgrade" in headers.get("connection", "").lower()
            assert "websocket" in headers.get("upgrade", "").lower()
            
            # Connection is now established - stay idle for ~5 seconds
            start_time = time.time()
            idle_duration = 5.0
            
            while time.time() - start_time < idle_duration:
                # Verify connection is still open by checking socket
                try:
                    sock.settimeout(0.1)
                    # Try to peek at socket (this will timeout if no data, which is fine)
                    data = sock.recv(1, socket.MSG_PEEK)
                    if data == b'':
                        pytest.fail("WebSocket connection was closed during idle period")
                except socket.timeout:
                    # Timeout is expected - socket is still open, just no data
                    pass
                except (OSError, ConnectionError, BrokenPipeError):
                    pytest.fail("WebSocket connection was closed during idle period")
                time.sleep(0.1)
            
            # After idle period, verify connection is still open
            # Send a ping frame to verify connection is still alive
            # WebSocket ping frame: FIN=1, opcode=0x9, payload empty
            ping_frame = bytes([0x89, 0x00])  # FIN=1, opcode=0x9, no mask, empty payload
            try:
                sock.sendall(ping_frame)
                # Wait briefly for pong response
                sock.settimeout(1.0)
                response = sock.recv(10)
                # Should receive pong frame (opcode 0xA)
                assert len(response) >= 2, "Expected pong response"
                assert (response[0] & 0x0F) == 0xA, "Expected pong opcode (0xA)"
            except (OSError, ConnectionError, BrokenPipeError, socket.timeout) as e:
                pytest.fail(f"Connection not alive after idle period: {e}")
            
            sock.close()
            
        finally:
            # Terminate Tower process
            try:
                process.terminate()
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
