import logging
import os

from beets import config
from beets.library import Library
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from beets_jar import get_imports, get_lib
from beets_jar.imports import ImportRegistry
from beets_jar.imports.external_api import review_url, session_payload
from beets_jar.security import is_valid_hash, verify_api_key
from beets_jar.services import start_web_import

log = logging.getLogger(__name__)


def require_api_key(request: Request) -> None:
    stored = config["jar"]["api_key_hash"].as_str().strip().lower()
    if not stored:
        raise HTTPException(404)  # API disabled: behave as if it doesn't exist
    if not is_valid_hash(stored):
        # most likely a raw key pasted in by mistake; fail closed instead of matching it
        log.warning("jar.api_key_hash is not a SHA-256 hex digest; run `beet jar generate-key`")
        raise HTTPException(404)
    supplied = request.headers.get("x-api-key", "")
    auth = request.headers.get("authorization", "")
    if not supplied and auth.lower().startswith("bearer "):
        supplied = auth[7:]
    if not supplied or not verify_api_key(supplied, stored):
        raise HTTPException(401, "Invalid API key")


router = APIRouter(prefix="/api/v1", tags=["api"], dependencies=[Depends(require_api_key)])


def _base_url(request: Request) -> str:
    return config["jar"]["base_url"].as_str() or str(request.base_url)


class StartImport(BaseModel):
    path: str
    seed_id: str | None = None


@router.post("/imports", status_code=201)
async def start(
    body: StartImport,
    request: Request,
    lib: Library = Depends(get_lib),
    imports: ImportRegistry = Depends(get_imports),
):
    path = body.path.strip()
    if not path or not os.path.exists(path):
        raise HTTPException(400, "Path does not exist on the server")
    session = start_web_import(lib, imports, [path], seed_id=(body.seed_id or ""))
    base = _base_url(request)
    return {
        "session_id": session.session_id,
        "status_url": f"{base.rstrip('/')}/api/v1/imports/{session.session_id}",
        "review_url": review_url(session.session_id, base),
    }


@router.get("/imports")
async def list_sessions(request: Request, imports: ImportRegistry = Depends(get_imports)):
    base = _base_url(request)
    return [session_payload(s, base) for s in imports.sessions.values()]


@router.get("/imports/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    response: Response,
    imports: ImportRegistry = Depends(get_imports),
):
    session = imports.sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown or dismissed session")
    etag = f'"{session.version}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return session_payload(session, _base_url(request))


@router.delete("/imports/{session_id}", status_code=204)
async def dismiss(session_id: str, imports: ImportRegistry = Depends(get_imports)):
    if session_id not in imports.sessions:
        raise HTTPException(404)
    if not imports.dismiss(session_id):
        raise HTTPException(409, "Session is still running")
