"""Request bodies for the external /api/v1 routes."""

from pydantic import BaseModel


class StartImport(BaseModel):
    path: str
    seed_id: str | None = None
