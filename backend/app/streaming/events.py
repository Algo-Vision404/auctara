"""A minimal in-process pub/sub used to power Server-Sent Events.

Every event that is published here is also persisted (activity / audit)
by the caller. This bus only exists to push already-real events to
connected browsers in real time.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncIterator


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def publish(self, event: dict) -> None:
        event.setdefault("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
        for q in list(self._subscribers):
            await q.put(event)


bus = EventBus()


async def sse_stream(task_id: str | None = None) -> AsyncIterator[str]:
    q = bus.subscribe()
    try:
        yield f"data: {json.dumps({'event': 'CONNECTED', 'status': 'connected'})}\n\n"
        while True:
            event = await q.get()
            if task_id and event.get("task_id") and event.get("task_id") != task_id:
                continue
            yield f"data: {json.dumps(event)}\n\n"
    finally:
        bus.unsubscribe(q)
