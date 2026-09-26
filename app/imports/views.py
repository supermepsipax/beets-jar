from __future__ import annotations

import os
from dataclasses import dataclass, field

from beets.autotag import AlbumMatch

from app.imports.events import FINISHED, SessionStatus, TaskOutcome, TaskPhase
from app.imports.registry import (
    ImportRegistry,
    SessionState,
    TaskState,
    open_prompt,
    open_session_prompt,
)

RESTARTABLE = {TaskOutcome.SKIPPED, TaskOutcome.ABORTED, TaskOutcome.FAILED}

# (text, tone): tone maps to the .tag-<tone> CSS classes
OUTCOME_TAGS = {
    TaskOutcome.IMPORTED: ("Imported", "success"),
    TaskOutcome.SKIPPED: ("Skipped", "muted"),
    TaskOutcome.SPLIT: ("Split", "muted"),
    TaskOutcome.MERGED: ("Merged", "muted"),
    TaskOutcome.ABORTED: ("Stopped", "danger"),
    TaskOutcome.FAILED: ("Failed", "danger"),
}

# Friendlier names for beets' built-in prompt choices; plugin choices keep their own
CHOICE_LABELS = {
    "s": "Skip",
    "u": "Use as-is",
    "t": "As tracks",
    "g": "Group albums",
    "b": "Abort",
}


# ---------- names ----------

def short_path(path: str, max_len: int = 32) -> str:
    """/very/long/path/Art of Doubt -> /very/…/Art of Doubt"""
    if len(path) <= max_len:
        return path
    parts = path.rstrip(os.sep).split(os.sep)
    if len(parts) > 2:
        shortened = os.sep.join(parts[:2]) + f"{os.sep}…{os.sep}" + parts[-1]
        if len(shortened) <= max_len:
            return shortened
    return "…" + path[-(max_len - 1):]


def session_name(session: SessionState) -> str:
    if not session.paths:
        return "Import"
    extra = f" +{len(session.paths) - 1}" if len(session.paths) > 1 else ""
    return short_path(session.paths[0]) + extra


def task_name(session: SessionState, task: TaskState) -> str:
    """Folder name relative to the session root, e.g. "CD1" or "Album/CD1"."""
    paths = task.summary.paths
    if not paths:
        return "Untitled"
    path = paths[0].rstrip(os.sep)
    name = os.path.basename(path)
    if session.paths:
        root = session.paths[0].rstrip(os.sep)
        if path != root and path.startswith(root + os.sep):
            name = os.path.relpath(path, root)
    return name + (f" +{len(paths) - 1}" if len(paths) > 1 else "")


# ---------- labels ----------

def task_label(task: TaskState) -> str:
    if open_prompt(task):
        return "Choose →"
    if task.phase <= TaskPhase.QUEUED:
        return "Queued"
    if task.phase <= TaskPhase.CHOOSING:
        return "Lookup"
    return "Importing"  # CHOSEN / APPLYING / FILES


@dataclass(frozen=True)
class Tag:
    text: str
    tone: str


def outcome_tag(task: TaskState) -> Tag:
    if task.restarted:
        return Tag("Restarted", "muted")
    text, tone = OUTCOME_TAGS.get(task.outcome, ("Done", "muted"))
    return Tag(text, tone)


def can_restart(task: TaskState) -> bool:
    return task.outcome in RESTARTABLE and not task.restarted and bool(task.summary.raw_paths)


def choice_label(choice) -> str:
    return CHOICE_LABELS.get(choice.short, choice.long)


# ---------- panels ----------

@dataclass
class PanelGroup:
    session: SessionState
    name: str
    tasks: list[TaskState] = field(default_factory=list)
    resume: bool = False          # session-level prompt is open
    scanning: bool = False        # running, but nothing to show yet
    dismissable: bool = False
    empty_note: str | None = None


def in_progress(registry: ImportRegistry) -> list[PanelGroup]:
    """Running sessions, oldest first, with only their unfinished tasks."""
    groups = []
    for session in registry.sessions.values():
        if session.status in FINISHED:
            continue
        tasks = [t for t in session.tasks.values() if t.outcome is None]
        resume = open_session_prompt(session) is not None
        groups.append(PanelGroup(
            session=session,
            name=session_name(session),
            tasks=tasks,
            resume=resume,
            scanning=not tasks and not resume,
        ))
    return groups


def finished(registry: ImportRegistry) -> list[PanelGroup]:
    """Sessions with finished tasks, newest first. A running session can be in both panels."""
    groups = []
    for session in reversed(list(registry.sessions.values())):
        done = [t for t in session.tasks.values() if t.outcome is not None]
        is_finished = session.status in FINISHED
        empty_note = None
        if is_finished and not session.tasks:
            empty_note = {
                SessionStatus.FAILED: "Couldn't import",
                SessionStatus.ABORTED: "Stopped",
            }.get(session.status, "Nothing to import")
        if done or empty_note:
            groups.append(PanelGroup(
                session=session,
                name=session_name(session),
                tasks=done,
                dismissable=is_finished,
                empty_note=empty_note,
            ))
    return groups


# ---------- candidates ----------

@dataclass(frozen=True)
class TrackRow:
    number: str
    title: str
    old_title: str | None = None


@dataclass(frozen=True)
class CandidateView:
    index: int
    pct: int
    title: str
    artist: str
    year: str
    meta: str           # "2018 · CD · CA" / "Album · 2018"
    tracks: list[TrackRow]
    notes: str          # "2 tracks missing · 1 extra file"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def candidate_view(match, index: int) -> CandidateView:
    info = match.info
    year = str(info.get("year") or "")
    pct = max(0, round((1 - match.distance.distance) * 100))
    tracks: list[TrackRow] = []
    notes = ""

    if isinstance(match, AlbumMatch):
        meta = " · ".join(str(v) for v in (year, info.get("media"), info.get("country")) if v)
        pairs = sorted(
            match.item_info_pairs,
            key=lambda pair: (pair[1].get("medium") or 0, pair[1].get("index") or 0),
        )
        for item, track in pairs:
            new_title = track.get("title") or ""
            old_title = item.title or ""
            number = track.get("medium_index") or track.get("index") or ""
            tracks.append(TrackRow(
                number=str(number),
                title=new_title,
                old_title=old_title if old_title and old_title != new_title else None,
            ))
        bits = []
        if match.extra_tracks:
            bits.append(_plural(len(match.extra_tracks), "track") + " missing")
        if match.extra_items:
            bits.append(_plural(len(match.extra_items), "extra file"))
        notes = " · ".join(bits)
    else:
        meta = " · ".join(v for v in (info.get("album"), year) if v)

    return CandidateView(
        index=index,
        pct=pct,
        title=info.name or "",
        artist=info.get("artist") or "",
        year=year,
        meta=meta,
        tracks=tracks,
        notes=notes,
    )
