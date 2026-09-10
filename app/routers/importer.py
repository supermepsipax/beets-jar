from app.models.queues import QueueStorageType
from app.models.web_choice import ChoiceType
from fastapi.sse import EventSourceResponse, ServerSentEvent
import asyncio
from beets.library import Library
import threading
from app.services import WebImportSession
from app import get_queues, get_lib
from app.models import QueueStorage, QueueStorageItem, WebChoice
import logging
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from beets import config as beets_config
from beets import plugins as beets_plugins


logger = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["importer"])
templates = Jinja2Templates("app/templates")


@router.get("/import", response_class=HTMLResponse)
async def search_page(
    request: Request,
    # db: AsyncSession = Depends(get_db),
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
        queues: QueueStorage = Depends(get_queues),
):
    last_version = -1
    while True:
        if await request.is_disconnected():
            break
        current_version = queues.version
        if current_version != last_version:
            last_version = current_version
            print("queue is updated")
            html = templates.get_template("queues/queue_list.html").render(
                request=request,
                queues=queues,
            )
            
            yield ServerSentEvent(raw_data=html)
        
        try:
            await asyncio.wait_for(
                    queues.wait_for_change(last_version),
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
    beets_config.read()
    beets_plugins.load_plugins()
    import_session = WebImportSession(
            lib = lib,
            paths = [path],
            queues = queues,
            loghandler = None,
            query = None,
            
    )
    import_thread = threading.Thread(target=import_session.run, daemon=True)
    import_thread.start()
    
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

    else:
        raise HTTPException(status_code=400, detail="Unknown type")

    queue_item.queue.put(web_choice)
    return HTMLResponse(
            f'<div id="import-{queue_id}"><p>Choice submited.</p></div>')




