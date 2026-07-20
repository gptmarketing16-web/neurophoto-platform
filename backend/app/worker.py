from redis import Redis
from rq import Queue, Worker

from .settings import settings


def main() -> None:
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required for the worker")
    connection = Redis.from_url(settings.redis_url)
    worker = Worker([Queue("generations", connection=connection)], connection=connection)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
