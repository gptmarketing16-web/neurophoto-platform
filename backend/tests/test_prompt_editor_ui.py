from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_prompt_editor_assets_exist_and_are_injected():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert 'version="0.7.7"' in main
    assert 'prompt-editor.css?v=7.7' in main
    assert 'prompt-editor.js?v=7.7' in main
    assert (STATIC / "prompt-editor.css").is_file()
    assert (STATIC / "prompt-editor.js").is_file()


def test_prompt_editor_contract():
    script = (STATIC / "prompt-editor.js").read_text(encoding="utf-8")
    assert "prompt-editor-panel" in script
    assert "Промпт подключён" in script
    assert "openPromptEditor(node.id)" in script
    assert "savePromptEditor({close: true})" in script
    assert "Сначала сохраните изменения этого блока" in script
    assert "fetchProjectPreservingLocalChanges" in script
    assert "promptEditorReferenceFile" in script
    assert "loading=\"lazy\"" in script


def test_prompt_card_and_panel_styles_are_large_and_responsive():
    css = (STATIC / "prompt-editor.css").read_text(encoding="utf-8")
    assert ".prompt-card-reference" in css
    assert "min-height: 300px" in css
    assert ".prompt-editor-panel" in css
    assert "--prompt-editor-w: 470px" in css
    assert "@media (max-width: 720px)" in css
