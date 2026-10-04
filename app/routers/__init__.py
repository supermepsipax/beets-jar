from app.routers.configuration import router as configuration_router
from app.routers.importer import router as import_router
from app.routers.library import router as library_router
from app.routers.plugins import router as plugins_router
from app.routers.external_api import router as external_api_router

__all__ = [
    "configuration_router",
    "import_router",
    "library_router",
    "plugins_router",
    "external_api_router",
]
