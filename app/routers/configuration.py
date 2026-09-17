import logging
import os
import yaml
from pathlib import Path
from beets import config as beets_config
from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app import TEMPLATES_DIR
from app.services import get_config_text

logger = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["configuration"])
templates = Jinja2Templates(TEMPLATES_DIR)

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

    logger.info(yaml_text)
    response = templates.TemplateResponse(
        request,
        "configuration.html",
        {
            "yaml_text": yaml_text,
            "update_text": update_text,
        },
    )
    return response

@router.post("/configuration", response_class=HTMLResponse)
async def update_configuration(
    request: Request,
    yaml_text: str = Form(...)
):

    try:
        yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        response = templates.TemplateResponse(
            request,
            "partials/yaml_edit.html",
            {
                "yaml_text": yaml_text,
                "update_text": "Unable to parse config.yaml"
            },
        )
        return response

    # config_path = Path(os.environ["BEETSDIR"], "config.yaml")
    config_path = Path(beets_config.config_dir(), "config.yaml")
    with open(config_path,"w") as f:
        f.write(yaml_text)

    beets_config.set(yaml.safe_load(yaml_text))

    response = templates.TemplateResponse(
        request,
        "partials/yaml_edit.html",
        {
            "yaml_text": yaml_text,
            "update_text": "Changes Saved"
        },
    )
    return response
