import asyncio
import signal
import contextlib
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from beets import config as beets_config
from beets import plugins as beets_plugins
from beets.library import Library
from app import STATIC_DIR
from app.routers import library_router, import_router, configuration_router
from app.imports import event_bus, ImportRegistry


def create_app(lib: Library | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if lib is not None:
            app.state.lib = lib
            owns_lib = False
        else:
            beets_config.read()
            beets_plugins.load_plugins()
            app.state.lib = Library(
                path=beets_config["library"].as_filename(),
                directory=beets_config["directory"].as_filename(),
            )
            owns_lib = True

        imports = ImportRegistry()
        event_bus.bind(asyncio.get_running_loop())
        consumer = asyncio.create_task(event_bus.consume(imports.apply))
        app.state.imports = imports

        # Uvicorn waits for open connections before running lifespan shutdown, so the
        # SSE stream never ends and the server hangs. Hook uvicorn's signal handlers
        # (installed before startup) so streams are closed as soon as shutdown begins.
        loop = asyncio.get_running_loop()
        previous_handlers = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous = signal.getsignal(sig)
            if not callable(previous):
                continue
            previous_handlers[sig] = previous

            def handler(signum, frame, previous=previous):
                loop.call_soon_threadsafe(imports.close)
                previous(signum, frame)

            signal.signal(sig, handler)

        yield

        event_bus.unbind()
        consumer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer
        for sig, previous in previous_handlers.items():
            signal.signal(sig, previous)
        if owns_lib:
            app.state.lib._close()

    app = FastAPI(lifespan=lifespan)

    app.mount(
        "/static",
        StaticFiles(directory=STATIC_DIR),
        name="static",
    )

    app.include_router(library_router)
    app.include_router(import_router)
    app.include_router(configuration_router)
    return app


app = create_app()

# @app.get("/api/health")
# def health():
#     return {"status": "ok"}
