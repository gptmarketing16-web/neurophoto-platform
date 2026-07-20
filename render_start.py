"""Run the web API and the RQ worker in one Render web service.

Render's free plan does not provide a free background-worker service, so this
small supervisor keeps both processes in one container. Browser polling during
a generation keeps the free web service awake until the job completes.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

processes: list[subprocess.Popen] = []
stopping = False


def stop_all(signum: int | None = None, _frame=None) -> None:
    global stopping
    if stopping:
        return
    stopping = True
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 10
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
    if signum is not None:
        raise SystemExit(0)


def main() -> int:
    signal.signal(signal.SIGTERM, stop_all)
    signal.signal(signal.SIGINT, stop_all)

    port = os.environ.get("PORT", "10000")
    worker = subprocess.Popen([sys.executable, "-m", "app.worker"])
    web = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
            "--proxy-headers",
            "--forwarded-allow-ips=*",
        ]
    )
    processes.extend([worker, web])

    try:
        while True:
            worker_code = worker.poll()
            web_code = web.poll()
            if worker_code is not None:
                print(f"Generation worker stopped with code {worker_code}", flush=True)
                stop_all()
                return worker_code or 1
            if web_code is not None:
                print(f"Web service stopped with code {web_code}", flush=True)
                stop_all()
                return web_code or 1
            time.sleep(1)
    finally:
        stop_all()


if __name__ == "__main__":
    raise SystemExit(main())
