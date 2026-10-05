import asyncio

from fastapi import Request
from fastapi.sse import ServerSentEvent

DISCONNECT_CHECK_SECONDS = 1
KEEPALIVE_SECONDS = 30

async def panel_stream(request: Request, registry, template, build):
    """Re-render one side panel on every registry change; only send it if the HTML changed.

    `registry` needs `version`, `closing` and `wait_for_change()` (ImportRegistry,
    ProcessRegistry). `template` is a loaded Jinja template, rendered with
    `groups=build(registry)`.
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
