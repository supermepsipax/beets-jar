"""JSON shapes for the external import API."""

from __future__ import annotations

from app.imports import views
from app.imports.registry import (
    SessionState,
    TaskState,
    open_prompt,
    open_session_prompt,
)


def task_payload(session: SessionState, task: TaskState) -> dict:
    return {
        "task_id": task.task_id,
        "name": views.task_name(session, task),
        "items": task.summary.item_count,
        "phase": task.phase.name.lower(),  # queued | lookup | choosing | chosen | applying | files | done
        "outcome": task.outcome.value if task.outcome else None,
        "needs_input": open_prompt(task) is not None,
    }


def session_payload(session: SessionState, base_url: str) -> dict:
    tasks = [task_payload(session, t) for t in session.tasks.values()]
    return {
        "session_id": session.session_id,
        "status": session.status.value,  # running | needs_input | completed | aborted | failed
        "needs_input": open_session_prompt(session) is not None
        or any(t["needs_input"] for t in tasks),
        "paths": session.paths,
        "error": session.error,
        "version": session.version,
        "review_url": review_url(session.session_id, base_url),
        "tasks": tasks,
    }


def review_url(session_id: str, base_url: str) -> str:
    return f"{base_url.rstrip('/')}/import?session={session_id}"
