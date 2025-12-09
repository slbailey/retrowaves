"""
WebSocket protocol handler for Tower event endpoints.

Implements basic WebSocket upgrade and frame handling per RFC 6455.
"""

import base64
import hashlib
import struct
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# WebSocket magic string per RFC 6455
WEBSOCKET_MAGIC_STRING = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketError(Exception):
    """WebSocket protocol error."""
    pass


def generate_accept_key(sec_websocket_key: str) -> str:
    """
    Generate WebSocket accept key for upgrade response.
    
    Per RFC 6455 Section 1.3: SHA-1(key + magic_string), then base64 encode.
    
    Args:
        sec_websocket_key: Client's Sec-WebSocket-Key header value
        
    Returns:
        Sec-WebSocket-Accept value
    """
    key = sec_websocket_key + WEBSOCKET_MAGIC_STRING
    sha1 = hashlib.sha1(key.encode('utf-8')).digest()
    accept = base64.b64encode(sha1).decode('utf-8')
    return accept


def parse_upgrade_request(request_str: str) -> Optional[dict]:
    """
    Parse HTTP upgrade request to extract WebSocket headers.
    
    Args:
        request_str: Raw HTTP request string
        
    Returns:
        Dictionary with headers, or None if not a valid WebSocket upgrade
    """
    lines = request_str.split('\r\n')
    if not lines:
        return None
    
    # Parse request line
    request_line = lines[0]
    parts = request_line.split()
    if len(parts) < 3:
        return None
    
    method = parts[0]
    path = parts[1]
    
    if method != "GET":
        return None
    
    # Parse headers
    headers = {}
    for line in lines[1:]:
        if not line.strip():
            break
        if ':' in line:
            key, value = line.split(':', 1)
            headers[key.strip().lower()] = value.strip()
    
    # Check if this is a WebSocket upgrade request
    if headers.get('upgrade', '').lower() != 'websocket':
        return None
    
    if headers.get('connection', '').lower() != 'upgrade':
        return None
    
    if 'sec-websocket-key' not in headers:
        return None
    
    if 'sec-websocket-version' not in headers:
        return None
    
    version = headers['sec-websocket-version']
    if version != '13':
        return None  # Only support version 13
    
    return {
        'path': path,
        'headers': headers,
        'sec-websocket-key': headers['sec-websocket-key']
    }


def create_upgrade_response(sec_websocket_key: str) -> bytes:
    """
    Create WebSocket upgrade response.
    
    Args:
        sec_websocket_key: Client's Sec-WebSocket-Key header value
        
    Returns:
        HTTP response bytes for WebSocket upgrade
    """
    accept_key = generate_accept_key(sec_websocket_key)
    
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key}\r\n"
        "\r\n"
    )
    return response.encode('ascii')


def encode_websocket_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    """
    Encode a WebSocket frame.
    
    Per RFC 6455 Section 5.2:
    - FIN bit = 1 (final frame)
    - RSV bits = 0
    - Opcode: 0x1 = text, 0x2 = binary, 0x8 = close, 0x9 = ping, 0xA = pong
    - Mask = 0 (server to client frames are not masked)
    - Payload length
    
    Args:
        payload: Frame payload bytes
        opcode: Frame opcode (0x1 = text, 0x2 = binary, etc.)
        
    Returns:
        Encoded WebSocket frame bytes
    """
    payload_len = len(payload)
    
    # Frame header: FIN (1 bit) + RSV (3 bits) + Opcode (4 bits)
    first_byte = 0x80 | (opcode & 0x0F)  # FIN = 1, RSV = 0
    
    # Frame header: MASK (1 bit) + Payload length (7 bits, or extended)
    if payload_len < 126:
        second_byte = payload_len  # MASK = 0
        frame = struct.pack('!BB', first_byte, second_byte) + payload
    elif payload_len < 65536:
        second_byte = 126  # Extended payload length (16-bit)
        frame = struct.pack('!BBH', first_byte, second_byte, payload_len) + payload
    else:
        second_byte = 127  # Extended payload length (64-bit)
        frame = struct.pack('!BBQ', first_byte, second_byte, payload_len) + payload
    
    return frame


def decode_websocket_frame(data: bytes) -> Tuple[Optional[int], Optional[bytes], int]:
    """
    Decode a WebSocket frame.
    
    Args:
        data: Raw frame bytes
        
    Returns:
        Tuple of (opcode, payload, bytes_consumed)
        Returns (None, None, 0) if frame is incomplete
    """
    if len(data) < 2:
        return None, None, 0  # Incomplete frame
    
    first_byte = data[0]
    second_byte = data[1]
    
    fin = (first_byte >> 7) & 0x01
    opcode = first_byte & 0x0F
    masked = (second_byte >> 7) & 0x01
    payload_len = second_byte & 0x7F
    
    # Extended payload length
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
    
    # Masking key (4 bytes) if present
    mask_key = None
    if masked:
        if len(data) < header_len + 4:
            return None, None, 0
        mask_key = data[header_len:header_len + 4]
        header_len += 4
    
    # Check if we have the full payload
    if len(data) < header_len + payload_len:
        return None, None, 0  # Incomplete frame
    
    # Extract payload
    payload = data[header_len:header_len + payload_len]
    
    # Unmask if necessary
    if masked and mask_key:
        payload = bytes(payload[i] ^ mask_key[i % 4] for i in range(len(payload)))
    
    return opcode, payload, header_len + payload_len


def create_close_frame(code: int = 1000, reason: str = "") -> bytes:
    """
    Create a WebSocket close frame.
    
    Args:
        code: Close status code (1000 = normal closure)
        reason: Optional close reason
        
    Returns:
        Close frame bytes
    """
    payload = struct.pack('!H', code) + reason.encode('utf-8')
    return encode_websocket_frame(payload, opcode=0x8)

