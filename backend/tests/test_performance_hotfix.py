from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_performance_hotfix_is_loaded_after_canvas_extensions():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "performance-hotfix.js?v=7.11" in main
    assert main.index("prompt-editor-guards.js?v=7.8") < main.index("performance-hotfix.js?v=7.11")
    assert (STATIC / "performance-hotfix.js").is_file()


def test_upload_updates_canvas_locally_without_project_reload():
    script = (STATIC / "performance-hotfix.js").read_text(encoding="utf-8")
    assert "uploadNodeImageOptimized" in script
    assert "node.assets.push(asset)" in script
    assert "renderCanvas()" in script
    assert "reloadCurrentProject" not in script


def test_large_images_are_optimized_before_upload():
    script = (STATIC / "performance-hotfix.js").read_text(encoding="utf-8")
    assert "MAX_UPLOAD_DIMENSION = 3072" in script
    assert "MAX_UPLOAD_BYTES_WITHOUT_OPTIMIZATION = 5 * 1024 * 1024" in script
    assert "prepareImageForUpload" in script
    assert "canvasToBlob(canvas, 'image/jpeg', JPEG_QUALITY)" in script
    assert "form.append('file', uploadFile" in script


def test_save_does_not_refetch_project_list():
    script = (STATIC / "performance-hotfix.js").read_text(encoding="utf-8")
    assert "saveAllChangesOptimized" in script
    assert "syncCurrentProjectSummary()" in script
    assert "refreshProjectsQuietly" not in script


def test_canvas_images_use_lazy_async_decoding():
    script = (STATIC / "performance-hotfix.js").read_text(encoding="utf-8")
    assert "image.loading = 'lazy'" in script
    assert "image.decoding = 'async'" in script
    assert "MutationObserver" in script
