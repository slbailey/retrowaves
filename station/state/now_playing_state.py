"""
Now Playing State Manager

Implements NEW_NOW_PLAYING_STATE_CONTRACT.md

Provides authoritative, read-only state for currently active playout segment.
"""

import logging
import time
import threading
from dataclasses import dataclass
from typing import Optional

from station.broadcast_core.audio_event import AudioEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NowPlayingState:
    """
    Immutable state snapshot for currently playing segment.
    
    Per contract N.1, N.2: Required and optional fields.
    Per contract N.4: No derived fields (elapsed, remaining, progress, etc.).
    """
    segment_type: str  # Required (N.1)
    started_at: float  # Required (N.1) - wall-clock timestamp (time.time())
    title: Optional[str] = None  # Optional (N.2)
    artist: Optional[str] = None  # Optional (N.2)
    album: Optional[str] = None  # Optional (N.2)
    year: Optional[int] = None  # Optional (N.2)
    duration_sec: Optional[float] = None  # Optional (N.2)
    file_path: Optional[str] = None  # Optional (N.2)


class NowPlayingStateManager:
    """
    Manages NowPlayingState lifecycle.
    
    Per contract U.1, U.3: State created on segment_started, cleared on segment_finished.
    Per contract U.4, I.2: Station is the only writer.
    Per contract U.2, I.4: State is immutable during playback.
    """
    
    def __init__(self):
        """Initialize state manager."""
        self._state: Optional[NowPlayingState] = None
        self._lock = threading.RLock()  # Thread-safe state access
        self._listeners = []  # Callbacks for state changes (for WebSocket events)
    
    def on_segment_started(self, event: AudioEvent) -> None:
        """
        Handle on_segment_started event (U.1).
        
        Contract U.1: State MUST be created when on_segment_started is emitted.
        Contract I.7: State MUST align with segment lifecycle events.
        
        Args:
            event: AudioEvent that started playing
        """
        with self._lock:
            # Extract metadata from AudioEvent
            metadata = getattr(event, 'metadata', {}) or {}
            
            # Contract N.1: started_at MUST be wall-clock timestamp (time.time(), not time.monotonic())
            started_at = time.time()
            
            # Create immutable state snapshot
            self._state = NowPlayingState(
                segment_type=event.type,
                started_at=started_at,
                title=metadata.get('title'),
                artist=metadata.get('artist'),
                album=metadata.get('album'),
                year=metadata.get('year'),
                duration_sec=metadata.get('duration'),
                file_path=event.path
            )
            
            logger.debug(f"[NOW_PLAYING] State created: {self._state.segment_type} - {self._state.file_path}")
            
            # Notify listeners (for WebSocket events)
            self._notify_listeners(self._state)
    
    def on_segment_finished(self) -> None:
        """
        Handle on_segment_finished event (U.3).
        
        Contract U.3: State MUST be cleared when on_segment_finished is emitted.
        Contract U.3: State MUST NOT retain any information from completed segment.
        
        """
        with self._lock:
            if self._state is not None:
                logger.debug(f"[NOW_PLAYING] State cleared: {self._state.segment_type} - {self._state.file_path}")
            
            self._state = None
            
            # Notify listeners (for WebSocket events)
            self._notify_listeners(None)
    
    def get_state(self) -> Optional[NowPlayingState]:
        """
        Get current state (read-only).
        
        Contract E.3: State MAY be queried via read operations.
        Contract I.6: State queries MUST NOT block playout operations.
        
        Returns:
            Current NowPlayingState or None if no segment is playing
        """
        with self._lock:
            return self._state
    
    def clear_state(self) -> None:
        """
        Clear state (for restart semantics).
        
        Contract U.3: If Station restarts mid-segment, state MUST be cleared.
        
        """
        with self._lock:
            self._state = None
            self._notify_listeners(None)
    
    def add_listener(self, callback) -> None:
        """
        Add a listener callback for state changes.
        
        Used for WebSocket event broadcasting (E.2).
        Callback will be called with (state: Optional[NowPlayingState]) when state changes.
        
        Args:
            callback: Function to call on state changes
        """
        with self._lock:
            self._listeners.append(callback)
    
    def remove_listener(self, callback) -> None:
        """
        Remove a listener callback.
        
        Args:
            callback: Function to remove
        """
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)
    
    def _notify_listeners(self, state: Optional[NowPlayingState]) -> None:
        """
        Notify all listeners of state change.
        
        Contract E.5: All exposure operations MUST be non-blocking.
        
        Args:
            state: New state (or None if cleared)
        """
        # Copy listeners list to avoid lock contention during callback execution
        listeners = self._listeners.copy()
        
        for callback in listeners:
            try:
                callback(state)
            except Exception as e:
                # Contract E.5: Exposure failures MUST NOT affect playout behavior
                logger.debug(f"[NOW_PLAYING] Listener callback error: {e}")

