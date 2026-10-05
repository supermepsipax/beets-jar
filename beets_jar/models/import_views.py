"""What the import page's templates render (built in imports/views.py)."""

from __future__ import annotations

from dataclasses import dataclass, field

from beets_jar.models.imports import SessionState, TaskState


@dataclass(frozen=True)
class Tag:
    text: str
    tone: str  # maps to the .tag-<tone> CSS classes


@dataclass
class PanelGroup:
    session: SessionState
    name: str
    tasks: list[TaskState] = field(default_factory=list)
    resume: bool = False  # session-level prompt is open
    scanning: bool = False  # running, but nothing to show yet
    dismissable: bool = False
    empty_note: str | None = None


@dataclass(frozen=True)
class TrackRow:
    number: str
    title: str
    old_title: str | None = None


@dataclass(frozen=True)
class CandidateView:
    index: int
    pct: int
    title: str
    artist: str
    year: str
    meta: str  # "2018 · CD · CA" / "Album · 2018"
    tracks: list[TrackRow]
    notes: str  # "2 tracks missing · 1 extra file"
