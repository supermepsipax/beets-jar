from beets.library import Library
from fastapi import Request

from beets_jar.imports.registry import ImportRegistry
from beets_jar.processes.registry import ProcessRegistry
from beets_jar.processes.runner import ProcessRunner


def get_lib(request: Request) -> Library:
    return request.app.state.lib


def get_import_registry(request: Request) -> ImportRegistry:
    return request.app.state.import_registry


def get_process_registry(request: Request) -> ProcessRegistry:
    return request.app.state.process_registry


def get_runner(request: Request) -> ProcessRunner:
    return request.app.state.runner
