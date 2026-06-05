import asyncio

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from ..tracing import bus

router = APIRouter()


@router.get("/stream")
async def stream(pipeline_id: int | None = None):
    q = bus.subscribe(pipeline_id)

    async def gen():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield {"event": "trace", "data": msg}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            bus.unsubscribe(pipeline_id, q)

    return EventSourceResponse(gen())
