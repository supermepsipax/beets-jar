import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from beets import config as beets_config
from beets.library import Library
from app.routers import (
    library_router, import_router,
)
from app.models import QueueStorage

@asynccontextmanager
async def lifespan(app: FastAPI):
    beets_config.read()
    lib = Library(
        path=beets_config["library"].as_filename(),
        directory=beets_config["directory"].as_filename(),
    )
    app.state.lib = lib
    queues = QueueStorage()
    queues.bind_loop(asyncio.get_running_loop())
    app.state.queues = queues
    yield
    print('closing db')
    lib._close()
    print('db closed')

app = FastAPI(lifespan=lifespan)

app.include_router(library_router)
app.include_router(import_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
