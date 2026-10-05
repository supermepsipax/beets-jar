from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from beets_jar.services.plugins import defaults_hash, get_panel_plugins, ui_defaults
from beets_jar.templating import templates

router = APIRouter(tags=["plugins"])


@router.get("/plugins/all", response_class=HTMLResponse)
async def all_plugins(request: Request):
    """Library side panel: manifest plugins with their commands and settings."""
    plugins = []
    for plugin in get_panel_plugins():
        defaults = ui_defaults(plugin)
        plugins.append((plugin, defaults, defaults_hash(defaults)))
    return templates.TemplateResponse(request, "library/plugin_panel.html", {"plugins": plugins})
