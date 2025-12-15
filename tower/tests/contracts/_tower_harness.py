"""
Test harness for TowerRuntime contract tests.

See docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md

Responsibilities:
- Choose a free TCP port
- Start Tower in a subprocess with required env vars
- Wait until http://127.0.0.1:<port>/tower/buffer responds 200
- Yield (process, port)
- Terminate process on teardown
"""

import socket
import subprocess
import time
import os
import sys
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def wait_for_server(host: str, port: int, path: str = "/tower/buffer", timeout: float = 10.0) -> bool:
    """
    Wait until the server responds with 200 to a request.
    
    Args:
        host: Server hostname
        port: Server port
        path: Path to check (default: /tower/buffer)
        timeout: Maximum time to wait in seconds
    
    Returns:
        True if server responds 200, False if timeout
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            # Use raw socket to send HTTP request
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect((host, port))
            
            # Send HTTP GET request
            request = f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n"
            sock.sendall(request.encode('utf-8'))
            
            # Read response
            response_data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b'\r\n\r\n' in response_data:
                    break
            
            sock.close()
            
            # Parse status line
            if response_data:
                status_line = response_data.split(b'\r\n')[0].decode('utf-8', errors='ignore')
                if '200' in status_line:
                    return True
        except (ConnectionRefusedError, OSError, socket.timeout):
            pass
        except Exception:
            # Any other exception means server might be starting
            pass
        time.sleep(0.1)
    return False


def start_tower() -> Tuple[subprocess.Popen, int]:
    """
    Start Tower in a subprocess and wait for it to be ready.
    
    Returns:
        Tuple of (process, port)
    
    Raises:
        RuntimeError: If Tower fails to start or become ready
    """
    # Find project root (go up from tests/contracts/ to project root)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    
    # Choose a free port
    port = find_free_port()
    host = "127.0.0.1"
    
    # Set up environment
    env = os.environ.copy()
    env["TOWER_HOST"] = host
    env["TOWER_PORT"] = str(port)
    env["TOWER_ENCODER_ENABLED"] = "0"  # Disable encoder for tests
    env["TOWER_TEST_MODE"] = "1"  # Test mode
    env["TOWER_LOG_LEVEL"] = "WARNING"  # Reduce log noise
    # Use a unique socket path for tests to avoid conflicts
    import tempfile
    test_socket_dir = tempfile.mkdtemp(prefix="tower_test_")
    test_socket_path = os.path.join(test_socket_dir, f"pcm_{port}.sock")
    env["TOWER_PCM_SOCKET_PATH"] = test_socket_path
    
    # Start Tower as subprocess
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "tower"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=project_root
        )
    except Exception as e:
        raise RuntimeError(f"Failed to start Tower: {e}")
    
    # Wait for server to be ready (must respond 200 to /tower/buffer)
    if not wait_for_server(host, port, timeout=10.0):
        # Clean up process
        try:
            process.terminate()
            process.wait(timeout=2.0)
        except Exception:
            process.kill()
        raise RuntimeError(f"Tower failed to become ready within 10 seconds")
    
    return (process, port)

