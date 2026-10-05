"""Import state: what the registry tracks per session/task, and what a prompt carries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from queue import Queue
from typing import Any, Literal

from beets.autotag import AlbumMatch, TrackMatch
from beets.util import PromptChoice, displayable_path


class TaskPhase(IntEnum):
    QUEUED = 0
    LOOKUP = 1
    CHOOSING = 2
    CHOSEN = 3
    APPLYING = 4
    FILES = 5
    DONE = 6


class TaskOutcome(str, Enum):
    IMPORTED = "imported"
    SKIPPED = "skipped"
    SPLIT = "split"
    MERGED = "merged"
    ABORTED = "aborted"
    FAILED = "failed"


class SessionStatus(str, Enum):
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


FINISHED_SESSION_STATUSES = {
    SessionStatus.COMPLETED,
    SessionStatus.ABORTED,
    SessionStatus.FAILED,
}


class ChoiceType(str, Enum):
    """Short letters of beets' built-in candidate prompt choices."""

    SKIP = "s"
    ASIS = "u"
    AS_TRACKS = "t"
    GROUP_ALBUMS = "g"
    SEARCH = "e"
    ID = "i"
    ABORT = "b"


@dataclass(frozen=True)
class TaskSummary:
    paths: tuple[str, ...]
    item_count: int
    is_album: bool
    artist: str | None = None
    album: str | None = None
    raw_paths: tuple[bytes, ...] = ()

    @classmethod
    def from_task(cls, task) -> TaskSummary:
        """Snapshot of a live beets ImportTask, safe to keep after the task moves on."""
        items = task.items or []
        raw_paths = tuple(task.paths or [])
        return cls(
            paths=tuple(displayable_path(path) for path in raw_paths),
            item_count=len(items),
            is_album=task.is_album,
            artist=getattr(task, "cur_artist", None),
            album=getattr(task, "cur_album", None),
            raw_paths=raw_paths,
        )


@dataclass
class Prompt:
    prompt_id: str
    kind: Literal["candidate", "duplicate", "resume"]
    reply: Queue = field(default_factory=Queue)
    task: Any = None  # live ImportTask; safe to read while the prompt is open
    choices: list = field(default_factory=list)
    duplicate_summary: dict | None = None
    path: str | None = None
    answered: bool = False


@dataclass
class WebChoice:
    """A prompt reply from the browser: a candidate match or a prompt choice,
    plus whatever the choice needs (search terms, an MBID)."""

    choice: AlbumMatch | TrackMatch | PromptChoice
    follow_up_info: dict[str, str] = field(default_factory=dict)


@dataclass
class TaskState:
    task_id: str
    summary: TaskSummary
    phase: TaskPhase = TaskPhase.QUEUED
    outcome: TaskOutcome | None = None
    detail: str | None = None
    prompt: Prompt | None = None
    restarted: bool = False


@dataclass
class SessionState:
    session_id: str
    paths: list[str] = field(default_factory=list)
    status: SessionStatus = SessionStatus.RUNNING
    tasks: dict[str, TaskState] = field(default_factory=dict)
    prompt: Prompt | None = None  # resume prompt
    version: int = 0
    error: str | None = None

    def prompts(self):
        return [p for p in (self.prompt, *(t.prompt for t in self.tasks.values())) if p]
