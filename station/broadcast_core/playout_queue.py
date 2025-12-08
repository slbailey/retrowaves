"""
Playout Queue for Appalachia Radio 3.1.

FIFO queue for managing AudioEvents in playout order.

Architecture 3.1 Reference:
- Section 4.4: DJ Transition Window Behavior
- Section 5: Updated Playout Engine Flow
"""

import logging
from collections import deque
from typing import Optional

from station.broadcast_core.audio_event import AudioEvent

logger = logging.getLogger(__name__)


class PlayoutQueue:
    """
    FIFO queue for AudioEvents.
    
    Maintains order of audio segments for playout.
    Architecture 3.1 Reference: Section 4.4
    """
    
    def __init__(self):
        """Initialize the playout queue."""
        self._queue: deque[AudioEvent] = deque()
    
    def enqueue(self, audio_event: AudioEvent) -> None:
        """
        Add an AudioEvent to the end of the queue.
        
        Args:
            audio_event: AudioEvent to add
        """
        self._queue.append(audio_event)
        logger.debug(f"Enqueued: {audio_event.type} - {audio_event.path}")
    
    def enqueue_multiple(self, audio_events: list[AudioEvent]) -> None:
        """
        Add multiple AudioEvents to the end of the queue.
        
        Maintains the order of the input list.
        
        Args:
            audio_events: List of AudioEvents to add
        """
        for event in audio_events:
            self.enqueue(event)
    
    def dequeue(self) -> Optional[AudioEvent]:
        """
        Remove and return the first AudioEvent from the queue.
        
        Returns:
            AudioEvent from front of queue, or None if queue is empty
        """
        if self.empty():
            return None
        
        event = self._queue.popleft()
        logger.debug(f"Dequeued: {event.type} - {event.path}")
        return event
    
    def peek(self) -> Optional[AudioEvent]:
        """
        Return the first AudioEvent without removing it.
        
        Returns:
            AudioEvent from front of queue, or None if queue is empty
        """
        if self.empty():
            return None
        return self._queue[0]
    
    def empty(self) -> bool:
        """
        Check if the queue is empty.
        
        Returns:
            True if queue is empty, False otherwise
        """
        return len(self._queue) == 0
    
    def size(self) -> int:
        """
        Get the number of AudioEvents in the queue.
        
        Returns:
            Number of items in queue
        """
        return len(self._queue)
    
    def clear(self) -> None:
        """Clear all AudioEvents from the queue."""
        self._queue.clear()
        logger.debug("Queue cleared")

