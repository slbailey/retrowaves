"""
WebSocket client helper for testing WebSocket endpoints.
"""

import base64
import hashlib
import struct
import socket
import time
from typing import Optional, Tuple, List

# WebSocket magic string per RFC 6455
WEBSOCKET_MAGIC_STRING = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def generate_websocket_key() -> str:
    """Generate a random WebSocket key for testing."""
    import random
    key_bytes = bytes([random.randint(0, 255) for _ in range(16)])
    return base64.b64encode(key_bytes).decode('utf-8')


def generate_accept_key(sec_websocket_key: str) -> str:
    """Generate WebSocket accept key."""
    key = sec_websocket_key + WEBSOCKET_MAGIC_STRING
    sha1 = hashlib.sha1(key.encode('utf-8')).digest()
    return base64.b64encode(sha1).decode('utf-8')


def create_websocket_upgrade_request(path: str, host: str = "localhost", port: int = 8005, key: Optional[str] = None) -> bytes:
    """Create a WebSocket upgrade HTTP request."""
    if key is None:
        key = generate_websocket_key()
    
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    return request.encode('utf-8'), key


def decode_websocket_frame(data: bytes) -> Tuple[Optional[int], Optional[bytes], int]:
    """Decode a WebSocket frame."""
    if len(data) < 2:
        return None, None, 0
    
    first_byte = data[0]
    second_byte = data[1]
    
    fin = (first_byte >> 7) & 0x01
    opcode = first_byte & 0x0F
    masked = (second_byte >> 7) & 0x01
    payload_len = second_byte & 0x7F
    
    header_len = 2
    if payload_len == 126:
        if len(data) < 4:
            return None, None, 0
        payload_len = struct.unpack('!H', data[2:4])[0]
        header_len = 4
    elif payload_len == 127:
        if len(data) < 10:
            return None, None, 0
        payload_len = struct.unpack('!Q', data[2:10])[0]
        header_len = 10
    
    mask_key = None
    if masked:
        if len(data) < header_len + 4:
            return None, None, 0
        mask_key = data[header_len:header_len + 4]
        header_len += 4
    
    if len(data) < header_len + payload_len:
        return None, None, 0
    
    payload = data[header_len:header_len + payload_len]
    
    if masked and mask_key:
        payload = bytes(payload[i] ^ mask_key[i % 4] for i in range(len(payload)))
    
    return opcode, payload, header_len + payload_len


def read_websocket_response(sock: socket.socket, timeout: float = 2.0) -> Tuple[int, dict, bytes]:
    """Read HTTP upgrade response."""
    sock.settimeout(timeout)
    response_data = b''
    
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_data += chunk
            
            # Check if we have complete HTTP headers
            if b'\r\n\r\n' in response_data:
                break
        except socket.timeout:
            break
    
    response_str = response_data.decode('utf-8', errors='ignore')
    lines = response_str.split('\r\n')
    
    # Parse status line
    status_line = lines[0]
    parts = status_line.split(' ', 2)
    status_code = int(parts[1]) if len(parts) > 1 else 0
    
    # Parse headers
    headers = {}
    body_start = response_data.find(b'\r\n\r\n')
    header_data = response_data[:body_start].decode('utf-8', errors='ignore')
    
    for line in header_data.split('\r\n')[1:]:
        if ':' in line:
            key, value = line.split(':', 1)
            headers[key.strip().lower()] = value.strip()
    
    body = response_data[body_start + 4:] if body_start >= 0 else b''
    
    return status_code, headers, body


def read_websocket_messages(sock: socket.socket, timeout: float = 2.0, max_messages: int = 10) -> List[dict]:
    """Read WebSocket messages from socket."""
    messages = []
    buffer = b''
    sock.settimeout(timeout)
    
    start_time = time.time()
    while len(messages) < max_messages and (time.time() - start_time) < timeout:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
            
            while len(buffer) >= 2:
                opcode, payload, consumed = decode_websocket_frame(buffer)
                if opcode is None:
                    break
                
                buffer = buffer[consumed:]
                
                if opcode == 0x1:  # Text frame
                    try:
                        import json
                        msg = json.loads(payload.decode('utf-8'))
                        messages.append(msg)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
                elif opcode == 0x8:  # Close frame
                    return messages
                # Ignore other opcodes
        except socket.timeout:
            break
        except Exception:
            break
    
    return messages





