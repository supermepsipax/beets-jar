import asyncio
import logging
import os
import threading
from pathlib import Path

from beets.library import Library
from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.templating import Jinja2Templates

from app import TEMPLATES_DIR, get_imports, get_lib
from app.imports import ImportRegistry, views
from app.imports.registry import open_prompt, open_session_prompt
from app.models.web_choice import ChoiceType, WebChoice
from app.services import WebImportSession

logger = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["importer"])
templates = Jinja2Templates(TEMPLATES_DIR)
templates.env.filters["short_path"] = views.short_path
templates.env.globals.update(
    session_name=views.session_name,
    task_name=views.task_name,
    task_label=views.task_label,
    outcome_tag=views.outcome_tag,
    can_restart=views.can_restart,
    choice_label=views.choice_label,
    open_prompt=open_prompt,
)


@router.get("/import", response_class=HTMLResponse)
async def search_page(
    request: Request,
):
    """Main importer page."""

    response = templates.TemplateResponse(
        request,
        "importer.html",
        {},
    )
    return response


async def _panel_stream(
    request: Request, imports: ImportRegistry, template_path: str, build
):
    """Re-render one panel on every registry change; only send it if the HTML changed."""
    template = templates.get_template(template_path)
    last_version = -1
    last_html = None
    while not (imports.closing or await request.is_disconnected()):
        if imports.version != last_version:
            last_version = imports.version
            html = template.render(groups=build(imports))
            if html != last_html:
                last_html = html
                yield ServerSentEvent(raw_data=html)
        try:
            await asyncio.wait_for(imports.wait_for_change(last_version), timeout=30)
        except TimeoutError:
            yield ServerSentEvent(comment="keepalive")


@router.get("/import/stream/in-progress", response_class=EventSourceResponse)
async def stream_in_progress(
    request: Request, imports: ImportRegistry = Depends(get_imports)
):
    async for event in _panel_stream(
        request, imports, "imports/panel_in_progress.html", views.in_progress
    ):
        yield event


@router.get("/import/stream/finished", response_class=EventSourceResponse)
async def stream_finished(
    request: Request, imports: ImportRegistry = Depends(get_imports)
):
    async for event in _panel_stream(
        request, imports, "imports/panel_finished.html", views.finished
    ):
        yield event


# ---------------------------------------------------------------- work-area rendering


def _work(request: Request, name: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, f"imports/{name}.html", context)


DEV_TEST_DIR = Path(__file__).resolve().parents[2] / "dev" / "downloads" / "test"


def _test_imports() -> list[tuple[str, str]]:
    """(label, path) for the dev test folders, plus one for the whole folder.

    Empty when the folder doesn't exist, so the buttons only show up in a dev checkout.
    """
    if not DEV_TEST_DIR.is_dir():
        return []
    folders = sorted(p for p in DEV_TEST_DIR.iterdir() if p.is_dir())
    return [(p.name, str(p)) for p in folders] + [("All of them", str(DEV_TEST_DIR))]


def render_idle(request, imports, *, note=None, error=None):
    return _work(
        request,
        "work_idle",
        pending=imports.pending_count(),
        test_imports=_test_imports(),
        note=note,
        error=error,
    )


def render_next(request, imports, *, note=None):
    """The oldest prompt waiting on the user, or the idle view."""
    next_up = imports.next_needing_input()
    if next_up is None:
        return render_idle(request, imports, note=note)
    session_id, task_id = next_up
    return render_task(request, imports, session_id, task_id, note=note)


def render_task(
    request, imports, session_id, task_id=None, *, follow=False, note=None, error=None
):
    """The prompt for one task (or the session's resume prompt when task_id is None).

    With nothing to ask: show "Searching…" if we're following a search, otherwise
    fall through to the next task that needs the user.
    """
    session = imports.sessions.get(session_id)
    task = session.tasks.get(task_id) if session and task_id else None
    if session is None:
        prompt = None
    elif task_id is None:
        prompt = open_session_prompt(session)
    else:
        prompt = open_prompt(task)

    if prompt is None:
        if follow and task is not None and task.outcome is None:
            return _work(request, "work_waiting", session=session, task=task)
        return render_next(request, imports, note=note)

    context = {
        "session": session,
        "task": task,
        "prompt": prompt,
        "note": note,
        "error": error,
        "choose_url": f"/api/import/sessions/{session_id}/prompts/{prompt.prompt_id}/choose",
    }
    if prompt.kind == "candidate":
        # Reading prompt.task is safe: its pipeline thread is blocked on reply.get()
        candidates = [
            views.candidate_view(match, index)
            for index, match in enumerate(prompt.task.candidates or [], start=1)
        ]
        context.update(
            candidates=candidates,
            candidate=candidates[0] if candidates else None,
            is_album=prompt.task.is_album,
        )
    return _work(request, "work_task", **context)


# ---------------------------------------------------------------- work-area routes


@router.get("/import/work", response_class=HTMLResponse)
async def work_next(request: Request, imports: ImportRegistry = Depends(get_imports)):
    return render_next(request, imports)


@router.get("/import/work/idle", response_class=HTMLResponse)
async def work_idle(request: Request, imports: ImportRegistry = Depends(get_imports)):

    return render_idle(request, imports)


@router.get("/import/work/{session_id}", response_class=HTMLResponse)
async def work_session(
    request: Request, session_id: str, imports: ImportRegistry = Depends(get_imports)
):
    return render_task(request, imports, session_id)


