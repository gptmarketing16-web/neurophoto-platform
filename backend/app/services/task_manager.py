import asyncio
from collections.abc import Coroutine
from typing import Any


class TaskManager:
    def __init__(self) -> None:
        self.tasks: set[asyncio.Task[Any]] = set()

    def create(self, coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task


task_manager = TaskManager()
