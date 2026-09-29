import logging
from dataclasses import dataclass
from typing import Literal

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

Kind = Literal["album", "item"]
@dataclass(frozen=True)
class ResultRow:
    id: int
    title: str
    subtitle: str
    year: int | None

def result_row(obj: Album | Item) -> ResultRow:
    if isinstance(obj, Album):
        return ResultRow(obj.id, obj.album or "Unknown album", obj.albumartist or "", obj.year or None)
    subtitle = " · ".join(value for value in (obj.artist, obj.album) if value)
    return ResultRow(obj.id, obj.title or "Unknown track", subtitle, obj.year or None)


def get_object(lib: Library, kind: Kind, id_: int) -> Album | Item | None:
    return lib.get_album(id_) if kind == "album" else lib.get_item(id_)


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

    response = templates.TemplateResponse(
        request,
        "library.html",
        {},
    )
    return response


@router.get("/library/work", response_class=HTMLResponse)
async def library_work_area(
    request: Request,
):
    """Main library page."""

    response = templates.TemplateResponse(
        request,
        "library/work_idle.html",
        {},
    )
    return response

@router.get("/library/stats", response_class=HTMLResponse)
async def library_stats(
    request: Request,
    lib: Library = Depends(get_lib),
):
    """Track and album counts shown in the nav header."""

    # COUNT(*) instead of len(lib.items()) so we don't load every row just to count it
    with lib.transaction() as tx:
        item_count = tx.query(f"SELECT COUNT(*) FROM {Item._table}")[0][0]
        album_count = tx.query(f"SELECT COUNT(*) FROM {Album._table}")[0][0]

    response = templates.TemplateResponse(
        request,
        "library/nav_stats.html",
        {
            "item_count": item_count,
            "album_count": album_count,
        },
    )
    return response

@router.get("/library/query_results", response_class=HTMLResponse)
async def get_query_results(
    request: Request,
    lib: Library = Depends(get_lib),
    query: str = "",
    album: bool = False,
):
    """Main library page."""

    query = query.strip()
    kind: Kind = "album" if album else "item"
    context = {"kind": kind, "query": query, "rows": [], "error": None}
    if query:
        results = lib.albums(query) if album else lib.items(query)
        context["rows"] = [result_row(result) for result in results]

    response = templates.TemplateResponse(
        request,
        "library/library_results.html",
        context,
    )
    return response
