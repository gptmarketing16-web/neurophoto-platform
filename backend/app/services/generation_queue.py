from __future__ import annotations

import asyncio

from ..settings import settings
from .canvas_generations import run_canvas_generation
from .task_manager import task_manager


def run_generation_job(generation_id: str) -> None:
    asyncio.run(run_canvas_generation(generation_id))


def enqueue_generation(generation_id: str) -> None:
    if settings.queue_mode == "redis" and settings.redis_url:
        from redis import Redis
        from rq import Queue

        connection = Redis.from_url(settings.redis_url)
        queue = Queue("generations", connection=connection, default_timeout=1800)
        queue.enqueue(
            "app.services.generation_queue.run_generation_job",
            generation_id,
            job_id=f"generation-{generation_id}",
            result_ttl=3600,
            failure_ttl=86400,
        )
        return
    task_manager.create(run_canvas_generation(generation_id))
