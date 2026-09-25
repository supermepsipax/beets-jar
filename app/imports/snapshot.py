from rich.jupyter import display
from uuid import uuid4
from beets.util import displayable_path
from app.imports.events import TaskSummary

def task_key(task) -> str:
    task_id = getattr(task, "task_id", None)
    if task_id is None:
        task_id = task.task_id = uuid4().hex
    return task_id

def summarize_task(task) -> TaskSummary:
    items = task.itmes or []
    return TaskSummary(
        paths = tuple(displayable_path(path) for path in (task.paths or [])),
        item_count = len(items),
        is_album = task.is_album,
        artist = getattr(task, "cur_artist", None),
        album = getattr(task, "cur_album", None),
    )
