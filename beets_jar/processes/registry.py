import asyncio

from beets_jar.models.process_events import (
    ProcessFinished,
    ProcessQueued,
    ProcessStarted,
    TargetFinished,
)
from beets_jar.models.processes import ProcessState, ProcessStatus


class ProcessRegistry:
    """In-memory view of queued/running/finished plugin processes.

    Display state only: the ProcessRunner owns the real queue.
    """

    def __init__(self, max_finished: int = 50):
        self.processes: dict[str, ProcessState] = {}
        self.version = 0
        self.max_finished = max_finished
        self._waiters: set[asyncio.Event] = set()
        self._closing = False

    # ---- reducer ----
    def apply(self, event):
        if isinstance(event, ProcessQueued):
            # A restart reuses the id: start fresh and move the row to the end
            self.processes.pop(event.process_id, None)
            self.processes[event.process_id] = ProcessState(event.process_id, event.spec)
        else:
            state = self.processes.get(event.process_id)
            if state is None:
                return  # late event for a dismissed/trimmed process
            match event:
                case ProcessStarted():
                    state.status = ProcessStatus.RUNNING
                case TargetFinished(ok=ok, detail=detail):
                    state.done += 1
                    if not ok:
                        state.failed += 1
                        state.last_error = detail
                case ProcessFinished(status=status, error=error):
                    state.status, state.error = status, error
                    self._trim()
        self._notify()

    # ---- commands ----
    def dismiss(self, process_id: str) -> bool:
        state = self.processes.get(process_id)
        if state is None or not state.finished:
            return False
        del self.processes[process_id]
        self._notify()
        return True

    def _trim(self):
        finished = [pid for pid, s in self.processes.items() if s.finished]
        for pid in finished[: max(0, len(finished) - self.max_finished)]:
            del self.processes[pid]

    # ---- SSE plumbing (same as ImportRegistry) ----
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
