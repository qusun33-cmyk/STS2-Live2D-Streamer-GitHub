from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field


@dataclass(order=True)
class NarrationMessage:
    sort_key: tuple[int, int] = field(init=False, repr=False)
    priority: int
    sequence: int
    text: str
    mood: str | None = None
    expression: str | None = None
    source: str | None = None
    dedupe_key: str | None = None

    def __post_init__(self) -> None:
        self.sort_key = (-self.priority, self.sequence)


class NarrationHub:
    def __init__(self, speaker, dedupe_window_seconds: float = 12.0):
        self._speaker = speaker
        self._dedupe_window_seconds = dedupe_window_seconds
        self._queue: queue.PriorityQueue[NarrationMessage] = queue.PriorityQueue()
        self._dedupe: dict[str, float] = {}
        self._sequence = 0
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="streamer-narration")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._queue.put(NarrationMessage(priority=-999, sequence=10**9, text="__stop__"))
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def submit(
        self,
        text: str,
        *,
        priority: int = 0,
        mood: str | None = None,
        expression: str | None = None,
        source: str | None = None,
        dedupe_key: str | None = None,
    ) -> bool:
        cleaned = " ".join((text or "").split()).strip()
        if not cleaned:
            return False

        key = dedupe_key or cleaned
        now = time.monotonic()
        self._expire_dedupe(now)
        previous = self._dedupe.get(key)
        if previous is not None and now - previous < self._dedupe_window_seconds:
            return False

        self._dedupe[key] = now
        self._sequence += 1
        self._queue.put(
            NarrationMessage(
                priority=priority,
                sequence=self._sequence,
                text=cleaned,
                mood=mood,
                expression=expression,
                source=source,
                dedupe_key=key,
            )
        )
        return True

    def _expire_dedupe(self, now: float) -> None:
        expired = [
            key
            for key, timestamp in self._dedupe.items()
            if now - timestamp >= self._dedupe_window_seconds
        ]
        for key in expired:
            self._dedupe.pop(key, None)

    def _run(self) -> None:
        while self._running:
            try:
                message = self._queue.get(timeout=0.3)
            except queue.Empty:
                continue

            if message.text == "__stop__":
                return

            self._speaker.speak(
                message.text,
                mood=message.mood,
                expression=message.expression,
                source=message.source,
            )
