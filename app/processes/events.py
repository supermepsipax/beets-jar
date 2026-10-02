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


FINISHED = {ProcessStatus.COMPLETED, ProcessStatus.FAILED, ProcessStatus.CANCELLED}


@dataclass(frozen=True)
class ProcessSpec:
    """Everything needed to run (or re-run) one plugin command over the selected rows."""

    plugin: str
    command: str
    queries: tuple[str, ...]  # one beets query per progress step (see targets.py)
    album: bool | None = None  # opts.album, for target=flag commands
    overrides: dict[str, Any] = field(default_factory=dict)  # dest -> value, incl. manifest `fixed`
    subtitle: str = ""  # the library query the rows came from, for the panel

    @property
    def name(self) -> str:
        return self.plugin if self.command == self.plugin else f"{self.plugin} · {self.command}"


# ---- events ----
@dataclass(frozen=True)
class ProcessQueued:
    process_id: str
    spec: ProcessSpec


@dataclass(frozen=True)
class ProcessStarted:
    process_id: str


@dataclass(frozen=True)
class TargetFinished:
    process_id: str
    ok: bool
    detail: str | None = None


@dataclass(frozen=True)
class ProcessFinished:
    process_id: str
    status: ProcessStatus
    error: str | None = None
