from urllib.parse import quote

from beets import config
from beets.library import Library
from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.sse import EventSourceResponse

from beets_jar.dependencies import get_import_registry, get_lib
from beets_jar.imports import presenters
from beets_jar.imports.registry import ImportRegistry
from beets_jar.imports.replies import build_reply
from beets_jar.imports.session import start_web_import, validate_import_path
from beets_jar.models.imports import FINISHED_SESSION_STATUSES, ChoiceType
from beets_jar.services.streaming import panel_stream
from beets_jar.templating import templates

router = APIRouter(tags=["imports"])


@router.get("/import", response_class=HTMLResponse)
async def import_page(
    request: Request, session: str | None = None, task: str | None = None
):
    """Main import page. `?session=` (and optionally `&task=`) focus the work area."""
    work_url = _work_url(session, task, follow=True)
    return templates.TemplateResponse(request, "imports.html", {"work_url": work_url})


@router.get("/import/stream/in-progress", response_class=EventSourceResponse)
async def stream_in_progress(
    request: Request, import_registry: ImportRegistry = Depends(get_import_registry)
):
    template = templates.get_template("imports/in_progress_panel.html")
    async for event in panel_stream(request, import_registry, template, presenters.in_progress):
        yield event


@router.get("/import/stream/finished", response_class=EventSourceResponse)
async def stream_finished(
    request: Request, import_registry: ImportRegistry = Depends(get_import_registry)
):
    template = templates.get_template("imports/finished_panel.html")
    async for event in panel_stream(request, import_registry, template, presenters.finished):
        yield event


# ---------------------------------------------------------------- work-area rendering


def _work_url(session_id: str | None = None, task_id: str | None = None, *, follow=False) -> str:
    """URL of the work-area route that shows a task, a session's first prompt, or the next prompt."""
    if session_id and task_id:
        url = f"/import/work/{quote(session_id, safe='')}/{quote(task_id, safe='')}"
        return f"{url}?follow=1" if follow else url
    if session_id:
        return f"/import/work?session={quote(session_id, safe='')}"
    return "/import/work"


def _choose_url(session_id: str, prompt_id: str) -> str:
    """Where a prompt's forms post their answer."""
    return f"/import/sessions/{session_id}/prompts/{prompt_id}/choose"


def _work(request: Request, name: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, f"imports/{name}.html", context)


def render_idle(request, import_registry, *, note=None, error=None):
    # (label, folder) buttons from the jar.import_paths config
    quick_imports = [
        (label, path.as_filename()) for label, path in config["jar"]["import_paths"].items()
    ]
    return _work(
        request,
        "work_idle",
        pending=import_registry.pending_count(),
        quick_imports=quick_imports,
        note=note,
        error=error,
    )


def render_next(request, import_registry, *, note=None, prefer_session=None):
    next_up = import_registry.next_needing_input(prefer_session)
    if next_up is None:
        return render_idle(request, import_registry, note=note)
    session_id, task_id = next_up
    return render_task(request, import_registry, session_id, task_id, note=note)


def render_session(request, import_registry, session_id):
    """Review-link entry: this session's first prompt; if it has none yet but is
    still running, wait for one; otherwise continue with the normal next prompt."""
    session = import_registry.sessions.get(session_id)
    if session is None:
        return render_next(request, import_registry, note="That import is no longer here.")
    next_up = import_registry.next_needing_input(prefer_session=session_id)
    if next_up and next_up[0] == session_id:
        return render_task(request, import_registry, *next_up)
    if session.status not in FINISHED_SESSION_STATUSES:
        return _render_waiting(request, session, None, _work_url(session_id), "Looking up…")
    return render_next(
        request, import_registry, note=f"{presenters.session_name(session)} doesn't need anything."
    )


