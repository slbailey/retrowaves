"""
Event buffer for storing Station heartbeat events.

Per NEW_TOWER_RUNTIME_CONTRACT T-EVENTS2:
- Bounded, thread-safe event buffer
- Events stored with timestamps (Tower wall-clock time when received)
- Maximum capacity (default: 1000 events)
- FIFO eviction when buffer is full
"""

from __future__ import annotations

import time
import threading
import uuid
from collections import deque
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict

import logging

logger = logging.getLogger(__name__)


@dataclass
class StationEvent:
    """Station heartbeat event structure."""
    event_type: str
    timestamp: float  # Station Clock A timestamp
    tower_received_at: float  # Tower wall-clock timestamp when received
    event_id: str  # Tower-side unique ID for tracking
    metadata: Dict[str, Any]


# Accepted event types per contract T-EVENTS1
ACCEPTED_EVENT_TYPES = {
    "segment_started",
    "segment_progress",
    "segment_finished",
    "dj_think_started",
    "dj_think_completed",
    "decode_clock_skew",
    "station_underflow",
    "station_overflow",
    "station_shutting_down",
    "station_starting_up",
}


class EventBuffer:
    """
    Thread-safe bounded event buffer for Station heartbeat events.
    
    Per contract T-EVENTS2:
    - Bounded capacity (default: 1000 events)
    - Thread-safe operations
    - FIFO eviction when full
    - Events stored with tower_received_at timestamp
    """
    
    def __init__(self, capacity: int = 1000):
        """
        Initialize event buffer.
        
        Args:
            capacity: Maximum number of events to store (default: 1000)
        """
        self.capacity = capacity
        self._events: deque[StationEvent] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._overflow_count = 0
        # Track station shutdown state per contract T-EVENTS5 exception
        self._station_shutting_down = False
    
    def add_event(self, event_type: str, timestamp: float, metadata: Dict[str, Any]) -> bool:
        """
        Add an event to the buffer.
        
        Per contract T-EVENTS2, T-EVENTS6: Non-blocking, fast (< 1ms typical, < 10ms maximum).
        
        Args:
            event_type: Event type (must be one of ACCEPTED_EVENT_TYPES)
            timestamp: Station Clock A timestamp
            metadata: Event metadata
            
        Returns:
            True if event was stored, False if validation failed
        """
        # Validate event per contract T-EVENTS7
        if not self._validate_event(event_type, timestamp, metadata):
            return False
        
        # Create event with tower_received_at timestamp per contract T-EVENTS2
        event = StationEvent(
            event_type=event_type,
            timestamp=timestamp,
            tower_received_at=time.time(),  # Tower wall-clock time
            event_id=str(uuid.uuid4()),
            metadata=metadata
        )
        
        # Store event (thread-safe, bounded)
        with self._lock:
            # Check if buffer is full (before adding)
            was_full = len(self._events) >= self.capacity
            self._events.append(event)
            
            # Track station shutdown state per contract T-EVENTS5 exception
            if event_type == "station_shutting_down":
                self._station_shutting_down = True
            elif event_type == "station_starting_up":
                self._station_shutting_down = False
            
            # Track overflow per contract T-EVENTS2.5
            if was_full:
                self._overflow_count += 1
                if self._overflow_count % 100 == 1:  # Log every 100th overflow
                    logger.warning(
                        f"Event buffer overflow: {self._overflow_count} events dropped "
                        f"(FIFO eviction per contract T-EVENTS2.5)"
                    )
        
        return True
    
    def get_recent_events(
        self,
        limit: int = 100,
        event_type: Optional[str] = None,
        since: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Get recent events with optional filtering.
        
        Per contract T-EXPOSE2, T-EXPOSE6: Returns events in order of reception (FIFO).
        
        Args:
            limit: Maximum number of events to return (default: 100)
            event_type: Filter by event type (optional)
            since: Only return events received after this timestamp (optional)
            
        Returns:
            Dictionary with 'events', 'count', 'total_available'
        """
        with self._lock:
            events_list = list(self._events)
            total_available = len(events_list)
        
        # Filter events per contract T-EXPOSE7
        filtered = []
        for event in events_list:
            # Apply filters
            if event_type is not None and event.event_type != event_type:
                continue
            if since is not None and event.tower_received_at < since:
                continue
            
            filtered.append(event)
            
            # Apply limit
            if len(filtered) >= limit:
                break
        
        # Convert events to dict format
        events_dict = [asdict(event) for event in filtered]
        
        return {
            "events": events_dict,
            "count": len(events_dict),
            "total_available": total_available
        }
    
    def get_events_stream(
        self,
        event_type: Optional[str] = None,
        since: Optional[float] = None
    ):
        """
        Generator for streaming events.
        
        Per contract T-EXPOSE1: Streams events as they are received (FIFO order).
        
        Args:
            event_type: Filter by event type (optional)
            since: Only stream events received after this timestamp (optional)
            
        Yields:
            StationEvent objects
        """
        start_index = 0
        if since is not None:
            # Find starting index based on since timestamp
            with self._lock:
                events_list = list(self._events)
            
            for i, event in enumerate(events_list):
                if event.tower_received_at >= since:
                    start_index = i
                    break
        
        # Stream events starting from start_index
        while True:
            with self._lock:
                events_list = list(self._events)
            
            # Yield new events
            for i in range(start_index, len(events_list)):
                event = events_list[i]
                
                # Apply filters
                if event_type is not None and event.event_type != event_type:
                    continue
                
                yield event
            
            start_index = len(events_list)
            time.sleep(0.1)  # Poll for new events (non-blocking)
    
    def is_station_shutting_down(self) -> bool:
        """
        Check if station is shutting down.
        
        Per contract T-EVENTS5 exception: Used to suppress PCM loss warnings.
        
        Returns:
            True if station_shutting_down event was received and station_starting_up has not been received since
        """
        with self._lock:
            return self._station_shutting_down
    
    def _validate_event(self, event_type: str, timestamp: float, metadata: Dict[str, Any]) -> bool:
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

