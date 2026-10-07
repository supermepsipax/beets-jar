"""Import state: what the registry tracks per session/task, and what a prompt carries."""

from __future__ import annotations
from beets.dbcore import Query

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from queue import Queue
from typing import Any, Literal, Sequence

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
    duplicate_summary: dict | None = None  # duplicate prompts only
    resume_path: str | None = None  # resume prompts only
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

    @property
    def open_prompt(self) -> Prompt | None:
        """The task's prompt while it still waits for an answer."""
        if self.prompt is None or self.prompt.answered:
            return None
        return self.prompt


@dataclass
class SessionState:
    session_id: str
    status: SessionStatus = SessionStatus.RUNNING
    tasks: dict[str, TaskState] = field(default_factory=dict)
    query: str | Sequence[str] | Query | None = None
    paths: list[str] | None = None
    prompt: Prompt | None = None  # resume prompt
    version: int = 0
    error: str | None = None

    @property
    def open_prompt(self) -> Prompt | None:
        """The session's own (resume) prompt while it still waits for an answer."""
        if self.prompt is None or self.prompt.answered:
            return None
        return self.prompt

    def prompts(self) -> list[Prompt]:
        """Every prompt in the session, answered or not."""
        task_prompts = [task.prompt for task in self.tasks.values()]
        return [prompt for prompt in (self.prompt, *task_prompts) if prompt]

    def open_prompts(self) -> Iterator[tuple[str | None, Prompt]]:
        """(task_id, prompt) for each unanswered prompt, oldest first.
        The resume prompt comes first, with task_id None."""
        if self.open_prompt:
            yield None, self.open_prompt
        for task in self.tasks.values():
            if task.open_prompt:
                yield task.task_id, task.open_prompt
