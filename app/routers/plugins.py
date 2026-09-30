from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import TEMPLATES_DIR
from app.services.plugins import defaults_hash, get_panel_plugins, ui_defaults

router = APIRouter(tags=["plugins"])
templates = Jinja2Templates(TEMPLATES_DIR)


@router.get("/plugins/all", response_class=HTMLResponse)
async def all_plugins(request: Request):
    """Library side panel: manifest plugins with their commands and settings."""
    plugins = []
    for plugin in get_panel_plugins():
        defaults = ui_defaults(plugin)
        plugins.append((plugin, defaults, defaults_hash(defaults)))
    return templates.TemplateResponse(request, "library/plugin_panel.html", {"plugins": plugins})
