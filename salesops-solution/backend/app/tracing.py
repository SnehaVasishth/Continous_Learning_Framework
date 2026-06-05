"""In-memory event bus for SSE.

Each pipeline run publishes TraceEvent rows AND streams the same payloads to
any subscribed SSE client. The DB is the durable record; the bus is just
push notifications for the live UI.

THREAD-SAFETY: pipelines run in a BackgroundTasks thread (sync); SSE
subscribers live on the FastAPI asyncio loop. We must NEVER call
`asyncio.Queue.put_nowait` directly across threads — that's not thread-safe
and can hang. We use `loop.call_soon_threadsafe` to schedule the put on the
loop's own thread.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

log = logging.getLogger("tracing")


class TraceBus:
    def __init__(self) -> None:
        self._subs: dict[int, set[asyncio.Queue]] = defaultdict(set)
        self._global: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, pipeline_id: int | None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        # Cache the loop we saw at first subscription — that's the FastAPI loop.
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        if pipeline_id is None:
            self._global.add(q)
        else:
            self._subs[pipeline_id].add(q)
        return q

    def unsubscribe(self, pipeline_id: int | None, q: asyncio.Queue) -> None:
        if pipeline_id is None:
            self._global.discard(q)
        else:
            self._subs.get(pipeline_id, set()).discard(q)

    def publish(self, pipeline_id: int, payload: dict[str, Any]) -> None:
        try:
            msg = json.dumps(payload, default=str)
        except Exception:
            log.exception("trace publish: json.dumps failed; skipping event")
            return
        targets: list[asyncio.Queue] = list(self._subs.get(pipeline_id, set())) + list(self._global)
        if not targets:
            return
        loop = self._loop
        for q in targets:
            try:
                if loop and loop.is_running():
                    # Cross-thread safe — schedule the put on the loop's own thread.
                    loop.call_soon_threadsafe(self._sync_put, q, msg)
                else:
                    # Same-thread fallback (shouldn't happen in production).
                    self._sync_put(q, msg)
            except Exception:
                log.exception("trace publish to queue failed; continuing")

    @staticmethod
    def _sync_put(q: asyncio.Queue, msg: str) -> None:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                q.put_nowait(msg)
            except Exception:
                pass


bus = TraceBus()
