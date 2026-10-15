"""sse_stream used to block forever on `await q.get()` whenever no event had
anything new to deliver. A disconnected client (closed tab, dropped
network, a sleeping laptop) was only ever discovered the next time some
*unrelated* event happened to be published and the write to that dead
socket finally failed - until then its subscriber queue stayed registered
on the bus, silently accumulating (and never draining) anything published
in the meantime. A periodic heartbeat forces a write on an otherwise-idle
connection often enough that a dead one is found, and cleaned up, within
one interval instead of being leaked indefinitely.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import app.streaming.events as events


@pytest.mark.asyncio
async def test_idle_stream_sends_a_heartbeat_instead_of_blocking_forever(monkeypatch):
    monkeypatch.setattr(events, "HEARTBEAT_INTERVAL_SECONDS", 0.05)
    gen = events.sse_stream()
    try:
        first = await asyncio.wait_for(gen.__anext__(), timeout=1)
        assert json.loads(first.removeprefix("data: ").strip())["event"] == "CONNECTED"

        # Nothing was published - with no heartbeat this would hang forever.
        second = await asyncio.wait_for(gen.__anext__(), timeout=1)
        assert second.startswith(": heartbeat")
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_a_real_event_still_arrives_promptly_alongside_heartbeats(monkeypatch):
    monkeypatch.setattr(events, "HEARTBEAT_INTERVAL_SECONDS", 0.05)
    gen = events.sse_stream()
    try:
        await asyncio.wait_for(gen.__anext__(), timeout=1)  # CONNECTED

        await events.bus.publish({"event": "TASK_STARTED", "task_id": "t1"})

        # May see zero or more heartbeats first, but the real event must
        # show up without being lost.
        for _ in range(10):
            chunk = await asyncio.wait_for(gen.__anext__(), timeout=1)
            if chunk.startswith(": heartbeat"):
                continue
            assert json.loads(chunk.removeprefix("data: ").strip())["event"] == "TASK_STARTED"
            break
        else:
            pytest.fail("real event never arrived")
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_closing_the_stream_unsubscribes_it_from_the_bus():
    before = len(events.bus._subscribers)
    gen = events.sse_stream()
    await gen.__anext__()  # CONNECTED - subscribe has happened by now
    assert len(events.bus._subscribers) == before + 1

    await gen.aclose()
    assert len(events.bus._subscribers) == before
