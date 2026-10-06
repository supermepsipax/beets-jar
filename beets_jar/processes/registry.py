from beets_jar.models.process_events import (
    ProcessFinished,
    ProcessQueued,
    ProcessStarted,
    TargetFinished,
)
from beets_jar.models.processes import ProcessState, ProcessStatus
from beets_jar.services.streaming import ChangeNotifier


class ProcessRegistry(ChangeNotifier):
    """In-memory view of queued/running/finished plugin processes.

    Display state only: the ProcessRunner owns the real queue.
    """

    def __init__(self, max_finished: int = 50):
        super().__init__()
        self.processes: dict[str, ProcessState] = {}
        self.max_finished = max_finished

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
                    state.status = status
                    state.error = error
                    self._trim()
        self.notify()

    # ---- commands ----
    def dismiss(self, process_id: str) -> bool:
        state = self.processes.get(process_id)
        if state is None or not state.finished:
            return False
        del self.processes[process_id]
        self.notify()
        return True

    def _trim(self):
        """Keep at most max_finished finished processes, dropping the oldest."""
        finished_ids = [pid for pid, state in self.processes.items() if state.finished]
        for process_id in finished_ids[: max(0, len(finished_ids) - self.max_finished)]:
            del self.processes[process_id]
