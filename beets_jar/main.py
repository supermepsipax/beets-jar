import asyncio
import contextlib
import signal
from contextlib import asynccontextmanager

from beets import config as beets_config
from beets import plugins as beets_plugins
from beets.library import Library
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from beets_jar.imports.registry import ImportRegistry
from beets_jar.processes.registry import ProcessRegistry
from beets_jar.processes.runner import ProcessRunner
from beets_jar.routers.configuration import router as configuration_router
from beets_jar.routers.external_api import router as external_api_router
from beets_jar.routers.imports import router as imports_router
from beets_jar.routers.library import router as library_router
from beets_jar.routers.plugins import router as plugins_router
from beets_jar.services.event_bus import import_event_bus, process_event_bus
from beets_jar.templating import STATIC_DIR


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
        loop = asyncio.get_running_loop()

        imports = ImportRegistry()
        import_event_bus.bind(loop)
        import_consumer = asyncio.create_task(import_event_bus.consume(imports.apply))
        app.state.imports = imports

        processes = ProcessRegistry()
        process_event_bus.bind(loop)
        process_consumer = asyncio.create_task(process_event_bus.consume(processes.apply))
        runner = ProcessRunner(app.state.lib)
        runner.start()
        app.state.processes = processes
        app.state.runner = runner

        def close_streams():
            imports.close()
            processes.close()

        # Uvicorn waits for open connections before running lifespan shutdown, so the
        # SSE stream never ends and the server hangs. Hook uvicorn's signal handlers
        # (installed before startup) so streams are closed as soon as shutdown begins.
        previous_handlers = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous = signal.getsignal(sig)
            if not callable(previous):
                continue
            previous_handlers[sig] = previous

            def handler(signum, frame, previous=previous):
                loop.call_soon_threadsafe(close_streams)
                previous(signum, frame)

            signal.signal(sig, handler)

        yield

        runner.stop()  # a command already running finishes in its daemon thread
        for bus, consumer in ((import_event_bus, import_consumer), (process_event_bus, process_consumer)):
            bus.unbind()
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
    app.include_router(imports_router)
    app.include_router(configuration_router)
    app.include_router(plugins_router)
    app.include_router(external_api_router)
    return app


app = create_app()
