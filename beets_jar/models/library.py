"""Library search results."""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["album", "item"]


@dataclass(frozen=True)
class ResultRow:
    id: int
    title: str
    subtitle: str
    year: int | None
