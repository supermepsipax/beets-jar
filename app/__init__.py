from app.dependencies import get_lib, get_queues
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

__all__ = [
    "get_lib",
    "get_queues",
]
