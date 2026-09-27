import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import TEMPLATES_DIR
from app.services import get_loaded_plugins

logger = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["plugins"])
templates = Jinja2Templates(TEMPLATES_DIR)


@router.get("/plugins/all", response_class=HTMLResponse)
async def all_plugins(
    request: Request,
):
    """Main library page."""

    plugins = get_loaded_plugins()
    print([(name, plugin) for name, plugin in plugins.items()])


    response = templates.TemplateResponse(
        request,
        "library/plugin_panel.html",
        {"plugins": [(name, plugin) for name, plugin in plugins.items()]},
    )
    return response
