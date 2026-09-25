import asyncio
from dataclasses import dataclass, field
from app.imports.events import (
    FINISHED, Prompt, PromptClosed, PromptOpened, SessionFinished, SessionStarted,
    SessionStatus, TaskFinished, TaskOutcome, TaskPhase, TaskSeen, TaskSummary,
)


@dataclass
class TaskState:
    task_id: str
    summary: TaskSummary
    phase: TaskPhase = TaskPhase.QUEUED
    outcome: TaskOutcome | None = None
    detail: str | None = None
    prompt: Prompt | None = None


@dataclass
class SessionState:
    session_id: str
    paths: list[str] = field(default_factory=list)
    status: SessionStatus = SessionStatus.RUNNING
    tasks: dict[str, TaskState] = field(default_factory=dict)
    prompt: Prompt | None = None       # resume prompt
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
    """Only ever touched from the event loop, so no lock is needed."""

    def __init__(self, max_finished: int = 50):
        self.sessions: dict[str, SessionState] = {}
        self.version = 0
        self.max_finished = max_finished
        self._waiters: set[asyncio.Event] = set()
        self._closing = False

    # ---- reducer ----
    def apply(self, event):
        session_state = self.sessions.setdefault(event.session_id, SessionState(event.session_id))

        match event:
            case SessionStarted(paths=paths):
                session_state.paths = list(paths)

            case TaskSeen(task_id=tid, phase=phase, summary=summary):
                task_state = session_state.tasks.get(tid)
                if task_state is None:
                    session_state.tasks[tid] = TaskState(tid, summary, phase)
                else:
                    task_state.summary = summary
                    task_state.phase = max(task_state.phase, phase)  # never move backwards

            case TaskFinished(task_id=tid, outcome=outcome, detail=detail):
                if task_state := session_state.tasks.get(tid):
                    task_state.outcome, task_state.detail, task_state.phase = outcome, detail, TaskPhase.DONE

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
                if session_state.status is SessionStatus.NEEDS_INPUT and not session_state.prompts():
                    session_state.status = SessionStatus.RUNNING

            case SessionFinished(status=status, error=error):
                session_state.status, session_state.error, session_state.prompt = status, error, None
                for task_state in session_state.tasks.values():
                    task_state.prompt = None
                    if task_state.outcome is None:
                        task_state.outcome, task_state.phase = SWEEP[status], TaskPhase.DONE
                self._trim()

        session_state.version += 1
        self._notify()

    # ---- queries / commands ----
    def find_prompt(self, session_id: str, prompt_id: str) -> Prompt | None:
        session_state = self.sessions.get(session_id)
        if session_state is None:
            return None
        return next((p for p in session_state.prompts() if p.prompt_id == prompt_id), None)

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
