from app.models.queues import QueueStorageType
from app.models.web_choice import ChoiceType
from fastapi.sse import EventSourceResponse, ServerSentEvent
import asyncio
from beets.library import Library
import threading
from app.services import WebImportSession
from app import get_queues, get_lib, TEMPLATES_DIR, get_imports
from app.models import QueueStorage, QueueStorageItem, WebChoice
from app.imports import ImportRegistry
import logging
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse


logger = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["importer"])
templates = Jinja2Templates(TEMPLATES_DIR)


@router.get("/import", response_class=HTMLResponse)
async def search_page(
    request: Request,
):
    """Main importer page."""

    response = templates.TemplateResponse(
        request,
        "importer.html",
        {
        },
    )
    return response

@router.get("/import/queues/stream", response_class=EventSourceResponse)
async def queues_stream(
        request: Request,
        # queues: QueueStorage = Depends(get_queues),
        imports = Depends(get_imports),
):
    last_version = -1
    while True:
        if imports.closing or await request.is_disconnected():
            break
        current_version = imports.version
        if current_version != last_version:
            last_version = current_version
            html = templates.get_template("imports/session_list.html").render(
                request=request,
                sessions=list(imports.sessions.values()),
            )
            
            yield ServerSentEvent(raw_data=html)
        
        try:
            await asyncio.wait_for(
                    imports.wait_for_change(last_version),
                    timeout=30
            )
        except TimeoutError:
            yield ServerSentEvent(comment="keepalive")

@router.post("/api/import/start")
async def start_import(
        path: str = Form(...),
        lib: Library = Depends(get_lib),
        queues: QueueStorage = Depends(get_queues),
        mbid: str = "",
):
    """Triggers an import, can have an optional mbid to help aid import"""
    import_session = WebImportSession(
            lib = lib,
            paths = [path],
            loghandler = None,
            query = None,
    )
    import_thread = threading.Thread(target=import_session.run, daemon=True)
    import_thread.start()

    return {"session_id": import_session.session_id}

@router.post("/api/import/sessions/{session_id}/prompts/{prompt_id}/choose")
async def choose(
    session_id: str,
    prompt_id: str,
    type: str = Form(...),
    value: str = Form(...),
    artist: str = Form(""),
    query: str = Form(""),
    mbid: str = Form(""),
    imports: ImportRegistry = Depends(get_imports),
):
    prompt = imports.find_prompt(session_id, prompt_id)
    if prompt is None:
        raise HTTPException(404, "Prompt not found (if may have been replaced)")
    if prompt.answered:
        raise HTTPException(409, "Prompt already answered")
    reply = _build_reply(prompt, type, value, artist, query, mbid)
    prompt.answered = True
    prompt.reply.put(reply)
    return HTMLResponse("<p> Choice submitted. </p>")

def _build_reply(prompt, type, value, artist, query, mbid):
    if prompt.kind == "resume":
        return value == "yes"

    if prompt.kind == "candidate" and type == "candidate":
        candidates = prompt.task.candidates
        index = int(value) - 1
        if not 0 <= index < len(candidates):
            raise HTTPException(400, "Unknown candidate")
        return WebChoice(candidates[index], {})

    choice = next((c for c in prompt.choices if c.short == value), None)
    if choice is None:
        raise HTTPException(400, "Unknown action")
    if prompt.kind == "candidate" and choice.short == ChoiceType.ID and mbid:
        return WebChoice(choice, {"mbid": mbid})
    if prompt.kind == "candidate" and choice.short == ChoiceType.SEARCH and artist and query:
        return WebChoice(choice, {"artist": artist, "query": query})
    return WebChoice(choice, {})
    
@router.post("/api/import/{queue_id}/choose")
async def make_import_choice(
        queue_id: str,
        type: str = Form(...),
        value: str = Form(...),
        artist: str = Form(""),
        query: str = Form(""),
        mbid: str = Form(""),
        queues: QueueStorage = Depends(get_queues),
):
    """Updates a specified WebImportSessions with a user choice"""

    queue_item: QueueStorageItem | None = queues.get(queue_id)
    if queue_item is None:
        raise HTTPException(status_code=404, detail="Import not found")
    if queue_item.queue_type == QueueStorageType.CANDIDATE:
        if type == "candidate":
            index = int(value) -1
            choice = queue_item.task.candidates[index]
            web_choice = WebChoice(choice, {})
        elif type == "action":
            choice = next(
                    (c for c in queue_item.choices if c.short == value),
                    None,
            )
            if choice is None:
                raise HTTPException(status_code=400, detail="Unknown action")
            if ChoiceType(choice.short) == ChoiceType.ID and mbid:
                web_choice = WebChoice(choice, {"mbid": mbid})
                
            elif ChoiceType(choice.short) == ChoiceType.SEARCH and artist and query:
                web_choice = WebChoice(choice, {"artist": artist, "query": query})
            else:
                web_choice = WebChoice(choice, {})
    elif queue_item.queue_type == QueueStorageType.DUPLICATE:
        if type == "action":
            choice = next(
                    (c for c in queue_item.choices if c.short == value),
                    None,
            )
            if choice is None:
                raise HTTPException(status_code=400, detail="Unknown action")
            web_choice = WebChoice(choice, {})

    elif queue_item.queue_type == QueueStorageType.RESUME:
        if type == "action":
            queue_item.queue.put("yes"==value)
            return HTMLResponse('<p>Choice submited.</p>')


    else:
        raise HTTPException(status_code=400, detail="Unknown type")

    queue_item.queue.put(web_choice)
    return HTMLResponse('<p>Choice submited.</p>')

@router.get("/api/import/debug")
async def import_debug(imports: ImportRegistry = Depends(get_imports)):
    return {
        sid: {
            "status": s.status,
            "prompt": s.prompt.prompt_id if s.prompt else None,
            "tasks": {
                tid: {
                    "paths": t.summary.paths,
                    "phase": t.phase.name,
                    "outcome": t.outcome,
                    "prompt": t.prompt.kind if t.prompt else None,
                }
                for tid, t in s.tasks.items()
            },
        }
        for sid, s in imports.sessions.items()
    }



