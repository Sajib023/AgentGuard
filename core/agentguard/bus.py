"""In-process WebSocket event bus.

Every event recorded by the service is pushed to connected dashboard/monitor
clients; clients may also emit events over the same socket.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .schema import Event, EventType
from .utils import now


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[int, dict] = {}   # id -> {"queue": Queue, "session": str|None, "types": set|None}
        self._next = 0
        self._lock = asyncio.Lock()

    async def subscribe(self, *, session_id: str | None = None, types: set[str] | None = None) -> tuple[int, asyncio.Queue]:
        async with self._lock:
            self._next += 1
            sid = self._next
            q: asyncio.Queue = asyncio.Queue(maxsize=512)
            self._subs[sid] = {"queue": q, "session": session_id, "types": types}
        return sid, q

    async def unsubscribe(self, sid: int) -> None:
        async with self._lock:
            self._subs.pop(sid, None)

    async def publish(self, event: Event) -> None:
        message = await self._encode(event)
        async with self._lock:
            targets = list(self._subs.items())
        for sid, sub in targets:
            want_session = sub["session"]
            want_types = sub["types"]
            if want_session and event.session_id != want_session:
                continue
            if want_types and event.type.value not in want_types:
                continue
            try:
                sub["queue"].put_nowait(message)
            except asyncio.QueueFull:  # slow client: drop, never block the pipeline
                continue

    def broadcast_breaker(self, payload: dict[str, Any]) -> None:
        # Convenience bridge for sync contexts (breaker callbacks).
        msg = json.dumps({"kind": "breaker", "meta": payload, "ts": now()})
        for sid, sub in list(self._subs.items()):
            try:
                sub["queue"].put_nowait(msg)
            except asyncio.QueueFull:
                continue

    @staticmethod
    async def _encode(event: Event) -> str:
        return json.dumps({"kind": "event", "event": event.model_dump(mode="json")}, default=str)