@router.get("/import/work/{session_id}/{task_id}", response_class=HTMLResponse)
async def work_task(
    request: Request,
    session_id: str,
    task_id: str,
    follow: bool = False,
    imports: ImportRegistry = Depends(get_imports),
):
    return render_task(request, imports, session_id, task_id, follow=follow)


@router.get(
    "/import/work/{session_id}/prompts/{prompt_id}/candidates/{index}",
    response_class=HTMLResponse,
)
async def candidate_detail(
    request: Request,
    session_id: str,
    prompt_id: str,
    index: int,
    imports: ImportRegistry = Depends(get_imports),
):
    located = imports.locate_prompt(session_id, prompt_id)
    prompt = located[1] if located else None
    candidates = []
    if prompt and not prompt.answered and prompt.kind == "candidate":
        candidates = prompt.task.candidates or []
    if not 1 <= index <= len(candidates):
        return HTMLResponse(
            '<p class="work-note">This choice is no longer available.</p>'
        )
    return _work(
        request,
        "candidate_detail",
        candidate=views.candidate_view(candidates[index - 1], index),
        choose_url=f"/api/import/sessions/{session_id}/prompts/{prompt_id}/choose",
    )


# ---------------------------------------------------------------- actions


def _start_session(
    lib: Library, paths: list, *, restart: bool = False
) -> WebImportSession:
    session = WebImportSession(
        lib=lib, paths=paths, loghandler=None, query=None, restart=restart
    )
    threading.Thread(target=session.run, daemon=True).start()
    return session


@router.post("/api/import/start", response_class=HTMLResponse)
async def start_import(
    request: Request,
    path: str = Form(""),
    lib: Library = Depends(get_lib),
    imports: ImportRegistry = Depends(get_imports),
):
    path = path.strip()
    if not path or not os.path.exists(path):
        return render_idle(
            request, imports, error="That folder doesn't exist on the server."
        )
    _start_session(lib, [path])
    return render_idle(request, imports, note="Import started.")


@router.post(
    "/api/import/sessions/{session_id}/prompts/{prompt_id}/choose",
    response_class=HTMLResponse,
)
async def choose(
    request: Request,
    session_id: str,
    prompt_id: str,
    type: str = Form(...),
    value: str = Form(...),
    artist: str = Form(""),
    query: str = Form(""),
    mbid: str = Form(""),
    imports: ImportRegistry = Depends(get_imports),
):
    """Answer a prompt, then return whatever the work area should show next.

    Always 200 with HTML, so htmx never has to deal with error statuses.
    """
    located = imports.locate_prompt(session_id, prompt_id)
    if located is None or located[1].answered:
        return render_next(request, imports, note="That choice was already made.")
    task_id, prompt = located

    try:
        reply = _build_reply(
            prompt, type, value, artist.strip(), query.strip(), mbid.strip()
        )
    except ValueError as e:
        return render_task(request, imports, session_id, task_id, error=str(e))

    prompt.answered = True  # before put(): a double click can't send two replies
    prompt.reply.put(reply)

    if (
        prompt.kind == "candidate"
        and type == "action"
        and value in (ChoiceType.SEARCH, ChoiceType.ID)
    ):
        return render_task(request, imports, session_id, task_id, follow=True)
    if task_id is not None:
        await imports.wait_for_followup(session_id, task_id, prompt_id)
    return render_task(request, imports, session_id, task_id)


def _build_reply(prompt, type: str, value: str, artist: str, query: str, mbid: str):
    """Turn form fields into what the blocked pipeline thread expects. Raises ValueError."""
    if prompt.kind == "resume":
        return value == "yes"

    if prompt.kind == "candidate" and type == "candidate":
        candidates = prompt.task.candidates or []
        try:
            index = int(value) - 1
        except ValueError:
            raise ValueError("Unknown candidate.") from None
        if not 0 <= index < len(candidates):
            raise ValueError("Unknown candidate.")
        return WebChoice(candidates[index], {})

    choice = next((c for c in prompt.choices if c.short == value), None)
    if choice is None:
        raise ValueError("Unknown action.")

    if prompt.kind == "candidate":
        if choice.short == ChoiceType.SEARCH:
            if not query:
                raise ValueError("Enter something to search for.")
            return WebChoice(choice, {"artist": artist, "query": query})
        if choice.short == ChoiceType.ID:
            if not mbid:
                raise ValueError("Enter a MusicBrainz ID.")
            return WebChoice(choice, {"mbid": mbid})

    return WebChoice(choice, {})


@router.post("/api/import/sessions/{session_id}/tasks/{task_id}/restart")
async def restart_task(
    session_id: str,
    task_id: str,
    lib: Library = Depends(get_lib),
    imports: ImportRegistry = Depends(get_imports),
):
    task = imports.get_task(session_id, task_id)
    if task is not None and views.can_restart(task):
        imports.mark_restarted(session_id, task_id)
        _start_session(lib, list(task.summary.raw_paths), restart=True)
    return Response(status_code=204)  # panels update through the stream


@router.delete("/api/import/sessions/{session_id}")
async def dismiss_session(
    session_id: str, imports: ImportRegistry = Depends(get_imports)
):
    if not imports.dismiss(session_id):
        return Response(status_code=409)
    return Response(status_code=204)
