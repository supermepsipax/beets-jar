"""Events the import pipeline thread (and the beets plugin) send to the ImportRegistry."""

from __future__ import annotations

from dataclasses import dataclass

from beets_jar.models.imports import (
    Prompt,
    SessionStatus,
    TaskOutcome,
    TaskPhase,
    TaskSummary,
)


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
