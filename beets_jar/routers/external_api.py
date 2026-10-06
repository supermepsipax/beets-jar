import logging

from beets import config
from beets.library import Library
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from beets_jar.dependencies import get_import_registry, get_lib
from beets_jar.imports import presenters
from beets_jar.imports.registry import ImportRegistry
from beets_jar.imports.session import start_web_import, validate_import_path
from beets_jar.models.api import StartImport
from beets_jar.models.imports import SessionState, TaskState
from beets_jar.security import is_valid_hash, verify_api_key

log = logging.getLogger(__name__)


def require_api_key(request: Request) -> None:
    stored = config["jar"]["api_key_hash"].as_str().strip().lower()
    if not stored:
        raise HTTPException(404)  # API disabled: behave as if it doesn't exist
    if not is_valid_hash(stored):
        # most likely a raw key pasted in by mistake; fail closed instead of matching it
        log.warning("jar.api_key_hash is not a SHA-256 hex digest; run `beet jar generate-key`")
        raise HTTPException(404)
    supplied = _supplied_api_key(request)
    if not supplied or not verify_api_key(supplied, stored):
        raise HTTPException(401, "Invalid API key")


def _supplied_api_key(request: Request) -> str:
    """The key from the X-API-Key header, or else from `Authorization: Bearer <key>`."""
    key = request.headers.get("x-api-key", "")
    if key:
        return key
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[len("bearer "):]
    return ""


router = APIRouter(prefix="/api/v1", tags=["api"], dependencies=[Depends(require_api_key)])


def _base_url(request: Request) -> str:
    """Where clients reach this server, without a trailing slash."""
    return (config["jar"]["base_url"].as_str() or str(request.base_url)).rstrip("/")


def _review_url(base_url: str, session_id: str) -> str:
    return f"{base_url}/import?session={session_id}"


@router.post("/imports", status_code=201)
async def start_import_session(
    body: StartImport,
    request: Request,
    lib: Library = Depends(get_lib),
    import_registry: ImportRegistry = Depends(get_import_registry),
):
    path = validate_import_path(body.path)
    if path is None:
        raise HTTPException(400, "Path does not exist on the server")
    session = start_web_import(lib, import_registry, [path], seed_id=(body.seed_id or ""))
    base_url = _base_url(request)
    return {
        "session_id": session.session_id,
        "status_url": f"{base_url}/api/v1/imports/{session.session_id}",
        "review_url": _review_url(base_url, session.session_id),
    }


@router.get("/imports")
async def list_sessions(request: Request, import_registry: ImportRegistry = Depends(get_import_registry)):
    base_url = _base_url(request)
    return [session_payload(session, base_url) for session in import_registry.sessions.values()]


@router.get("/imports/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    response: Response,
    import_registry: ImportRegistry = Depends(get_import_registry),
):
    session = import_registry.sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown or dismissed session")
    etag = f'"{session.version}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return session_payload(session, _base_url(request))


@router.delete("/imports/{session_id}", status_code=204)
async def dismiss_import_session(session_id: str, import_registry: ImportRegistry = Depends(get_import_registry)):
    if session_id not in import_registry.sessions:
        raise HTTPException(404)
    if not import_registry.dismiss(session_id):
        raise HTTPException(409, "Session is still running")


# ---------------------------------------------------------------- JSON shapes
# These keys are the public API: add to them, don't rename them.


def session_payload(session: SessionState, base_url: str) -> dict:
    tasks = [_task_payload(session, task) for task in session.tasks.values()]
    needs_input = session.open_prompt is not None or any(task["needs_input"] for task in tasks)
    return {
        "session_id": session.session_id,
        "status": session.status.value,  # running | needs_input | completed | aborted | failed
        "needs_input": needs_input,
        "paths": session.paths,
        "error": session.error,
        "version": session.version,
        "review_url": _review_url(base_url, session.session_id),
        "tasks": tasks,
    }


def _task_payload(session: SessionState, task: TaskState) -> dict:
    return {
        "task_id": task.task_id,
        "name": presenters.task_name(session, task),
        "items": task.summary.item_count,
        "phase": task.phase.name.lower(),  # queued | lookup | choosing | chosen | applying | files | done
        "outcome": task.outcome.value if task.outcome else None,
        "needs_input": task.open_prompt is not None,
    }
