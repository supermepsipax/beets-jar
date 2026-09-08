from app.models import QueueStorage
from beets.library import Library
from fastapi import Request

def get_lib(request: Request) -> Library:
    return request.app.state.lib

def get_queues(request: Request) -> QueueStorage:
    return request.app.state.queues
