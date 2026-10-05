"""The one Jinja environment every router renders with, plus the app's asset paths."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from beets_jar.imports import views
from beets_jar.imports.registry import open_prompt

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

templates = Jinja2Templates(TEMPLATES_DIR)
templates.env.filters["short_path"] = views.short_path
templates.env.globals.update(
    session_name=views.session_name,
    task_name=views.task_name,
    task_label=views.task_label,
    outcome_tag=views.outcome_tag,
    can_restart=views.can_restart,
    choice_label=views.choice_label,
    open_prompt=open_prompt,
)
