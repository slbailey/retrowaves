"""
Station State Manager

Implements STATION_STATE_CONTRACT.md

Provides authoritative, queryable runtime state of Station.
State is LEVEL-triggered and authoritative, independent of event history.
"""

import logging
import time
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Any

from station.broadcast_core.audio_event import AudioEvent

logger = logging.getLogger(__name__)


# Allowed station states per contract S.1
# Per contract: DJ_TALKING is deprecated. Non-song segments use SONG_PLAYING state with segment_type="segment"
STATION_STATE_STARTING_UP = "STARTING_UP"
STATION_STATE_SONG_PLAYING = "SONG_PLAYING"
STATION_STATE_FALLBACK = "FALLBACK"
STATION_STATE_SHUTTING_DOWN = "SHUTTING_DOWN"
STATION_STATE_ERROR = "ERROR"

ALLOWED_STATES = {
    STATION_STATE_STARTING_UP,
    STATION_STATE_SONG_PLAYING,
    STATION_STATE_FALLBACK,
    STATION_STATE_SHUTTING_DOWN,
    STATION_STATE_ERROR,
}


@dataclass(frozen=True)
class StationState:
    """
    Immutable state snapshot for Station operational status.
    
    Per contract S.2: Required fields (station_state, since, current_audio).
    Per contract S.2.2: since is monotonic timestamp.
    Per contract S.2.3: current_audio is object or null.
    """
    station_state: str  # Required (S.2.1) - one of ALLOWED_STATES
    since: float  # Required (S.2.2) - monotonic timestamp
    current_audio: Optional[Dict[str, Any]] = None  # Required field (S.2.3), nullable value


