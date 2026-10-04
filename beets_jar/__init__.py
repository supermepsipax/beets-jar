from pathlib import Path

from beets_jar.dependencies import get_imports, get_lib, get_processes, get_runner

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

__all__ = [
    "get_lib",
    "get_imports",
    "get_processes",
    "get_runner",
]
