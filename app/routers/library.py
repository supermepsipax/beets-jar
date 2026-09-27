import logging
from typing import Optional

from beets.dbcore import Results
from beets.library import Album, Item, Library
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import TEMPLATES_DIR, get_lib
from app.services import get_loaded_plugins

logger = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["library"])
templates = Jinja2Templates(TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
):
    return RedirectResponse(url="/library", status_code=302)


@router.get("/library", response_class=HTMLResponse)
async def library_page(
    request: Request,
):
    """Main library page."""

    plugins = get_loaded_plugins()

    response = templates.TemplateResponse(
        request,
        "library.html",
        {},
    )
    return response


@router.get("/library/work", response_class=HTMLResponse)
async def library_work_area(
    request: Request,
    lib: Library = Depends(get_lib),
):
    """Main library page."""

    response = templates.TemplateResponse(
        request,
        "library/work_idle.html",
        {
            "item_count": len(lib.items()),
            "album_count": len(lib.albums()),
        },
    )
    return response


@router.get("/api/items", response_class=HTMLResponse)
async def get_items(
    request: Request,
    lib: Library = Depends(get_lib),
    query: str = "",
    album: bool = False,
):
    """Main library page."""

    if album:
        albums: Results[Album] = lib.albums(query)
        items = None
    else:
        items: Results[Item] = lib.items(query)
        albums = None

    response = templates.TemplateResponse(
        request,
        "partials/items.html",
        {
            "items": items,
            "albums": albums,
        },
    )
    return response