class StationStateManager:
    """
    Manages StationState lifecycle.
    
    Per contract R.3: State updates happen ONLY via lifecycle hooks.
    Per contract I.4: Station is the ONLY writer of state.
    Per contract I.6: State queries MUST NOT block playout operations.
    """
    
    def __init__(self):
        """Initialize state manager."""
        self._state: Optional[StationState] = None
        self._lock = threading.RLock()  # Thread-safe state access
    
    def _create_current_audio(self, segment: AudioEvent) -> Dict[str, Any]:
        """
        Create current_audio object from AudioEvent.
        
        Per contract S.2.3: Required fields (segment_type, file_path, started_at).
        Optional fields (title, artist, duration_sec).
        For non-song segments: Required metadata (segment_class, segment_role, production_type).
        
        Args:
            segment: AudioEvent to create current_audio from
            
        Returns:
            Dictionary with current_audio structure
        """
        metadata = getattr(segment, 'metadata', {}) or {}
        
        # Contract S.2.3: started_at MUST be wall-clock timestamp (time.time())
        started_at = time.time()
        
        # Contract S.2.3: segment_type MUST be "song", "segment", or "fallback"
        # Map AudioEvent.type to segment_type
        if segment.type == "song":
            segment_type = "song"
        elif segment.type == "fallback":
            segment_type = "fallback"
        else:
            # All other types (intro, outro, talk, id, announcement) are "segment"
            segment_type = "segment"
        
        # Contract S.2.3: Required fields
        current_audio = {
            "segment_type": segment_type,
            "file_path": segment.path,
            "started_at": started_at,
        }
        
        # Contract S.2.3: Optional fields for songs
        if segment_type == "song":
            if metadata.get('title') is not None:
                current_audio["title"] = metadata.get('title')
            if metadata.get('artist') is not None:
                current_audio["artist"] = metadata.get('artist')
            if metadata.get('duration') is not None:
                current_audio["duration_sec"] = metadata.get('duration')
        
        # Contract S.2.3: Required metadata for non-song segments (segment_type="segment")
        if segment_type == "segment":
            # Extract segment metadata from AudioEvent.metadata or infer from segment type
            # Import helper function from playout_engine
            from station.broadcast_core.playout_engine import _get_segment_metadata
            
            try:
                segment_metadata = _get_segment_metadata(segment)
                current_audio["segment_class"] = segment_metadata["segment_class"]
                current_audio["segment_role"] = segment_metadata["segment_role"]
                current_audio["production_type"] = segment_metadata["production_type"]
            except ValueError as e:
                # Per contract: Fail loudly if metadata cannot be determined
                logger.error(
                    f"Contract violation [S.2.3]: Cannot create current_audio for segment {segment.path}: {e}. "
                    f"State update refused."
                )
                # Return minimal state - this should not happen in normal operation
                current_audio["segment_class"] = None
                current_audio["segment_role"] = None
                current_audio["production_type"] = None
            
            # Optional fields for segments
            if metadata.get('duration') is not None:
                current_audio["duration_sec"] = metadata.get('duration')
        
        return current_audio
    
    def on_startup(self, startup_announcement: Optional[AudioEvent] = None) -> None:
        """
        Handle station startup.
        
        Per contract: On startup, station_state = STARTING_UP, current_audio populated with startup announcement.
        
        Args:
            startup_announcement: Optional startup announcement AudioEvent
        """
        with self._lock:
            # Contract S.2.2: since MUST be monotonic timestamp
            since = time.monotonic()
            
            # Contract S.4: current_audio MUST be non-null in STARTING_UP
            if startup_announcement:
                current_audio = self._create_current_audio(startup_announcement)
            else:
                # If no startup announcement, create a minimal current_audio
                # This should not happen per contract, but handle gracefully
                current_audio = {
                    "segment_type": "talk",
                    "file_path": "",
                    "started_at": time.time(),
                }
            
            self._state = StationState(
                station_state=STATION_STATE_STARTING_UP,
                since=since,
                current_audio=current_audio
            )
            
            logger.debug(f"[STATION_STATE] Startup: {self._state.station_state}")
    
    def on_segment_started(self, segment: AudioEvent) -> None:
        """
        Handle on_segment_started lifecycle event.
        
        Per contract R.3: State MUST be updated when on_segment_started is emitted.
        Per contract S.4: current_audio MUST be non-null in all non-ERROR states.
        Per contract: Non-song segments use SONG_PLAYING state with segment_type="segment".
        
        Args:
            segment: AudioEvent that started playing
        """
        with self._lock:
            # Contract S.2.2: since MUST be monotonic timestamp
            since = time.monotonic()
            
            # Determine station_state based on segment type
            # Per contract: Non-song segments use SONG_PLAYING state (not DJ_TALKING)
            if segment.type == "song":
                station_state = STATION_STATE_SONG_PLAYING
            elif segment.type == "fallback":
                station_state = STATION_STATE_FALLBACK
            else:
                # All other segment types (intro, outro, talk, id, announcement) use SONG_PLAYING
                # Per contract: Non-song segments are represented by segment_type="segment" in current_audio
                station_state = STATION_STATE_SONG_PLAYING
            
            # Contract S.4: current_audio MUST be non-null in all non-ERROR states
            current_audio = self._create_current_audio(segment)
            
            self._state = StationState(
                station_state=station_state,
                since=since,
                current_audio=current_audio
            )
            
            logger.debug(f"[STATION_STATE] Segment started: {self._state.station_state} - {segment.type}")
    
    def on_shutdown(self, shutdown_announcement: Optional[AudioEvent] = None) -> None:
        """
        Handle station shutdown.
        
        Per contract: On shutdown, station_state = SHUTTING_DOWN, current_audio populated with shutdown announcement.
        
        Args:
            shutdown_announcement: Optional shutdown announcement AudioEvent
        """
        with self._lock:
            # Contract S.2.2: since MUST be monotonic timestamp
            since = time.monotonic()
            
            # Contract S.4: current_audio MUST be non-null in SHUTTING_DOWN
            if shutdown_announcement:
                current_audio = self._create_current_audio(shutdown_announcement)
            else:
                # If no shutdown announcement, create a minimal current_audio
                current_audio = {
                    "segment_type": "talk",
                    "file_path": "",
                    "started_at": time.time(),
                }
            
            self._state = StationState(
                station_state=STATION_STATE_SHUTTING_DOWN,
                since=since,
                current_audio=current_audio
            )
            
            logger.debug(f"[STATION_STATE] Shutdown: {self._state.station_state}")
    
    def on_error(self) -> None:
        """
        Handle station error.
        
        Per contract S.4: On error, station_state = ERROR, current_audio = null.
        """
        with self._lock:
            # Contract S.2.2: since MUST be monotonic timestamp
            since = time.monotonic()
            
            # Contract S.4: current_audio MUST be null in ERROR
            self._state = StationState(
                station_state=STATION_STATE_ERROR,
                since=since,
                current_audio=None
            )
            
            logger.debug(f"[STATION_STATE] Error: {self._state.station_state}")
    
    def get_state(self) -> Optional[StationState]:
        """
        Get current state (read-only).
        
        Per contract Q.1: State MUST be queryable at any time.
        Per contract I.6: State queries MUST NOT block playout operations.
        
        Returns:
            Current StationState or None if not initialized
        """
        with self._lock:
            return self._state
    
    def get_state_dict(self) -> Dict[str, Any]:
        """
        Get current state as dictionary for JSON serialization.
        
        Per contract Q.2: Response format with station_state, since, current_audio.
        
        Returns:
            Dictionary with state fields
        """
        with self._lock:
            if self._state is None:
                # If state not initialized, return ERROR state
                return {
                    "station_state": STATION_STATE_ERROR,
                    "since": time.monotonic(),
                    "current_audio": None
                }
            
            return {
                "station_state": self._state.station_state,
                "since": self._state.since,
                "current_audio": self._state.current_audio
            }

