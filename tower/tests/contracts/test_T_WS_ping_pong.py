"""
Contract tests for T-WS5: Ping/Pong Support

See docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md section T-WS

T-WS5: TowerRuntime MUST respond to ping frames from clients with pong frames per RFC6455.
- TowerRuntime MUST respond to incoming ping frames with pong frames (RFC6455 requirement)
- TowerRuntime MAY send periodic ping frames to clients for connection liveness (optional)
- Ping/pong frames MUST NOT be considered data frames for event delivery purposes
"""

"""
Contract tests for T-WS5: Ping/Pong Support

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


class TestWSPingPong:
    """Tests for T-WS5: Ping/Pong Support."""
    
    def test_t_ws5_ping_triggers_pong(self):
        """
        Test T-WS5: RFC6455 ping->pong handling and no disconnect on ping.
        
        Steps:
        - Start Tower
        - Connect to /tower/events
        - Send a WebSocket ping frame
        - Assert:
          - connection remains open
          - no disconnect occurs
          - client library receives pong or at minimum ping does not cause close
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
            
            # Connection established - send ping frame
            # WebSocket ping frame format: FIN=1, opcode=0x9, masked=1 (client->server), payload
            ping_payload = b"test_ping"
            ping_frame = bytes([
                0x89,  # FIN=1, opcode=0x9 (ping)
                0x80 | len(ping_payload),  # mask=1, payload_len
            ])
            # Add mask key (4 bytes) - for testing, use simple mask
            mask_key = b"\x00\x00\x00\x00"
            ping_frame += mask_key
            # Mask payload
            masked_payload = bytes(ping_payload[i] ^ mask_key[i % 4] for i in range(len(ping_payload)))
            ping_frame += masked_payload
            
            # Send ping
            sock.sendall(ping_frame)
            
            # Wait for pong response (should be immediate)
            sock.settimeout(2.0)
            buffer = b''
            pong_received = False
            start_time = time.time()
            
            while time.time() - start_time < 2.0:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk
                    
                    # Try to decode WebSocket frame
                    if len(buffer) >= 2:
                        opcode, payload, consumed = decode_websocket_frame(buffer)
                        if opcode is not None:
                            buffer = buffer[consumed:]
                            if opcode == 0xA:  # Pong frame
                                # Verify pong contains same payload as ping
                                assert payload == ping_payload, "Pong payload should match ping payload"
                                pong_received = True
                                break
                            elif opcode == 0x8:  # Close frame
                                pytest.fail("Received close frame after ping - connection should remain open")
                except socket.timeout:
                    break
                except Exception as e:
                    pytest.fail(f"Error receiving pong: {e}")
            
            # Assert pong was received
            assert pong_received, "Pong frame not received in response to ping"
            
            # Assert connection is still open after ping/pong
            # Try to send another ping to verify connection is still alive
            time.sleep(0.1)  # Brief wait
            try:
                sock.sendall(ping_frame)
                sock.settimeout(1.0)
                response = sock.recv(10)
                # Should receive another pong
                assert len(response) >= 2, "Connection should still be open"
            except (OSError, ConnectionError, BrokenPipeError) as e:
                pytest.fail(f"Connection closed after ping/pong: {e}")
            
            sock.close()
            
        finally:
            # Terminate Tower process
            try:
                process.terminate()
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
