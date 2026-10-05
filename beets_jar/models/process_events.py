"""Events the ProcessRunner's worker thread sends to the ProcessRegistry."""

from __future__ import annotations

from dataclasses import dataclass

from beets_jar.models.processes import ProcessSpec, ProcessStatus


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
