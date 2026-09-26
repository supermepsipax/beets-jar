from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from queue import Queue
from typing import Any, Literal

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


FINISHED = {SessionStatus.COMPLETED, SessionStatus.ABORTED, SessionStatus.FAILED}

@dataclass(frozen=True)
class TaskSummary:
    paths: tuple[str, ...]
    item_count: int
    is_album: bool
    artist: str | None = None
    album: str | None = None
    raw_paths: tuple[bytes, ...] = ()


@dataclass
class Prompt:
    prompt_id: str
    kind: Literal["candidate", "duplicate", "resume"]
    reply: Queue = field(default_factory=Queue)
    task: Any = None                 # live ImportTask; safe to read while the prompt is open
    choices: list = field(default_factory=list)
    duplicate_summary: dict | None = None
    path: str | None = None
    answered: bool = False


# ---- events ----
@dataclass(frozen=True)
class SessionStarted:
    session_id: str
    paths: tuple[str, ...]

@dataclass(frozen=True)
class TaskSeen:
    session_id: str
    task_id: str
    phase: TaskPhase
    summary: TaskSummary

@dataclass(frozen=True)
class TaskFinished:
    session_id: str
    task_id: str
    outcome: TaskOutcome
    detail: str | None = None

@dataclass(frozen=True)
class PromptOpened:
    session_id: str
    task_id: str | None
    prompt: Prompt

@dataclass(frozen=True)
class PromptClosed:
    session_id: str
    prompt_id: str

@dataclass(frozen=True)
class SessionFinished:
    session_id: str
    status: SessionStatus
    error: str | None = None

