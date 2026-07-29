from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_s3_upload_does_not_block_async_event_loop():
    source = (ROOT / "backend" / "app" / "services" / "storage.py").read_text(encoding="utf-8")
    assert "UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024" in source
    assert "await asyncio.to_thread(" in source
    assert "max_pool_connections=16" in source


def test_render_can_use_a_separate_generation_worker():
    source = (ROOT / "render_start.py").read_text(encoding="utf-8")
    assert 'env_flag("RUN_EMBEDDED_WORKER", True)' in source
    assert 'positive_int_env("WEB_CONCURRENCY", 1)' in source
    assert '"--workers"' in source
    assert '"app.worker"' in source
