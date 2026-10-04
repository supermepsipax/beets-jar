import asyncio

from fastapi import Request
from fastapi.sse import ServerSentEvent


async def panel_stream(request: Request, registry, template, build):
    """Re-render one side panel on every registry change; only send it if the HTML changed.

    `registry` needs `version`, `closing` and `wait_for_change()` (ImportRegistry,
    ProcessRegistry). `template` is a loaded Jinja template, rendered with
    `groups=build(registry)`.
    """
    last_version, last_html = -1, None
    while not (registry.closing or await request.is_disconnected()):
        if registry.version != last_version:
            last_version = registry.version
            html = template.render(groups=build(registry))
            if html != last_html:
                last_html = html
                yield ServerSentEvent(raw_data=html)
        try:
            await asyncio.wait_for(registry.wait_for_change(last_version), timeout=30)
        except TimeoutError:
            yield ServerSentEvent(comment="keepalive")
