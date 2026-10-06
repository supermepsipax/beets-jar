"""Display rules for the Processes panel."""

from beets_jar.models.process_views import ProcessGroup, ProcessRow
from beets_jar.models.processes import ProcessState, ProcessStatus
from beets_jar.processes.registry import ProcessRegistry

# (text, tone): tone maps to the .tag-<tone> CSS classes
STATUS_TAGS = {
    ProcessStatus.QUEUED: ("Queued", "muted"),
    ProcessStatus.RUNNING: ("In progress", "active"),
    ProcessStatus.COMPLETED: ("Done", "success"),
    ProcessStatus.FAILED: ("Failed", "danger"),
    ProcessStatus.CANCELLED: ("Stopped", "muted"),
}


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
        name = state.spec.display_name
        groups.setdefault(name, ProcessGroup(name)).rows.append(process_row(state))
    return list(groups.values())
