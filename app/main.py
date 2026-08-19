from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from beets import config as beets_config
from beets.library import Library
from app.routers import (
    library_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    beets_config.read()
    lib = Library(
        path=beets_config["library"].as_filename(),
        directory=beets_config["directory"].as_filename(),
    )
    app.state.lib = lib
    yield


app = FastAPI(lifespan=lifespan)

app.include_router(library_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
