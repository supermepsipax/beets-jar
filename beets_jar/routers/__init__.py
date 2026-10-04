from beets_jar.routers.configuration import router as configuration_router
from beets_jar.routers.importer import router as import_router
from beets_jar.routers.library import router as library_router
from beets_jar.routers.plugins import router as plugins_router
from beets_jar.routers.external_api import router as external_api_router

__all__ = [
    "configuration_router",
    "import_router",
    "library_router",
    "plugins_router",
    "external_api_router",
]
