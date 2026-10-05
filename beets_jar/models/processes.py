"""Plugin process state: what to run, and how far it got."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProcessStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED_PROCESS_STATUSES = {
    ProcessStatus.COMPLETED,
    ProcessStatus.FAILED,
    ProcessStatus.CANCELLED,
}


@dataclass(frozen=True)
class ProcessSpec:
    """Everything needed to run (or re-run) one plugin command over the selected rows."""

    plugin: str
    command: str
    queries: tuple[str, ...]  # one beets query per progress step (see processes/specs.py)
    album: bool | None = None  # opts.album, for target=flag commands
    overrides: dict[str, Any] = field(default_factory=dict)  # dest -> value, incl. manifest `fixed`
    subtitle: str = ""  # the library query the rows came from, for the panel

    @property
    def name(self) -> str:
        return self.plugin if self.command == self.plugin else f"{self.plugin} · {self.command}"


@dataclass
class ProcessState:
    process_id: str
    spec: ProcessSpec
    status: ProcessStatus = ProcessStatus.QUEUED
    done: int = 0
    failed: int = 0
    error: str | None = None  # why the whole process failed
    last_error: str | None = None  # most recent single-row failure

    @property
    def total(self) -> int:
        return len(self.spec.queries)

    @property
    def finished(self) -> bool:
        return self.status in FINISHED_PROCESS_STATUSES
