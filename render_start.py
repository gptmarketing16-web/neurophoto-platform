"""Run the NeuroPhoto web API and, optionally, an embedded RQ worker.

The embedded worker remains enabled by default for compatibility with the current
single-service Render deployment. Set RUN_EMBEDDED_WORKER=false on the Web Service
when a separate Render Background Worker runs ``python -m app.worker``.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

processes: list[subprocess.Popen] = []
stopping = False


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


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
    run_embedded_worker = env_flag("RUN_EMBEDDED_WORKER", True)
    web_concurrency = positive_int_env("WEB_CONCURRENCY", 1)

    worker: subprocess.Popen | None = None
    if run_embedded_worker:
        worker = subprocess.Popen([sys.executable, "-m", "app.worker"])
        processes.append(worker)
        print("Embedded generation worker enabled", flush=True)
    else:
        print("Embedded generation worker disabled; expecting a separate worker service", flush=True)

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
            "--workers",
            str(web_concurrency),
            "--proxy-headers",
            "--forwarded-allow-ips=*",
        ]
    )
    processes.append(web)

    try:
        while True:
            if worker is not None:
                worker_code = worker.poll()
                if worker_code is not None:
                    print(f"Generation worker stopped with code {worker_code}", flush=True)
                    stop_all()
                    return worker_code or 1
            web_code = web.poll()
            if web_code is not None:
                print(f"Web service stopped with code {web_code}", flush=True)
                stop_all()
                return web_code or 1
            time.sleep(1)
    finally:
        stop_all()


if __name__ == "__main__":
    raise SystemExit(main())
