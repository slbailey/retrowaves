"""
Outputs module for Appalachia Radio 3.1.

This package contains output sinks (FM, YouTube, etc.) that handle
frame-based audio output.
"""

from .base_sink import BaseSink
from .null_sink import NullSink
from .file_sink import FileSink
from .ffmpeg_sink import FFMPEGSink
from .factory import create_output_sink

__all__ = [
    "BaseSink",
    "NullSink",
    "FileSink",
    "FFMPEGSink",
    "create_output_sink",
]

