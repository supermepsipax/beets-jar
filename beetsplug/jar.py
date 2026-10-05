"""Beets plugin for web interace and RESTful API"""

import os
import sys

import uvicorn
from beets import ui
from beets.importer import Action
from beets.plugins import BeetsPlugin

try:
    from beets.events import EventType  # beets >= 2.14
except ImportError:
    from beets.plugins import EventType

TASK_PHASES: dict[EventType, int] = {
    "import_task_created": 0,  # TaskPhase.QUEUED
    "import_task_start": 1,  # TaskPhase.LOOKUP
    "import_task_before_choice": 2,  # TaskPhase.CHOOSING
    "import_task_choice": 3,  # TaskPhase.CHOSEN
    "import_task_apply": 4,  # TaskPhase.APPLYING
    "import_task_files": 5,  # TaskPhase.FILES
}


def _run_detached(host, port, debug, forwarded_allow_ips):
    """Forks server into a background process, probably only works on Linux/Mac"""
    pid = os.fork()
    if pid > 0:
        print(f"Jar server started in background (PID {pid})")
        print(f"Listending on http://{host}:{port}")
        return
    os.setsid()
    sys.stdin.close()
    from beets_jar.main import create_app

    app = create_app()
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="debug" if debug else "info",
        forwarded_allow_ips=forwarded_allow_ips,
        timeout_graceful_shutdown=5,
    )


def _generate_key():
    """Print a new API key and the config line holding its hash. The key is not stored anywhere."""
    from beets_jar.security import generate_api_key, hash_api_key

    key = generate_api_key()
    print("API key (shown once, give this to the external service):\n")
    print(f"    {key}\n")
    print("Add this to the jar: section of config.yaml, then restart the server:\n")
    print(f"    api_key_hash: {hash_api_key(key)}")


class JarPlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self.config.add(
            {
                "host": "127.0.0.1",
                "port": 7734,
                "import_paths": {},
                "plugins": [],
                "api_key_hash": "",
                "base_url": "",
                # Proxies trusted to set X-Forwarded-Proto/For (comma-separated IPs or CIDRs)
                "forwarded_allow_ips": "127.0.0.1",
                "editor": {
                    "keymap": "default",
                },
            }
        )
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
        from beets_jar.imports.events import (
            TaskFinished,
            TaskOutcome,
            TaskPhase,
            TaskSeen,
        )
        from beets_jar.imports.snapshot import summarize_task, task_key
        from beets_jar.services.event_bus import import_event_bus

        phase = TaskPhase(phase)
        task_id = task_key(task)
        import_event_bus.emit(
            TaskSeen(session_id, task_id, phase, summarize_task(task))
        )

        if phase is TaskPhase.CHOSEN:
            if task.skip:
                import_event_bus.emit(
                    TaskFinished(session_id, task_id, TaskOutcome.SKIPPED)
                )
            elif task.choice_flag in (Action.TRACKS, Action.ALBUMS):
                import_event_bus.emit(
                    TaskFinished(session_id, task_id, TaskOutcome.SPLIT)
                )
        elif phase is TaskPhase.FILES:
            import_event_bus.emit(
                TaskFinished(session_id, task_id, TaskOutcome.IMPORTED)
            )

    def commands(self):
        cmd = ui.Subcommand(
            "jar", help="start the Beets-Jar web interface (or: jar generate-key)"
        )
        cmd.parser.usage += "\n       beet jar generate-key"

        cmd.parser.add_option(
            "--host",
            default=None,
            help="server hostname (default: from config or 127.0.0.1)",
        )
        cmd.parser.add_option(
            "-p",
            "--port",
            type="int",
            default=None,
            help="server port (default: from config or 7734)",
        )
        cmd.parser.add_option(
            "-d",
            "--debug",
            action="store_true",
            default=False,
            help="enable debug/reload mode",
        )
        cmd.parser.add_option(
            "-D",
            "--detach",
            action="store_true",
            default=False,
            help="run the server as a background daemon",
        )
        cmd.parser.add_option(
            "--dev",
            action="store_true",
            default=False,
            help="enable hot reload on source changes",
        )

        def func(lib, opts, args):
            if args:
                if args == ["generate-key"]:
                    _generate_key()
                    return
                raise ui.UserError(f"unknown jar command: {' '.join(args)}")
            host = opts.host or self.config["host"].as_str()
            port = opts.port or self.config["port"].get(int)
            forwarded_allow_ips = self.config["forwarded_allow_ips"].as_str()

            if opts.detach:
                _run_detached(host, port, opts.debug, forwarded_allow_ips)

            elif opts.dev:
                reload_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                uvicorn.run(
                    "beets_jar.main:app",
                    host=host,
                    port=port,
                    reload=True,
                    reload_dirs=[reload_dir],
                    log_level="debug" if opts.debug else "info",
                    forwarded_allow_ips=forwarded_allow_ips,
                    timeout_graceful_shutdown=5,
                )

            else:
                from beets_jar.main import create_app

                app = create_app(lib=lib)
                uvicorn.run(
                    app,
                    host=host,
                    port=port,
                    log_level="debug" if opts.debug else "info",
                    forwarded_allow_ips=forwarded_allow_ips,
                    timeout_graceful_shutdown=5,
                )

        cmd.func = func
        return [cmd]
