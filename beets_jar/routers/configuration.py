from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from beets_jar.services.configuration import (
    editor_keymap,
    parse_yaml,
    read_config_text,
    save_config,
)
from beets_jar.templating import templates

router = APIRouter(tags=["configuration"])


@router.get("/configuration", response_class=HTMLResponse)
async def configuration_page(
    request: Request,
):
    """Configuration page."""

    yaml_text = read_config_text()

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
            "keymap": editor_keymap(),
        },
    )
    return response


@router.post("/configuration", response_class=HTMLResponse)
async def update_configuration(request: Request, yaml_text: str = Form(...)):

    data, problem = parse_yaml(yaml_text)
    if problem:
        return templates.TemplateResponse(
            request,
            "configuration/status.html",
            {"error": f"Line {problem['line']}: {problem['message']}"},
        )

    save_config(yaml_text, data)

    response = templates.TemplateResponse(
        request,
        "configuration/status.html",
        {"saved": True},
    )
    return response

@router.post("/configuration/lint")
async def lint_configuration(yaml_text: str = Form(...)) -> list[dict]:
    _, problem = parse_yaml(yaml_text)
    return [problem] if problem else []
