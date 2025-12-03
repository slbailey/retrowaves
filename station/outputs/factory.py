import os
from .base_sink import BaseSink
from .null_sink import NullSink
from .file_sink import FileSink
from .ffmpeg_sink import FFMPEGSink


def create_output_sink() -> BaseSink:
    """
    Create an output sink based on environment configuration.
    
    Environment variables:
        OUTPUT_SINK_MODE: "null" | "wav" | "ffmpeg" (default: "null")
        OUTPUT_WAV_PATH: Path for WAV output when mode is "wav" (default: /tmp/appalachia_output.wav)
        OUTPUT_STREAM_PATH: Path or URL for ffmpeg output when mode is "ffmpeg" (default: /tmp/appalachia_output.aac)
    
    Returns:
        BaseSink instance configured according to environment
    """
    mode = os.getenv("OUTPUT_SINK_MODE", "null").lower()

    if mode == "wav":
        path = os.getenv("OUTPUT_WAV_PATH", "/tmp/appalachia_output.wav")
        return FileSink(path)

    if mode == "ffmpeg":
        target = os.getenv("OUTPUT_STREAM_PATH", "/tmp/appalachia_output.aac")
        return FFMPEGSink(target)

    # Default: discard audio, station logic still runs
    return NullSink()

