"""Display rules for the Processes panel."""
from dataclasses import dataclass, field

from app.processes.events import ProcessStatus
from app.processes.registry import ProcessRegistry, ProcessState

# (text, tone): tone maps to the .tag-<tone> CSS classes
STATUS_TAGS = {
    ProcessStatus.QUEUED: ("Queued", "muted"),
    ProcessStatus.RUNNING: ("In progress", "active"),
    ProcessStatus.COMPLETED: ("Done", "success"),
    ProcessStatus.FAILED: ("Failed", "danger"),
    ProcessStatus.CANCELLED: ("Stopped", "muted"),
}


@dataclass(frozen=True)
class ProcessRow:
    process_id: str
    subtitle: str
    done: int
    total: int
    pct: int
    tag: str
    tone: str
    error: str | None
    can_cancel: bool
    finished: bool


@dataclass
class ProcessGroup:
    name: str
    rows: list[ProcessRow] = field(default_factory=list)


def process_row(state: ProcessState) -> ProcessRow:
    tag, tone = STATUS_TAGS[state.status]
    if state.status is ProcessStatus.COMPLETED and state.failed:
        tag, tone = f"{state.failed} failed", "danger"
    total = state.total
    return ProcessRow(
        process_id=state.process_id,
        subtitle=state.spec.subtitle or f"{total} selected",
        done=state.done,
        total=total,
        pct=round(state.done * 100 / total) if total else 100,
        tag=tag,
        tone=tone,
        error=state.error or state.last_error,
        can_cancel=state.status in (ProcessStatus.QUEUED, ProcessStatus.RUNNING),
        finished=state.finished,
    )


def panel_groups(registry: ProcessRegistry) -> list[ProcessGroup]:
    """Processes grouped under their plugin (or "plugin · command"), in first-seen order."""
    groups: dict[str, ProcessGroup] = {}
    for state in registry.processes.values():
        name = state.spec.name
        groups.setdefault(name, ProcessGroup(name)).rows.append(process_row(state))
    return list(groups.values())
