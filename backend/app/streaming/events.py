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

# How often an otherwise-idle stream sends a heartbeat. Without this, a
# connection sitting on `await q.get()` with no new events to deliver has no
# reason to ever touch the underlying socket - so a client that's actually
# gone (closed tab, dropped network, a laptop put to sleep) is only
# discovered the next time some *other* activity happens to publish an
# event and the write to that dead socket finally fails. Until then its
# queue stays registered on the bus and keeps silently receiving (and never
# draining) every event published in the meantime. A periodic heartbeat
# forces a write on an idle connection often enough that a dead one gets
# cleaned up within one interval instead of being leaked indefinitely.
HEARTBEAT_INTERVAL_SECONDS = 15


async def sse_stream(task_id: str | None = None) -> AsyncIterator[str]:
    q = bus.subscribe()
    try:
        yield f"data: {json.dumps({'event': 'CONNECTED', 'status': 'connected'})}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                # A ": "-prefixed line is a comment per the SSE spec - the
                # browser's EventSource never surfaces it as a message, it
                # exists purely to exercise the connection.
                yield ": heartbeat\n\n"
                continue
            if task_id and event.get("task_id") and event.get("task_id") != task_id:
                continue
            yield f"data: {json.dumps(event)}\n\n"
    finally:
        bus.unsubscribe(q)
