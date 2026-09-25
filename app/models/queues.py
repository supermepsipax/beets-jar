import enum
import asyncio
import uuid
import threading
from beets.util import PromptChoice
from beets.importer import ImportTask
from queue import Queue


class QueueStorageType(str, enum.Enum):
    CANDIDATE = "candidate"
    DUPLICATE = "duplicate"
    RESUME = "resume"


class QueueStorageItem:
    def __init__(
        self,
        task: ImportTask | None = None,
        choices: list[PromptChoice] | None = None,
        queue_type: QueueStorageType = QueueStorageType.CANDIDATE,
        duplicate_summary: dict[str, list[str] | str] | None = None,
        path: str | None = None
    ):
        self.queue = Queue()
        self.task = task
        self.choices = choices
        self.queue_type = queue_type
        if queue_type == QueueStorageType.DUPLICATE and duplicate_summary is not None:
            self.duplicate_summary = duplicate_summary
        if queue_type == QueueStorageType.RESUME and path is not None:
            self.path = path


class QueueStorage:
    """Designed to be in memory storage only"""

    def __init__(self):
        self.queues: dict[str, QueueStorageItem] = {}
        self._lock = threading.Lock()
        self._version = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._waiters: list[asyncio.Event] = []
        self._closing = False

    def bind_loop(self, loop: asyncio.AbstractEventLoop):
        """Called at startup from the async context"""
        self._loop = loop

    def _notify(self):
        """Increments version and wakes SSE clients when the storage is updated"""
        self._version += 1
        if self._loop:
            for event in self._waiters:
                self._loop.call_soon_threadsafe(event.set)

    def close(self):
        """Wakes all SSE clients and tells them to stop streaming, called on server shutdown"""
        self._closing = True
        for event in self._waiters:
            event.set()

    @property
    def closing(self) -> bool:
        return self._closing

    def store(self, queue: QueueStorageItem) -> str:
        queue_id = uuid.uuid4().hex
        # TODO: remove print
        # print(f"storing new queue item {queue_id}")
        with self._lock:
            self.queues[queue_id] = queue
        self._notify()
        return queue_id

    def get(self, queue_id: str) -> QueueStorageItem | None:
        with self._lock:
            return self.queues.get(queue_id)

    def update(
        self,
        queue_id: str,
        task: ImportTask | None = None,
        choices: list[PromptChoice] | None = None,
        duplicate_summary: dict[str, list[str] | str] | None = None,
        path: str | None = None
    ):
        # TODO: remove print
        # print(f"updating queue {queue_id}")
        with self._lock:
            queue_item = self.queues.get(queue_id)
            if queue_item:
                if task is not None:
                    # TODO: remove print
                    # print(f"task {task}")
                    queue_item.task = task
                if choices is not None:
                    # TODO: remove print
                    # print(f"choices {choices}")
                    queue_item.choices = choices
                if duplicate_summary is not None:
                    # TODO: remove print
                    # print(f"duplicate_summary {duplicate_summary}")
                    queue_item.duplicate_summary = duplicate_summary
                if path is not None:
                    # TODO: remove print
                    # print(f"path {path}")
                    queue_item.path = path
        self._notify()

    def delete(self, queue_id: str):
        with self._lock:
            self.queues.pop(queue_id, None)
        self._notify()

    def items(self):
        with self._lock:
            return list(self.queues.items())

    @property
    def version(self) -> int:
        return self._version

    async def wait_for_change(self, since_version: int) -> int:
        """Allows multiple SSE clients to wait for a change"""
        if self._version > since_version or self._closing:
            return self._version

        event = asyncio.Event()
        self._waiters.append(event)
        try:
            await event.wait()
        finally:
            self._waiters.remove(event)
        return self._version
