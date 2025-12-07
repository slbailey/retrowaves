"""
Tower HTTP server subsystem.

This package provides the HTTP server for streaming MP3 audio to clients.
Client management is owned by HTTPServer per NEW_TOWER_RUNTIME_CONTRACT.
"""

from tower.http.server import HTTPServer

__all__ = [
    "HTTPServer",
]

