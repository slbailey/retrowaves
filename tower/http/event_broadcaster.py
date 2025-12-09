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
ACCEPTED_EVENT_TYPES = {
    "station_starting_up",
    "station_shutting_down",
    "new_song",
    "dj_talking",
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
        
        Returns:
            True if valid, False otherwise
        """
        # Validate event type
        if event_type not in ACCEPTED_EVENT_TYPES:
            logger.debug(f"Invalid event type: {event_type}")
            return False
        
        # Validate timestamp is a number
        if not isinstance(timestamp, (int, float)):
            logger.debug(f"Invalid timestamp type: {type(timestamp)}")
            return False
        
        # Validate metadata is a dict
        if not isinstance(metadata, dict):
            logger.debug(f"Invalid metadata type: {type(metadata)}")
            return False
        
        return True
    
    def update_shutdown_state(self, event_type: str) -> None:
        """
        Update station shutdown state based on event type.
        
        Per contract T-EVENTS5 exception: Used to suppress PCM loss warnings.
        
        Args:
            event_type: Event type (must be station_shutting_down or station_starting_up)
        """
        with self._lock:
            if event_type == "station_shutting_down":
                self._station_shutting_down = True
            elif event_type == "station_starting_up":
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


