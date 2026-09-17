from beets.dbcore import Results
from typing import Optional
from beets.library import Library, Album, Item
from app import get_lib, TEMPLATES_DIR
import logging
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse

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
    lib: Library = Depends(get_lib),
):
    """Main library page."""
    # for item in lib.items():
    #     logger.info(item)
    # for album in lib.albums():
    #     logger.info(album)

    response = templates.TemplateResponse(
        request,
        "library.html",
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
    album: str | None = None,
):
    """Main library page."""

    show_only_albums = album is not None

    if show_only_albums:
        results: Results[Album] = lib.albums(query)
    else:
        results: Results[Item] = lib.items(query)

    response = templates.TemplateResponse(
        request,
        "partials/items.html",
        {
            "items": results,
        },

    )
    return response
