import asyncio
import logging

log = logging.getLogger("uvicorn.error")

class ImportEventBus:

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None

    def bind(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._queue = asyncio.Queue()

    def unbind(self):
        self._loop = None

    def emit(self, event) -> None:
        if self._loop is None or self._loop.is_closed() or self._queue is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except RuntimeError:
            pass

    async def consume(self, handler):
        while True:
            event = await self._queue.get()
            try:
                handler(event)
            except Exception:
                log.exception("Failed to apply import event %r", event)

event_bus = ImportEventBus()
