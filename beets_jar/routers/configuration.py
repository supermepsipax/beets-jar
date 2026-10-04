import logging
from pathlib import Path

import yaml
from beets import config as beets_config
from confuse import ConfigError
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from beets_jar import TEMPLATES_DIR
from beets_jar.services import get_config_text

logger = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["configuration"])
templates = Jinja2Templates(TEMPLATES_DIR)

KEYMAPS = ["default", "vim"]

def _yaml_problem(text: str) -> dict | None:
    try:
        yaml.safe_load(text)

    except yaml.MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        return {
            "line": mark.line + 1 if mark else 1,
            "col": mark.column + 1 if mark else 1,
            "message": e.problem or str(e),
        }
    except yaml.YAMLError as e:
        return {"line": 1, "col": 1, "message": str(e)}

    return None

def _editor_keymap() -> str:
    try:
        return beets_config["jar"]["editor"]["keymap"].as_choice(KEYMAPS)
    except ConfigError:
        logger.warning("jar.editor.keymap must be one of %s; using default", KEYMAPS)
        return "default"


@router.get("/configuration", response_class=HTMLResponse)
async def configuration_page(
    request: Request,
):
    """Confiuration page."""

    yaml_text = get_config_text()

    if yaml_text is not None:
        update_text = ""

    else:
        yaml_text = ""
        update_text = "Unable to parse config.yaml"

    response = templates.TemplateResponse(
        request,
        "configuration.html",
        {
            "yaml_text": yaml_text,
            "update_text": update_text,
            "keymap": _editor_keymap(),
        },
    )
    return response


@router.post("/configuration", response_class=HTMLResponse)
async def update_configuration(request: Request, yaml_text: str = Form(...)):

    problem = _yaml_problem(yaml_text)
    if problem:
        return templates.TemplateResponse(
            request,
            "partials/config_status.html",
            {"error": f"Line {problem['line']}: {problem['message']}"},
        )

    config_path = Path(beets_config.config_dir(), "config.yaml")
    config_path.write_text(yaml_text)
    beets_config.set(yaml.safe_load(yaml_text))

    response = templates.TemplateResponse(
        request,
        "partials/config_status.html",
        {"saved": True},
    )
    return response

@router.post("/api/config/lint")
async def lint_configuration(yaml_text: str = Form(...)) -> list[dict]:
    problem = _yaml_problem(yaml_text)
    return [problem] if problem else []
