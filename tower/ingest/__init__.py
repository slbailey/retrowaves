"""
PCM Ingestion subsystem for Tower.

This package provides the PCM Ingestion layer that accepts canonical PCM frames
from upstream providers and delivers them to Tower's upstream PCM buffer.

Per NEW_PCM_INGEST_CONTRACT: PCM Ingestion is a pure transport layer that
validates frame size and delivers frames without transformations, routing,
or timing decisions.
"""

from tower.ingest.pcm_ingestor import PCMIngestor
from tower.ingest.transport import IngestTransport, UnixSocketIngestTransport

__all__ = [
    "PCMIngestor",
    "IngestTransport",
    "UnixSocketIngestTransport",
]