def render_task(
    request, import_registry, session_id, task_id=None, *, follow=False, note=None, error=None
):
    """The prompt for one task (or the session's resume prompt when task_id is None).

    With nothing to ask: show "Searching…" if we're following a search, otherwise
    fall through to the next task that needs the user.
    """
    session = import_registry.sessions.get(session_id)
    task = None
    prompt = None
    if session is not None and task_id is None:
        prompt = session.open_prompt
    elif session is not None:
        task = session.tasks.get(task_id)
        prompt = task.open_prompt if task else None

    if prompt is None:
        if follow and task is not None and task.outcome is None:
            poll_url = _work_url(session_id, task_id, follow=True)
            return _render_waiting(request, session, task, poll_url, "Searching…")
        return render_next(request, import_registry, note=note, prefer_session=session_id)

    context = {
        "session": session,
        "task": task,
        "prompt": prompt,
        "note": note,
        "error": error,
        "choose_url": _choose_url(session_id, prompt.prompt_id),
    }
    if prompt.kind == "candidate":
        context.update(_candidate_context(prompt))
    return _work(request, "work_task", **context)


def _candidate_context(prompt) -> dict:
    """The candidate list, and the first candidate's details, for a candidate prompt."""
    # Reading prompt.task is safe: its pipeline thread is blocked on reply.get()
    candidates = [
        presenters.candidate_view(match, index)
        for index, match in enumerate(prompt.task.candidates or [], start=1)
    ]
    return {
        "candidates": candidates,
        "candidate": candidates[0] if candidates else None,
        "is_album": prompt.task.is_album,
    }


def _render_waiting(request, session, task, poll_url: str, message: str):
    """A placeholder card that polls `poll_url` until there's something to show."""
    return _work(
        request, "work_waiting", session=session, task=task, poll_url=poll_url, message=message
    )


# ---------------------------------------------------------------- work-area routes


@router.get("/import/work", response_class=HTMLResponse)
async def work_next(
    request: Request, session: str | None = None, import_registry: ImportRegistry = Depends(get_import_registry)
):
    if session:
        return render_session(request, import_registry, session)
    return render_next(request, import_registry)


@router.get("/import/work/idle", response_class=HTMLResponse)
async def work_idle(request: Request, import_registry: ImportRegistry = Depends(get_import_registry)):
    return render_idle(request, import_registry)


@router.get("/import/work/{session_id}", response_class=HTMLResponse)
async def work_session(
    request: Request, session_id: str, import_registry: ImportRegistry = Depends(get_import_registry)
):
    return render_task(request, import_registry, session_id)


@router.get("/import/work/{session_id}/{task_id}", response_class=HTMLResponse)
async def work_task(
    request: Request,
    session_id: str,
    task_id: str,
    follow: bool = False,
    import_registry: ImportRegistry = Depends(get_import_registry),
):
    return render_task(request, import_registry, session_id, task_id, follow=follow)


@router.get(
    "/import/work/{session_id}/prompts/{prompt_id}/candidates/{index}",
    response_class=HTMLResponse,
)
async def candidate_detail(
    request: Request,
    session_id: str,
    prompt_id: str,
    index: int,
    import_registry: ImportRegistry = Depends(get_import_registry),
):
    found = import_registry.find_open_prompt(session_id, prompt_id)
    candidates = []
    if found is not None:
        _, prompt = found
        if prompt.kind == "candidate":
            candidates = prompt.task.candidates or []
    if not 1 <= index <= len(candidates):
        return HTMLResponse(
            '<p class="work-note">This choice is no longer available.</p>'
        )
    return _work(
        request,
        "candidate_detail",
        candidate=presenters.candidate_view(candidates[index - 1], index),
        choose_url=_choose_url(session_id, prompt_id),
    )


# ---------------------------------------------------------------- actions


@router.post("/import/start", response_class=HTMLResponse)
async def start_import(
    request: Request,
    path: str = Form(""),
    lib: Library = Depends(get_lib),
    import_registry: ImportRegistry = Depends(get_import_registry),
):
    path = validate_import_path(path)
    if path is None:
        return render_idle(
            request, import_registry, error="That folder doesn't exist on the server."
        )
    start_web_import(lib, import_registry, paths=[path])
    return render_idle(request, import_registry, note="Import started.")



