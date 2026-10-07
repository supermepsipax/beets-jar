from __future__ import annotations

import asyncio

from beets_jar.models.import_events import (
    PromptClosed,
    PromptOpened,
    SessionFinished,
    SessionStarted,
    TaskFinished,
    TaskSeen,
)
from beets_jar.models.imports import (
    FINISHED_SESSION_STATUSES,
    Prompt,
    SessionState,
    SessionStatus,
    TaskOutcome,
    TaskPhase,
    TaskState,
)
from beets_jar.services.streaming import ChangeNotifier

# When a session ends, tasks that never got an outcome of their own get this one
OUTCOME_FOR_UNFINISHED_TASKS = {
    SessionStatus.COMPLETED: TaskOutcome.SKIPPED,
    SessionStatus.ABORTED: TaskOutcome.ABORTED,
    SessionStatus.FAILED: TaskOutcome.FAILED,
}


class ImportRegistry(ChangeNotifier):
    """In memory register for all active/finished imports"""

    def __init__(self, max_finished: int = 50):
        super().__init__()
        self.sessions: dict[str, SessionState] = {}
        self.max_finished = max_finished

    # ---- reducer ----
    def apply(self, event):
        if isinstance(event, SessionStarted):
            session_state = self.sessions.setdefault(
                event.session_id, SessionState(event.session_id)
            )
        else:
            session_state = self.sessions.get(event.session_id)
            if session_state is None:
                return

        match event:
            case SessionStarted(paths=paths, query=query):
                if paths is not None:
                    session_state.paths = list(paths)
                if query is not None:
                    session_state.query = query

            case TaskSeen(task_id=task_id, phase=phase, summary=summary):
                task_state = session_state.tasks.get(task_id)
                if task_state is None:
                    session_state.tasks[task_id] = TaskState(task_id, summary, phase)
                else:
                    task_state.summary = summary
                    task_state.phase = max(task_state.phase, phase)  # never move backwards

            case TaskFinished(task_id=task_id, outcome=outcome, detail=detail):
                if task_state := session_state.tasks.get(task_id):
                    task_state.outcome = outcome
                    task_state.detail = detail
                    task_state.phase = TaskPhase.DONE

            case PromptOpened(task_id=task_id, prompt=prompt):
                if task_id is None:
                    session_state.prompt = prompt
                elif task_state := session_state.tasks.get(task_id):
                    task_state.prompt = prompt
                session_state.status = SessionStatus.NEEDS_INPUT

            case PromptClosed(prompt_id=prompt_id):
                if session_state.prompt and session_state.prompt.prompt_id == prompt_id:
                    session_state.prompt = None
                for task_state in session_state.tasks.values():
                    if task_state.prompt and task_state.prompt.prompt_id == prompt_id:
                        task_state.prompt = None
                if (
                    session_state.status is SessionStatus.NEEDS_INPUT
                    and not session_state.prompts()
                ):
                    session_state.status = SessionStatus.RUNNING

            case SessionFinished(status=status, error=error):
                session_state.status = status
                session_state.error = error
                session_state.prompt = None
                for task_state in session_state.tasks.values():
                    task_state.prompt = None
                    if task_state.outcome is None:
                        task_state.outcome = OUTCOME_FOR_UNFINISHED_TASKS[status]
                        task_state.phase = TaskPhase.DONE
                self._trim()

        session_state.version += 1
        self.notify()

    # ---- queries ----
    def get_task(self, session_id: str, task_id: str) -> TaskState | None:
        session_state = self.sessions.get(session_id)
        return session_state.tasks.get(task_id) if session_state else None

    def find_open_prompt(self, session_id: str, prompt_id: str) -> tuple[str | None, Prompt] | None:
        """(task_id, prompt) for an unanswered prompt; task_id is None for the resume prompt.
        None when the prompt is gone or already answered."""
        session_state = self.sessions.get(session_id)
        if session_state is None:
            return None
        for task_id, prompt in session_state.open_prompts():
            if prompt.prompt_id == prompt_id:
                return task_id, prompt
        return None

    def next_needing_input(self, prefer_session: str | None = None) -> tuple[str, str | None] | None:
        """Oldest open prompt (session order, then task order), trying `prefer_session` first."""
        sessions = list(self.sessions.values())
        if prefer_session in self.sessions:
            # stable sort: the preferred session moves to the front, the rest keep their order
            sessions.sort(key=lambda session_state: session_state.session_id != prefer_session)
        for session_state in sessions:
            for task_id, _prompt in session_state.open_prompts():
                return session_state.session_id, task_id
        return None

    def pending_count(self) -> int:
        """How many prompts are waiting on the user, across all sessions."""
        count = 0
        for session_state in self.sessions.values():
            count += sum(1 for _ in session_state.open_prompts())
        return count

    def finished_count(self) -> int:
        return len(self._finished_session_ids())

    # ---- commands ----
    def mark_restarted(self, session_id: str, task_id: str) -> None:
        if task_state := self.get_task(session_id, task_id):
            task_state.restarted = True
            self.sessions[session_id].version += 1
            self.notify()

    async def wait_for_followup(
        self, session_id: str, task_id: str, answered_prompt_id: str, timeout: float = 1.5
    ) -> None:
        """After a choice, wait briefly for the same task to either ask again
        (e.g. the duplicate question right after picking a candidate) or move on.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        since = self.version
        while True:
            task_state = self.get_task(session_id, task_id)
            if task_state is None or task_state.outcome is not None:
                return
            prompt = task_state.open_prompt
            asked_again = prompt is not None and prompt.prompt_id != answered_prompt_id
            if asked_again or task_state.phase >= TaskPhase.APPLYING:
                return
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            try:
                since = await asyncio.wait_for(self.wait_for_change(since), remaining)
            except TimeoutError:
                return

    def dismiss(self, session_id: str) -> bool:
        session_state = self.sessions.get(session_id)
        if session_state is None or session_state.status not in FINISHED_SESSION_STATUSES:
            return False
        del self.sessions[session_id]
        self.notify()
        return True

    def dismiss_finished(self) -> int:
        """Dismiss every finished session; running ones stay. Returns how many went."""
        finished_ids = self._finished_session_ids()
        for session_id in finished_ids:
            del self.sessions[session_id]
        if finished_ids:
            self.notify()
        return len(finished_ids)

    def _trim(self):
        """Keep at most max_finished finished sessions, dropping the oldest."""
        finished_ids = self._finished_session_ids()
        for session_id in finished_ids[: max(0, len(finished_ids) - self.max_finished)]:
            del self.sessions[session_id]

    def _finished_session_ids(self) -> list[str]:
        return [
            session_id
            for session_id, session_state in self.sessions.items()
            if session_state.status in FINISHED_SESSION_STATUSES
        ]
