import logging
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["library"])
templates = Jinja2Templates("app/templates")

@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
):
    return RedirectResponse(url="/library", status_code=302)

@router.get("/library", response_class=HTMLResponse)
async def search_page(
    request: Request,
    # db: AsyncSession = Depends(get_db),
):
    """Main library page."""

    response = templates.TemplateResponse(
        request,
        "library.html",
        {
        },
    )
    return response

