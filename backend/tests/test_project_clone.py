from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.projects import _clone_project_contents
from app.db import Base
from app.models import CanvasGeneration, Project, ProjectAsset, ProjectNode
from app.services.storage import storage


def test_clone_users_project_into_agent_copies_full_canvas(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "copy_key", lambda source, target: None)

    with Session(engine, expire_on_commit=False) as db:
        source = Project(
            id="prj_source",
            title="Основа",
            project_type="user",
            viewport={"x": 17, "y": 23, "zoom": 0.8, "edge_style": "curved"},
        )
        photo = ProjectNode(id="node_photo", project=source, node_type="photo", title="Фото", x=10, y=20, config={})
        prompt = ProjectNode(
            id="node_prompt",
            project=source,
            node_type="prompt",
            title="Промпт №1",
            x=300,
            y=40,
            config={"reference_number": 1, "prompt_text": "Тест", "system_prompt_locked": True},
        )
        note = ProjectNode(
            id="node_note",
            project=source,
            node_type="note",
            title="Заметка",
            x=80,
            y=200,
            config={"note_text": "Связи", "target_node_ids": [photo.id, prompt.id]},
        )
        generation = CanvasGeneration(
            id="gen_source",
            project=source,
            prompt_node=prompt,
            status="completed",
            output_count=1,
            provider="openai",
        )
        reference = ProjectAsset(
            id="asset_ref",
            project_id=source.id,
            node=prompt,
            kind="reference",
            order_index=0,
            original_filename="ref.png",
            storage_key="source/ref.png",
            mime_type="image/png",
            sha256="a" * 64,
        )
        output = ProjectAsset(
            id="asset_out",
            project_id=source.id,
            node=prompt,
            generation=generation,
            kind="output",
            order_index=0,
            original_filename="result.png",
            storage_key="source/result.png",
            mime_type="image/png",
            sha256="b" * 64,
        )
        db.add_all([source, photo, prompt, note, generation, reference, output])
        db.commit()

        duplicate = Project(id="prj_agent", title="Конвейер", project_type="agent")
        db.add(duplicate)
        db.flush()
        copied_keys: list[str] = []
        _clone_project_contents(
            db,
            source,
            duplicate,
            copied_keys,
            include_generations=True,
            include_all_assets=True,
        )
        db.commit()

        copied_nodes = {node.node_type: node for node in duplicate.nodes}
        assert set(copied_nodes) == {"photo", "prompt", "note"}
        assert copied_nodes["prompt"].config["reference_number"] == 1
        assert copied_nodes["prompt"].config["system_prompt_locked"] is True
        assert set(copied_nodes["note"].config["target_node_ids"]) == {
            copied_nodes["photo"].id,
            copied_nodes["prompt"].id,
        }
        assert len(duplicate.generations) == 1
        assert duplicate.generations[0].status == "completed"
        assert duplicate.generations[0].prompt_node_id == copied_nodes["prompt"].id
        copied_assets = copied_nodes["prompt"].assets
        assert {asset.kind for asset in copied_assets} == {"reference", "output"}
        copied_output = next(asset for asset in copied_assets if asset.kind == "output")
        assert copied_output.generation_id == duplicate.generations[0].id
        assert len(copied_keys) == 2
