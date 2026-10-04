from beets.library import Library
from fastapi import Request

from beets_jar.imports import ImportRegistry
from beets_jar.processes import ProcessRegistry, ProcessRunner


def get_lib(request: Request) -> Library:
    return request.app.state.lib


def get_imports(request: Request) -> ImportRegistry:
    return request.app.state.imports


def get_processes(request: Request) -> ProcessRegistry:
    return request.app.state.processes


def get_runner(request: Request) -> ProcessRunner:
    return request.app.state.runner
