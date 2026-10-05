"""What the Processes panel renders (built in processes/presenters.py)."""

from dataclasses import dataclass, field


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
