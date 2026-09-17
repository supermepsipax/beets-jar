"""Beets plugin for web interace and RESTful API"""

import os
import sys
import uvicorn
from beets import ui
from beets.plugins import BeetsPlugin

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
    uvicorn.run(app, host=host, port=port, log_level="debug" if debug else "info")


class JarPlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self.config.add({
            "host": "127.0.0.1",
            "port": 7734,
        })

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
                )

            else:
                from app.main import create_app
                app = create_app(lib=lib)
                uvicorn.run(app, host=host, port=port, log_level="debug" if opts.debug else "info")
        cmd.func = func
        return [cmd]
