"""
Contract tests for T-BUF: Buffer Status Endpoint

See docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md section T-BUF

T-BUF1: Endpoint path MUST remain /tower/buffer for backward compatibility.
T-BUF2: Response MUST be JSON with fields:
  capacity:int, count:int, overflow_count:int, ratio:(int|float)
"""

"""
Contract tests for T-BUF: Buffer Status Endpoint

See docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md section T-BUF
"""

"""
Contract tests for T-BUF: Buffer Status Endpoint

See docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md section T-BUF
"""

import pytest
import json
import subprocess
import sys
import os
import socket
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from tests.contracts._tower_harness import start_tower


class TestBUFPathAndSchema:
    """Tests for T-BUF: Buffer Status Endpoint."""
    
    def test_t_buf1_path_is_tower_buffer(self):
        """
        Test T-BUF1: Endpoint path MUST be /tower/buffer.
        
        Steps:
        - Start Tower
        - GET http://127.0.0.1:<port>/tower/buffer
        - Assert 200 response
        - Optionally assert /tower/pcm-buffer-status is not canonical (404 or not found).
        """
        process, port = start_tower()
        try:
            # Test canonical path using raw socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(("127.0.0.1", port))
            request = f"GET /tower/buffer HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
            sock.sendall(request.encode('utf-8'))
            response_data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b'\r\n\r\n' in response_data:
                    break
            sock.close()
            status_line = response_data.split(b'\r\n')[0].decode('utf-8', errors='ignore')
            assert '200' in status_line, f"Expected 200 OK, got {status_line}"
            
            # Verify non-canonical path is not available (or returns 404)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(("127.0.0.1", port))
            request = f"GET /tower/pcm-buffer-status HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
            sock.sendall(request.encode('utf-8'))
            response_data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b'\r\n\r\n' in response_data:
                    break
            sock.close()
            status_line = response_data.split(b'\r\n')[0].decode('utf-8', errors='ignore')
            # Should be 404 (not found) or similar
            assert '404' in status_line, f"Non-canonical path should not exist (expected 404, got {status_line})"
            
        finally:
            # Terminate Tower process
            try:
                process.terminate()
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
    
    def test_t_buf2_response_schema(self):
        """
        Test T-BUF2: Response MUST be JSON with required fields.
        
        Steps:
        - Start Tower
        - GET http://127.0.0.1:<port>/tower/buffer
        - Assert 200
        - Assert JSON fields and types:
          - capacity:int
          - count:int
          - overflow_count:int
          - ratio:int|float
        """
        process, port = start_tower()
        try:
            # Use raw socket for HTTP request
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(("127.0.0.1", port))
            request = f"GET /tower/buffer HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
            sock.sendall(request.encode('utf-8'))
            response_data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b'\r\n\r\n' in response_data:
                    # Get body if present
                    header_end = response_data.find(b'\r\n\r\n')
                    if len(response_data) > header_end + 4:
                        body_data = response_data[header_end + 4:]
                        # Try to read more if Content-Length indicates more data
                        # For simplicity, assume body is in first response
                        break
            sock.close()
            
            status_line = response_data.split(b'\r\n')[0].decode('utf-8', errors='ignore')
            assert '200' in status_line, f"Expected 200 OK, got {status_line}"
            
            # Extract body
            header_end = response_data.find(b'\r\n\r\n')
            body = response_data[header_end + 4:].decode('utf-8', errors='ignore')
            
            # Parse JSON
            try:
                data = json.loads(body)
            except json.JSONDecodeError as e:
                pytest.fail(f"Response is not valid JSON: {e}")
            
            # Verify required fields exist
            assert "capacity" in data, "Response must include 'capacity' field"
            assert "count" in data, "Response must include 'count' field"
            assert "overflow_count" in data, "Response must include 'overflow_count' field"
            assert "ratio" in data, "Response must include 'ratio' field"
            
            # Verify field types
            assert isinstance(data["capacity"], int), f"'capacity' must be int, got {type(data['capacity'])}"
            assert isinstance(data["count"], int), f"'count' must be int, got {type(data['count'])}"
            assert isinstance(data["overflow_count"], int), f"'overflow_count' must be int, got {type(data['overflow_count'])}"
            assert isinstance(data["ratio"], (int, float)), f"'ratio' must be int or float, got {type(data['ratio'])}"
            
            # Verify ratio is in valid range (0-1)
            assert 0.0 <= data["ratio"] <= 1.0, f"'ratio' must be between 0 and 1, got {data['ratio']}"
            
            # Verify capacity is positive
            assert data["capacity"] > 0, f"'capacity' must be positive, got {data['capacity']}"
            
            # Verify count is non-negative
            assert data["count"] >= 0, f"'count' must be non-negative, got {data['count']}"
            
            # Verify overflow_count is non-negative
            assert data["overflow_count"] >= 0, f"'overflow_count' must be non-negative, got {data['overflow_count']}"
            
        finally:
            # Terminate Tower process
            try:
                process.terminate()
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
