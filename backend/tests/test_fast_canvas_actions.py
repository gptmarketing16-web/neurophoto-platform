from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
STATIC = APP / "static"


def test_fast_performance_router_is_registered():
    main = (APP / "main.py").read_text(encoding="utf-8")
    assert "from .api.performance import router as performance_router" in main
    assert "app.include_router(performance_router)" in main


def test_fast_actions_script_is_loaded_last():
    main = (APP / "main.py").read_text(encoding="utf-8")
    assert "performance-actions.js?v=7.12" in main
    assert main.index("performance-hotfix.js?v=7.11") < main.index("performance-actions.js?v=7.12")
    assert (STATIC / "performance-actions.js").is_file()


def test_fast_endpoints_avoid_full_project_reload_and_waiting_for_s3_delete():
    source = (APP / "api" / "performance.py").read_text(encoding="utf-8")
    assert '"/api/projects/{project_id}/fast-save"' in source
    assert '"/api/projects/{project_id}/nodes/bulk-delete"' in source
    assert '"/api/canvas/nodes/{node_id}/fast-photo"' in source
    assert '"/api/canvas/nodes/{node_id}/fast-reference"' in source
    assert "background_tasks.add_task(storage.delete_keys" in source
    assert "select(ProjectNode).where" in source
    assert "selectinload(ProjectNode.generations)" not in source


def test_frontend_uses_one_bulk_delete_request_and_fast_prompt_save():
    script = (STATIC / "performance-actions.js").read_text(encoding="utf-8")
    assert "deleteSelectedObjectsFast" in script
    assert "/nodes/bulk-delete" in script
    assert "fastSavePromptEditor" in script
    assert "oldSaveButton.replaceWith(saveButton)" in script
    assert "fetchProjectPreservingLocalChanges" not in script
    assert "refreshProjectsQuietly" not in script


def test_existing_image_optimizer_is_reused_for_customer_photos_and_references():
    hotfix = (STATIC / "performance-hotfix.js").read_text(encoding="utf-8")
    actions = (STATIC / "performance-actions.js").read_text(encoding="utf-8")
    assert "prepareImageForUpload(file)" in hotfix
    assert "uploadNodeImageOptimized" in hotfix
    assert "fast-photo" in actions
    assert "fast-reference" in actions
