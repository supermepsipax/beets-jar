"""The one Jinja environment every router renders with, plus the app's asset paths."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from beets_jar.imports import presenters

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

templates = Jinja2Templates(TEMPLATES_DIR)
templates.env.filters["short_path"] = presenters.short_path
templates.env.globals.update(
    session_name=presenters.session_name,
    task_name=presenters.task_name,
    task_label=presenters.task_label,
    outcome_tag=presenters.outcome_tag,
    can_restart=presenters.can_restart,
    choice_label=presenters.choice_label,
)
