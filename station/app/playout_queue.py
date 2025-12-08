from typing import List, Optional

from station.broadcast_core.audio_event import AudioEvent


class PlayoutQueue:
    def __init__(self) -> None:
        self._queue: List[AudioEvent] = []

    def enqueue(self, event: AudioEvent) -> None:
        self._queue.append(event)

    def dequeue(self) -> Optional[AudioEvent]:
        if not self._queue:
            return None
        return self._queue.pop(0)

    def __len__(self) -> int:
        return len(self._queue)

    def dump(self) -> List[str]:
        return [f"{e.type}:{e.path}" for e in self._queue]


