from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from beets_jar.services.plugins import get_panel_plugins
from beets_jar.templating import templates

router = APIRouter(tags=["plugins"])


@router.get("/plugins/all", response_class=HTMLResponse)
async def all_plugins(request: Request):
    """Library side panel: manifest plugins with their commands and settings."""
    return templates.TemplateResponse(
        request, "library/plugin_panel.html", {"plugins": get_panel_plugins()}
    )
