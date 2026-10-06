import logging

from beets.library import Album, Item, Library
from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.sse import EventSourceResponse
from markupsafe import escape

from beets_jar.dependencies import get_lib, get_process_registry, get_runner
from beets_jar.models.library import Kind
from beets_jar.processes.presenters import panel_groups
from beets_jar.processes.registry import ProcessRegistry
from beets_jar.processes.runner import ProcessRunner
from beets_jar.processes.specs import build_specs
from beets_jar.services.library import get_album_or_item, result_row
from beets_jar.services.plugins import get_panel_plugins
from beets_jar.services.streaming import panel_stream
from beets_jar.templating import templates

logger = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["library"])


@router.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse(url="/library", status_code=302)


@router.get("/library", response_class=HTMLResponse)
async def library_page(request: Request):
    """Main library page."""
    return templates.TemplateResponse(request, "library.html", {})


@router.get("/library/stats", response_class=HTMLResponse)
async def library_stats(
    request: Request,
    lib: Library = Depends(get_lib),
):
    """Track and album counts shown in the nav header."""

    # COUNT(*) instead of len(lib.items()) so we don't load every row just to count it
    with lib.transaction() as transaction:
        item_count = transaction.query(f"SELECT COUNT(*) FROM {Item._table}")[0][0]
        album_count = transaction.query(f"SELECT COUNT(*) FROM {Album._table}")[0][0]

    return templates.TemplateResponse(
        request,
        "library/nav_stats.html",
        {"item_count": item_count, "album_count": album_count},
    )


@router.get("/library/plugins", response_class=HTMLResponse)
async def plugin_panel(request: Request):
    """Plugins side panel: manifest plugins with their commands and settings."""
    return templates.TemplateResponse(
        request, "library/plugin_panel.html", {"plugins": get_panel_plugins()}
    )


@router.get("/library/query-results", response_class=HTMLResponse)
async def query_results(
    request: Request,
    lib: Library = Depends(get_lib),
    query: str = "",
    album: bool = False,
):
    """Search results for the library page's query box."""

    query = query.strip()
    kind: Kind = "album" if album else "item"
    context = {"kind": kind, "query": query, "rows": [], "error": None}
    if query:
        results = lib.albums(query) if album else lib.items(query)
        context["rows"] = [result_row(result) for result in results]

    return templates.TemplateResponse(request, "library/results.html", context)


def _delete_modal(
    request: Request, kind: Kind, album_or_item: Album | Item, error: str | None = None
):
    is_album = isinstance(album_or_item, Album)
    return templates.TemplateResponse(
        request,
        "modals/library_delete_modal.html",
        {
            "kind": kind,
            "row": result_row(album_or_item),
            "track_count": len(album_or_item.items()) if is_album else None,
            "error": error,
        },
    )


def _deleted_row(kind: Kind, album_or_item_id: int) -> HTMLResponse:
    """Empty main content (clears #modal-root, which closes the dialog) plus an
    out-of-band swap that turns the result row into a "Deleted" placeholder."""
    return HTMLResponse(
        f'<li id="row-{kind}-{album_or_item_id}" class="result-row is-deleted" hx-swap-oob="true">'
        '<span class="result-main"><strong>Deleted</strong></span></li>'
    )


@router.get("/library/modal/delete", response_class=HTMLResponse)
async def delete_modal(
    request: Request, kind: Kind, album_or_item_id: int, lib: Library = Depends(get_lib)
):
    album_or_item = get_album_or_item(lib, kind, album_or_item_id)
    if album_or_item is None:
        return _deleted_row(kind, album_or_item_id)  # already gone: just update the row
    return _delete_modal(request, kind, album_or_item)


@router.delete("/library/rows/{kind}/{album_or_item_id}", response_class=HTMLResponse)
async def delete_album_or_item(
    request: Request,
    kind: Kind,
    album_or_item_id: int,
    delete_files: bool = False,  # query string: htmx sends DELETE form fields in the URL
    lib: Library = Depends(get_lib),
):
    album_or_item = get_album_or_item(lib, kind, album_or_item_id)
    if album_or_item is not None:
        try:
            await run_in_threadpool(album_or_item.remove, delete=delete_files)
        except Exception as error:
            logger.exception("Failed to delete %s %s", kind, album_or_item_id)
            return _delete_modal(
                request, kind, album_or_item, error=f"Couldn't delete: {error}"
            )
    return _deleted_row(kind, album_or_item_id)


def _note(text: str) -> HTMLResponse:
    """Short message next to the Process button."""
    return HTMLResponse(str(escape(text)))


@router.post("/library/processes", response_class=HTMLResponse)
async def queue_processes(
    request: Request,
    lib: Library = Depends(get_lib),
    runner: ProcessRunner = Depends(get_runner),
):
    """One process per switched-on plugin, in panel order (see build_specs)."""
    form = await request.form()
    try:
        specs = build_specs(lib, form)
    except ValueError as error:
        return _note(str(error))
    for spec in specs:
        runner.enqueue(spec)
    return _note("Queued: " + ", ".join(spec.display_name for spec in specs))


@router.get("/library/stream/processes", response_class=EventSourceResponse)
async def stream_processes(
    request: Request, process_registry: ProcessRegistry = Depends(get_process_registry)
):
    template = templates.get_template("library/process_panel.html")
    async for event in panel_stream(request, process_registry, template, panel_groups):
        yield event


@router.post("/library/processes/{process_id}/cancel")
async def cancel_process(process_id: str, runner: ProcessRunner = Depends(get_runner)):
    runner.cancel(process_id)
    return Response(status_code=204)  # the panel updates through the stream


@router.post("/library/processes/{process_id}/restart")
async def restart_process(
    process_id: str,
    process_registry: ProcessRegistry = Depends(get_process_registry),
    runner: ProcessRunner = Depends(get_runner),
):
    process_state = process_registry.processes.get(process_id)
    if process_state is not None and process_state.finished:
        runner.enqueue(process_state.spec, process_id)
    return Response(status_code=204)


@router.delete("/library/processes/{process_id}")
async def dismiss_process(
    process_id: str, process_registry: ProcessRegistry = Depends(get_process_registry)
):
    return Response(status_code=204 if process_registry.dismiss(process_id) else 409)
