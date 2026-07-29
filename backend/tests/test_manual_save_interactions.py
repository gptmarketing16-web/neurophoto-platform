from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
STATIC = APP / "static"


def test_interaction_router_and_policy_are_loaded_last():
    main = (APP / "main.py").read_text(encoding="utf-8")
    assert "from .api.interaction import router as interaction_router" in main
    assert "app.include_router(interaction_router)" in main
    assert "interaction-policy.js?v=7.13" in main
    assert main.index("performance-actions.js?v=7.12") < main.index("interaction-policy.js?v=7.13")


def test_workspace_navigation_does_not_mark_project_dirty():
    script = (STATIC / "interaction-policy.js").read_text(encoding="utf-8")
    marker = "scheduleViewportSave = function scheduleViewportLocally()"
    start = script.index(marker)
    end = script.index("};", start)
    implementation = script[start:end]
    assert "persistLocalView()" in implementation
    assert "mergeDirtyProject" not in implementation


def test_upload_does_not_autosave_other_edits():
    script = (STATIC / "interaction-policy.js").read_text(encoding="utf-8")
    start = script.index("uploadNodeImage = async function uploadNodeImageManualSave")
    end = script.index("async function createPhotoFromPaste", start)
    implementation = script[start:end]
    assert "saveAllChanges" not in implementation
    assert "/api/canvas/nodes/${node.id}/${endpointKind}" in implementation


def test_blocks_and_clipboard_photo_use_fast_endpoints():
    script = (STATIC / "interaction-policy.js").read_text(encoding="utf-8")
    api = (APP / "api" / "interaction.py").read_text(encoding="utf-8")
    assert "/nodes/fast-create" in script
    assert "/nodes/fast-photo" in script
    assert '@router.post("/api/projects/{project_id}/nodes/fast-create"' in api
    assert '@router.post("/api/projects/{project_id}/nodes/fast-photo"' in api
    assert "select(func.count(ProjectNode.id))" in api


def test_russian_layout_tool_shortcuts_are_supported():
    script = (STATIC / "interaction-policy.js").read_text(encoding="utf-8")
    assert "key === 'м'" in script
    assert "key === 'р'" in script
    assert "setToolMode('select')" in script
    assert "setToolMode('hand')" in script
