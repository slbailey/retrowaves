"""
Event broadcaster for Station heartbeat events.

Per NEW_TOWER_RUNTIME_CONTRACT T-EVENTS2:
- Events are NOT stored
- Events are delivered only to currently connected WebSocket clients
- Events are dropped immediately if no clients are connected
- Only tracks station shutdown state (for encoder manager)
"""

from __future__ import annotations

import threading
from typing import Dict, Any

import logging

logger = logging.getLogger(__name__)


# Accepted event types per contract T-EVENTS1
# ONLY these four event types are accepted:
ACCEPTED_EVENT_TYPES = {
    "station_startup",  # Station has started up and playout has begun
    "station_shutdown",  # Station is shutting down after terminal playout completes
    "song_playing",  # Song segment has started playing (edge-triggered transition)
    "segment_playing",  # Non-song segment has started playing (edge-triggered transition)
}

# DEPRECATED event types (MUST be explicitly rejected per contract T-EVENTS1)
DEPRECATED_EVENT_TYPES = {
    "station_starting_up",  # DEPRECATED - use station_startup instead
    "station_shutting_down",  # DEPRECATED - use station_shutdown instead
    "now_playing",  # DEPRECATED - Tower must not accept this event
    "dj_talking",  # DEPRECATED - use segment_playing instead
}


class EventBroadcaster:
    """
    Event broadcaster for Station heartbeat events.
    
    Per contract T-EVENTS2:
    - Events are NOT stored
    - Only tracks station shutdown state (for encoder manager)
    - Validates events before delivery
    """
    
    def __init__(self):
        """Initialize event broadcaster."""
        self._lock = threading.Lock()
        # Track station shutdown state per contract T-EVENTS5 exception
        self._station_shutting_down = False
    
    def validate_event(self, event_type: str, timestamp: float, metadata: Dict[str, Any]) -> bool:
        """
        Validate event per contract T-EVENTS7.
        
        Per contract T-EVENTS1:
        - Accept ONLY: station_startup, station_shutdown, song_playing, segment_playing
        - Reject DEPRECATED: station_starting_up, station_shutting_down, now_playing, dj_talking
        - Reject any other unknown event types
        
        Per contract T-EVENTS3.4: Tower treats metadata as opaque and does not validate metadata fields.
        Metadata is broadcast verbatim if event_type is valid.
        
        Returns:
            True if valid, False otherwise
        """
        # Contract T-EVENTS1: Reject deprecated event types
        if event_type in DEPRECATED_EVENT_TYPES:
            logger.warning(f"Contract violation [T-EVENTS1]: Rejected deprecated event type: {event_type}")
            return False
        
        # Contract T-EVENTS1: Accept only allowed event types
        if event_type not in ACCEPTED_EVENT_TYPES:
            logger.warning(f"Contract violation [T-EVENTS1]: Rejected unknown event type: {event_type}")
            return False
        
        # Validate timestamp is a number
        if not isinstance(timestamp, (int, float)):
            logger.debug(f"Invalid timestamp type: {type(timestamp)}")
            return False
        
        # Validate metadata is a dict
        if not isinstance(metadata, dict):
            logger.debug(f"Invalid metadata type: {type(metadata)}")
            return False
        
        # Per contract T-EVENTS3.4: Tower treats metadata as opaque
        # No metadata field validation - metadata is broadcast verbatim
        
        return True
    
    def update_shutdown_state(self, event_type: str) -> None:
        """
        Update station shutdown state based on event type.
        
        Per contract T-EVENTS5 exception: Used to suppress PCM loss warnings.
        
        Args:
            event_type: Event type (must be station_shutdown or station_startup)
        """
        with self._lock:
            # Use new event names (station_startup, station_shutdown)
            if event_type == "station_shutdown":
                self._station_shutting_down = True
            elif event_type == "station_startup":
                self._station_shutting_down = False
    
    def is_station_shutting_down(self) -> bool:
        """
        Check if station is shutting down.
        
        Per contract T-EVENTS5 exception: Used to suppress PCM loss warnings.
        
        Returns:
            True if station_shutting_down event was received and station_starting_up has not been received since
        """
        with self._lock:
            return self._station_shutting_down


