from beets.library import Library
from fastapi import Request
from app.imports import ImportRegistry

def get_lib(request: Request) -> Library:
    return request.app.state.lib

def get_imports(request: Request) -> ImportRegistry:
    return request.app.state.imports
