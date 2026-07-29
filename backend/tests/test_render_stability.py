from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
STATIC = APP / "static"


def test_render_speed_router_and_final_script_are_loaded():
    main = (APP / "main.py").read_text(encoding="utf-8")
    assert "from .api.render_speed import router as render_speed_router" in main
    assert "app.include_router(render_speed_router)" in main
    assert "render-stability.js?v=7.14" in main
    assert main.index("interaction-policy.js?v=7.13") < main.index("render-stability.js?v=7.14")


def test_canvas_render_is_keyed_and_preserves_unchanged_images():
    script = (STATIC / "render-stability.js").read_text(encoding="utf-8")
    assert "renderCanvasIncrementally" in script
    assert "dataset.renderSignature" in script
    assert "current.replaceWith(buildNodeElement" in script
    assert "nodesLayer.innerHTML" not in script
    assert "renderCanvas();" in script


def test_canvas_images_use_direct_endpoint_with_proxy_fallback():
    script = (STATIC / "render-stability.js").read_text(encoding="utf-8")
    router = (APP / "api" / "render_speed.py").read_text(encoding="utf-8")
    assert "/api/canvas/assets/${match[1]}/direct" in script
    assert "proxyAssetFallback" in script
    assert "image.loading = 'eager'" in script
    assert '@router.get("/api/canvas/assets/{asset_id}/direct")' in router
    assert "generate_presigned_url" in router
    assert "RedirectResponse" in router
    assert "FileResponse" in router


def test_prompt_creation_uses_single_max_query_and_no_full_render_list():
    script = (STATIC / "render-stability.js").read_text(encoding="utf-8")
    router = (APP / "api" / "render_speed.py").read_text(encoding="utf-8")
    assert "/nodes/instant-create" in script
    assert "renderProjectList" not in script
    assert "func.max" in router
    assert "as_integer()" in router
    assert "select(ProjectNode.config).where" not in router
