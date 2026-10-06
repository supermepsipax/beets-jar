import asyncio

from fastapi import Request
from fastapi.sse import ServerSentEvent


class ChangeNotifier:
    """A version number that SSE streams can wait on.

    ImportRegistry and ProcessRegistry extend this and call notify() after every
    change; each panel stream re-renders when the version moves.
    """

    def __init__(self):
        self.version = 0
        self._waiters: set[asyncio.Event] = set()
        self._closing = False

    def notify(self):
        self.version += 1
        for waiter in self._waiters:
            waiter.set()

    @property
    def closing(self) -> bool:
        return self._closing

    def close(self):
        """Server shutdown: wake every stream so it can end."""
        self._closing = True
        for waiter in self._waiters:
            waiter.set()

    async def wait_for_change(self, since_version: int) -> int:
        if self.version > since_version or self._closing:
            return self.version
        waiter = asyncio.Event()
        self._waiters.add(waiter)
        try:
            await waiter.wait()
        finally:
            self._waiters.discard(waiter)
        return self.version

# How often an idle stream checks whether its browser tab went away. Without
# this, a closed tab's stream lingers until the next change or keepalive.
DISCONNECT_CHECK_SECONDS = 1
KEEPALIVE_SECONDS = 30


async def panel_stream(request: Request, registry: ChangeNotifier, template, build):
    """Re-render one side panel on every registry change; only send it if the HTML changed.

    `template` is a loaded Jinja template, rendered with `groups=build(registry)`.
    """
    last_version, last_html = -1, None
    idle_seconds = 0
    while not (registry.closing or await request.is_disconnected()):
        if registry.version != last_version:
            last_version = registry.version
            idle_seconds = 0
            html = template.render(groups=build(registry))
            if html != last_html:
                last_html = html
                yield ServerSentEvent(raw_data=html)
        try:
            await asyncio.wait_for(
                registry.wait_for_change(last_version), timeout=DISCONNECT_CHECK_SECONDS
            )
        except TimeoutError:
            idle_seconds += DISCONNECT_CHECK_SECONDS
            if idle_seconds >= KEEPALIVE_SECONDS:
                idle_seconds = 0
                yield ServerSentEvent(comment="keepalive")
