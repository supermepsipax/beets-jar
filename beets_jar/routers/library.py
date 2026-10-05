import logging

from beets.library import Album, Item, Library
from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.sse import EventSourceResponse
from markupsafe import escape

from beets_jar.dependencies import get_lib, get_processes, get_runner
from beets_jar.models.library import Kind
from beets_jar.processes.presenters import panel_groups
from beets_jar.processes.registry import ProcessRegistry
from beets_jar.processes.runner import ProcessRunner
from beets_jar.processes.specs import build_specs
from beets_jar.services.library import get_album_or_item, result_row
from beets_jar.services.streaming import panel_stream
from beets_jar.templating import templates

logger = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["library"])


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
        "library/results.html",
        context,
    )
    return response


def _delete_modal(
    request: Request, kind: Kind, obj: Album | Item, error: str | None = None
):
    return templates.TemplateResponse(
        request,
        "modals/library_delete_modal.html",
        {
            "kind": kind,
            "row": result_row(obj),
            "track_count": len(obj.items()) if isinstance(obj, Album) else None,
            "error": error,
        },
    )


def _deleted_row(kind: Kind, id_: int) -> HTMLResponse:
    """Empty main content (clears #modal-root, which closes the dialog) plus an
    out-of-band swap that turns the result row into a "Deleted" placeholder."""
    return HTMLResponse(
        f'<li id="row-{kind}-{id_}" class="result-row is-deleted" hx-swap-oob="true">'
        '<span class="result-main"><strong>Deleted</strong></span></li>'
    )


@router.get("/library/modal/delete", response_class=HTMLResponse)
async def delete_modal(
    request: Request, kind: Kind, id: int, lib: Library = Depends(get_lib)
):
    obj = get_album_or_item(lib, kind, id)
    if obj is None:
        return _deleted_row(kind, id)  # already gone: just update the row
    return _delete_modal(request, kind, obj)


@router.delete("/api/library/{kind}/{id}", response_class=HTMLResponse)
async def delete_object(
    request: Request,
    kind: Kind,
    id: int,
    delete_files: bool = False,  # query string: htmx sends DELETE form fields in the URL
    lib: Library = Depends(get_lib),
):
    obj = get_album_or_item(lib, kind, id)
    if obj is not None:
        try:
            await run_in_threadpool(obj.remove, delete=delete_files)
        except Exception as e:
            logger.exception("Failed to delete %s %s", kind, id)
            return _delete_modal(request, kind, obj, error=f"Couldn't delete: {e}")
    return _deleted_row(kind, id)


def _note(text: str) -> HTMLResponse:
    """Short message next to the Process button."""
    return HTMLResponse(str(escape(text)))


@router.post("/api/library/process", response_class=HTMLResponse)
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
    return _note("Queued: " + ", ".join(spec.name for spec in specs))


@router.get("/library/stream/processes", response_class=EventSourceResponse)
async def stream_processes(
    request: Request, processes: ProcessRegistry = Depends(get_processes)
):
    template = templates.get_template("library/process_panel.html")
    async for event in panel_stream(request, processes, template, panel_groups):
        yield event


@router.post("/api/processes/{process_id}/cancel")
async def cancel_process(process_id: str, runner: ProcessRunner = Depends(get_runner)):
    runner.cancel(process_id)
    return Response(status_code=204)  # the panel updates through the stream


@router.post("/api/processes/{process_id}/restart")
async def restart_process(
    process_id: str,
    processes: ProcessRegistry = Depends(get_processes),
    runner: ProcessRunner = Depends(get_runner),
):
    state = processes.processes.get(process_id)
    if state is not None and state.finished:
        runner.enqueue(state.spec, process_id)
    return Response(status_code=204)


@router.delete("/api/processes/{process_id}")
async def dismiss_process(
    process_id: str, processes: ProcessRegistry = Depends(get_processes)
):
    return Response(status_code=204 if processes.dismiss(process_id) else 409)
