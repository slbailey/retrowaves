"""
Tower fallback audio subsystem.

This package provides fallback audio generation for Tower when live PCM
is not available.
"""

from tower.fallback.file_source import FileSource
from tower.fallback.generator import FallbackGenerator

__all__ = [
    "FallbackGenerator",
    "FileSource",
]