@router.post(
    "/import/sessions/{session_id}/prompts/{prompt_id}/choose",
    response_class=HTMLResponse,
)
async def answer_prompt(
    request: Request,
    session_id: str,
    prompt_id: str,
    choice_type: str = Form(...),
    value: str = Form(...),
    artist: str = Form(""),
    query: str = Form(""),
    mbid: str = Form(""),
    import_registry: ImportRegistry = Depends(get_import_registry),
):
    """Answer a prompt, then return whatever the work area should show next.

    Always 200 with HTML, so htmx never has to deal with error statuses.
    """
    found = import_registry.find_open_prompt(session_id, prompt_id)
    if found is None:
        return render_next(request, import_registry, note="That choice was already made.")
    task_id, prompt = found

    try:
        reply = build_reply(
            prompt, choice_type, value, artist.strip(), query.strip(), mbid.strip()
        )
    except ValueError as error:
        return render_task(request, import_registry, session_id, task_id, error=str(error))

    prompt.answered = True  # before put(): a double click can't send two replies
    prompt.reply.put(reply)

    # A search or ID lookup: show "Searching…" until its candidates arrive
    starts_search = (
        prompt.kind == "candidate"
        and choice_type == "action"
        and value in (ChoiceType.SEARCH, ChoiceType.ID)
    )
    if starts_search:
        return render_task(request, import_registry, session_id, task_id, follow=True)
    if task_id is not None:
        await import_registry.wait_for_followup(session_id, task_id, prompt_id)
    return render_task(request, import_registry, session_id, task_id)


@router.post("/import/sessions/{session_id}/tasks/{task_id}/restart")
async def restart_task(
    session_id: str,
    task_id: str,
    lib: Library = Depends(get_lib),
    import_registry: ImportRegistry = Depends(get_import_registry),
):
    task = import_registry.get_task(session_id, task_id)
    if task is not None and presenters.can_restart(task):
        import_registry.mark_restarted(session_id, task_id)
        start_web_import(lib, import_registry, list(task.summary.raw_paths), restart=True)
    return Response(status_code=204)  # panels update through the stream


@router.get("/import/modal/clear", response_class=HTMLResponse)
async def clear_finished_modal(
    request: Request, import_registry: ImportRegistry = Depends(get_import_registry)
):
    return templates.TemplateResponse(
        request, "modals/import_clear_modal.html", {"count": import_registry.finished_count()}
    )


@router.get("/import/modal/abort/{session_id}/{prompt_id}", response_class=HTMLResponse)
async def abort_modal(
    request: Request,
    session_id: str,
    prompt_id: str,
    import_registry: ImportRegistry = Depends(get_import_registry),
):
    found = import_registry.find_open_prompt(session_id, prompt_id)
    if found is None:
        return HTMLResponse("")  # prompt already gone: nothing to confirm
    _, prompt = found
    abort_choice = next(
        (choice for choice in prompt.choices if choice.short == ChoiceType.ABORT), None
    )
    if abort_choice is None:
        return HTMLResponse("")
    return templates.TemplateResponse(
        request,
        "modals/import_abort_modal.html",
        {
            "session": import_registry.sessions[session_id],
            "choose_url": _choose_url(session_id, prompt_id),
            "value": abort_choice.short,
        },
    )


@router.delete("/import/sessions", response_class=HTMLResponse)
async def dismiss_finished_sessions(import_registry: ImportRegistry = Depends(get_import_registry)):
    import_registry.dismiss_finished()
    # Empty body swapped into #modal-root removes (closes) the confirm dialog;
    # the Finished panel updates through the stream.
    return HTMLResponse("")


@router.delete("/import/sessions/{session_id}")
async def dismiss_session(
    session_id: str, import_registry: ImportRegistry = Depends(get_import_registry)
):
    if not import_registry.dismiss(session_id):
        return Response(status_code=409)
    return Response(status_code=204)
