import asyncio
from dataclasses import dataclass, field

from app.imports.events import (
    FINISHED,
    Prompt,
    PromptClosed,
    PromptOpened,
    SessionFinished,
    SessionStarted,
    SessionStatus,
    TaskFinished,
    TaskOutcome,
    TaskPhase,
    TaskSeen,
    TaskSummary,
)


def open_prompt(task_state: TaskState | None) -> Prompt | None:
    if task_state is None or task_state.prompt is None or task_state.prompt.answered:
        return None
    return task_state.prompt


def open_session_prompt(session_state: SessionState) -> Prompt | None:
    prompt = session_state.prompt
    return prompt if prompt and not prompt.answered else None


@dataclass
class TaskState:
    task_id: str
    summary: TaskSummary
    phase: TaskPhase = TaskPhase.QUEUED
    outcome: TaskOutcome | None = None
    detail: str | None = None
    prompt: Prompt | None = None
    restarted: bool = False


@dataclass
class SessionState:
    session_id: str
    paths: list[str] = field(default_factory=list)
    status: SessionStatus = SessionStatus.RUNNING
    tasks: dict[str, TaskState] = field(default_factory=dict)
    prompt: Prompt | None = None  # resume prompt
    version: int = 0
    error: str | None = None

    def prompts(self):
        return [p for p in (self.prompt, *(t.prompt for t in self.tasks.values())) if p]


SWEEP = {
    SessionStatus.COMPLETED: TaskOutcome.SKIPPED,
    SessionStatus.ABORTED: TaskOutcome.ABORTED,
    SessionStatus.FAILED: TaskOutcome.FAILED,
}


class ImportRegistry:
    def __init__(self, max_finished: int = 50):
        self.sessions: dict[str, SessionState] = {}
        self.version = 0
        self.max_finished = max_finished
        self._waiters: set[asyncio.Event] = set()
        self._closing = False

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
            case SessionStarted(paths=paths):
                session_state.paths = list(paths)

            case TaskSeen(task_id=tid, phase=phase, summary=summary):
                task_state = session_state.tasks.get(tid)
                if task_state is None:
                    session_state.tasks[tid] = TaskState(tid, summary, phase)
                else:
                    task_state.summary = summary
                    task_state.phase = max(
                        task_state.phase, phase
                    )  # never move backwards

            case TaskFinished(task_id=tid, outcome=outcome, detail=detail):
                if task_state := session_state.tasks.get(tid):
                    task_state.outcome, task_state.detail, task_state.phase = (
                        outcome,
                        detail,
                        TaskPhase.DONE,
                    )

            case PromptOpened(task_id=tid, prompt=prompt):
                if tid is None:
                    session_state.prompt = prompt
                elif task_state := session_state.tasks.get(tid):
                    task_state.prompt = prompt
                session_state.status = SessionStatus.NEEDS_INPUT

            case PromptClosed(prompt_id=pid):
                if session_state.prompt and session_state.prompt.prompt_id == pid:
                    session_state.prompt = None
                for task_state in session_state.tasks.values():
                    if task_state.prompt and task_state.prompt.prompt_id == pid:
                        task_state.prompt = None
                if (
                    session_state.status is SessionStatus.NEEDS_INPUT
                    and not session_state.prompts()
                ):
                    session_state.status = SessionStatus.RUNNING

            case SessionFinished(status=status, error=error):
                session_state.status, session_state.error, session_state.prompt = (
                    status,
                    error,
                    None,
                )
                for task_state in session_state.tasks.values():
                    task_state.prompt = None
                    if task_state.outcome is None:
                        task_state.outcome, task_state.phase = (
                            SWEEP[status],
                            TaskPhase.DONE,
                        )
                self._trim()

        session_state.version += 1
        self._notify()
    # ---- queries ----
    def get_task(self, session_id: str, task_id: str) -> TaskState | None:
        session_state = self.sessions.get(session_id)
        return session_state.tasks.get(task_id) if session_state else None

    def locate_prompt(self, session_id: str, prompt_id: str) -> tuple[str | None, Prompt] | None:
        """(task_id, prompt) for a prompt id; task_id is None for the resume prompt."""
        session_state = self.sessions.get(session_id)
        if session_state is None:
            return None
        if session_state.prompt and session_state.prompt.prompt_id == prompt_id:
            return None, session_state.prompt
        for task_state in session_state.tasks.values():
            if task_state.prompt and task_state.prompt.prompt_id == prompt_id:
                return task_state.task_id, task_state.prompt
        return None

    def next_needing_input(self) -> tuple[str, str | None] | None:
        """Oldest open prompt: session order, then task order."""
        for session_state in self.sessions.values():
            if open_session_prompt(session_state):
                return session_state.session_id, None
            for task_state in session_state.tasks.values():
                if open_prompt(task_state):
                    return session_state.session_id, task_state.task_id
        return None

    def pending_count(self) -> int:
        return sum(
            bool(open_session_prompt(s)) + sum(bool(open_prompt(t)) for t in s.tasks.values())
            for s in self.sessions.values()
        )

    # ---- commands ----
    def mark_restarted(self, session_id: str, task_id: str) -> None:
        if task_state := self.get_task(session_id, task_id):
            task_state.restarted = True
            self.sessions[session_id].version += 1
            self._notify()

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
            prompt = open_prompt(task_state)
            if (
                task_state is None
                or task_state.outcome is not None
                or (prompt and prompt.prompt_id != answered_prompt_id)
                or task_state.phase >= TaskPhase.APPLYING
            ):
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
        if session_state is None or session_state.status not in FINISHED:
            return False
        del self.sessions[session_id]
        self._notify()
        return True

    def _trim(self):
        finished = [sid for sid, s in self.sessions.items() if s.status in FINISHED]
        for sid in finished[: max(0, len(finished) - self.max_finished)]:
            del self.sessions[sid]

    # ---- SSE plumbing (ported from QueueStorage) ----
    def _notify(self):
        self.version += 1
        for waiter in self._waiters:
            waiter.set()

    @property
    def closing(self) -> bool:
        return self._closing

    def close(self):
        self._closing = True
        for waiter in self._waiters:
            waiter.set()

    async def wait_for_change(self, since_version: int) -> int:
        if self.version > since_version or self._closing:
            return self.version
        waiter = asyncio.Event()
        self._waiters.add(waiter)
        try:
            await waiter.wait()
        finally:
            self._waiters.discard(waiter)
        return self.version
