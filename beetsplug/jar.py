"""Beets plugin for web interace and RESTful API"""
from beets.util import displayable_path
from beets.importer import Action

import os
import sys
import uvicorn
from beets import ui
from beets.plugins import BeetsPlugin, EventType

TASK_PHASES: dict[EventType, int] = {
    "import_task_created": 0,        # TaskPhase.QUEUED
    "import_task_start": 1,          # TaskPhase.LOOKUP
    "import_task_before_choice": 2,  # TaskPhase.CHOOSING
    "import_task_choice": 3,         # TaskPhase.CHOSEN
    "import_task_apply": 4,          # TaskPhase.APPLYING
    "import_task_files": 5,          # TaskPhase.FILES
}

def _run_detached(host, port, debug):
    """Forks server into a background process, probably only works on Linux/Mac"""
    pid = os.fork()
    if pid > 0:
        print(f"Jar server started in background (PID {pid})")
        print(f"Listending on http://{host}:{port}")
        return
    os.setsid()
    sys.stdin.close()
    from app.main import create_app
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="debug" if debug else "info",
                timeout_graceful_shutdown=5)


class JarPlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self.config.add({
            "host": "127.0.0.1",
            "port": 7734,
        })
        for event_name, phase in TASK_PHASES.items():
            self.register_listener(event_name, self._make_handler(phase))

    def _make_handler(self, phase: int):
        def handler(session=None, task=None, **kwargs):
            try:
                self._on_task_event(phase, session, task)
            except Exception:
                self._log.exception("jar: failed to report import event")

        return handler
    def _on_task_event(self, phase, session, task):
        session_id = getattr(session, "session_id", None)
        if session_id is None or task is None:
            return
        from app.imports import event_bus
        from app.imports.events import TaskFinished, TaskOutcome, TaskPhase, TaskSeen
        from app.imports.snapshot import summarize_task, task_key

        phase = TaskPhase(phase)
        task_id = task_key(task)
        event_bus.emit(TaskSeen(session_id, task_id, phase, summarize_task(task)))

        if phase is TaskPhase.CHOSEN:
            if task.skip:
                event_bus.emit(TaskFinished(session_id, task_id, TaskOutcome.SKIPPED))
            elif task.choice_flag in (Action.TRACKS, Action.ALBUMS):
                event_bus.emit(TaskFinished(session_id, task_id, TaskOutcome.SPLIT))
        elif phase is TaskPhase.FILES:
            event_bus.emit(TaskFinished(session_id, task_id, TaskOutcome.IMPORTED))

    def commands(self):
        cmd = ui.Subcommand("jar", help="start the Beets-Jar web interface")
        cmd.parser.add_option(
            "--host", default=None,
            help="server hostname (default: from config or 127.0.0.1)"
        )
        cmd.parser.add_option(
            "-p", "--port", type="int", default=None,
            help="server port (default: from config or 7734)"
        )
        cmd.parser.add_option(
            "-d", "--debug", action="store_true", default=False,
            help="enable debug/reload mode"
        )
        cmd.parser.add_option(
            "-D", "--detach", action="store_true", default=False,
            help="run the server as a background daemon"
        )
        cmd.parser.add_option(
            "--dev", action="store_true", default=False,
            help="enable hot reload on source changes"
        )
        def func(lib, opts, args):
            host = opts.host or self.config["host"].as_str()
            port = opts.port or self.config["port"].get(int)

            if opts.detach:
                _run_detached(host, port, opts.debug)

            elif opts.dev:
                reload_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                uvicorn.run(
                    "app.main:app",
                    host=host,
                    port=port,
                    reload=True,
                    reload_dirs=[reload_dir],
                    log_level="debug" if opts.debug else "info",
                    timeout_graceful_shutdown=5,
                )

            else:
                from app.main import create_app
                app = create_app(lib=lib)
                uvicorn.run(
                    app, host=host, port=port,
                    log_level="debug" if opts.debug else "info",
                    timeout_graceful_shutdown=5,
                )
        cmd.func = func
        return [cmd]
