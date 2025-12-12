"""
Playout Queue for Appalachia Radio 3.1.

FIFO queue for managing AudioEvents in playout order.

Architecture 3.1 Reference:
- Section 4.4: DJ Transition Window Behavior
- Section 5: Updated Playout Engine Flow
"""

import logging
from collections import deque
from typing import Optional, Tuple
import uuid

from station.broadcast_core.audio_event import AudioEvent

logger = logging.getLogger(__name__)


class PlayoutQueue:
    """
    FIFO queue for AudioEvents with intent_id tracking.
    
    Maintains order of audio segments for playout.
    Stores (intent_id, AudioEvent) tuples to enforce atomic intent execution.
    Architecture 3.1 Reference: Section 4.4
    """
    
    def __init__(self):
        """Initialize the playout queue."""
        self._queue: deque[Tuple[uuid.UUID, AudioEvent]] = deque()
    
    def enqueue(self, audio_event: AudioEvent) -> None:
        """
        Add an AudioEvent to the end of the queue.
        
        Uses the intent_id from the AudioEvent itself.
        
        Args:
            audio_event: AudioEvent to add (must have intent_id set)
        """
        if audio_event.intent_id is None:
            logger.warning(f"Enqueuing AudioEvent without intent_id: {audio_event.type} - {audio_event.path}")
        intent_id = audio_event.intent_id if audio_event.intent_id else uuid.uuid4()
        self._queue.append((intent_id, audio_event))
        logger.debug(f"Enqueued: intent_id={intent_id}, type={audio_event.type}, path={audio_event.path}")
    
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
        
        intent_id, event = self._queue.popleft()
        logger.debug(f"Dequeued: intent_id={intent_id}, type={event.type}, path={event.path}")
        return event
    
    def peek(self) -> Optional[AudioEvent]:
        """
        Return the first AudioEvent without removing it.
        
        Returns:
            AudioEvent from front of queue, or None if queue is empty
        """
        if self.empty():
            return None
        _, event = self._queue[0]
        return event
    
    def peek_intent_id(self) -> Optional[uuid.UUID]:
        """
        Return the intent_id of the first item in the queue without removing it.
        
        Returns:
            intent_id from front of queue, or None if queue is empty
        """
        if self.empty():
            return None
        intent_id, _ = self._queue[0]
        return intent_id
    
    def get_all_intent_ids(self) -> list[uuid.UUID]:
        """
        Get all intent_ids currently in the queue (for verification).
        
        Returns:
            List of intent_ids in queue order
        """
        return [intent_id for intent_id, _ in self._queue]
    
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
    
    def dump(self) -> list[str]:
        """
        Dump queue contents for debugging.
        
        Returns:
            List of string representations of queue items
        """
        return [f"intent_id={intent_id}, {event.type}:{event.path}" for intent_id, event in self._queue]
    
    def get_tail(self, n: int) -> list[AudioEvent]:
        """
        Get the last N AudioEvents from the queue without removing them.
        
        Args:
            n: Number of items to retrieve from the tail
            
        Returns:
            List of AudioEvents from the tail of the queue (most recent last)
        """
        if n <= 0:
            return []
        queue_size = len(self._queue)
        if queue_size == 0:
            return []
        # Get last n items (or all if queue is smaller)
        start_idx = max(0, queue_size - n)
        # Extract AudioEvents from (intent_id, AudioEvent) tuples
        return [event for _, event in list(self._queue)[start_idx:]]

