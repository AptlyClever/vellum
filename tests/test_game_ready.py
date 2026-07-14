"""Game-ready catalog unit tests."""

from __future__ import annotations

import json
from pathlib import Path

from backend import game_ready as gr
from backend import register as register_mod


def test_register_and_list_element(tmp_path, monkeypatch):
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("VELLUM_GAME_READY_PATH", str(tmp_path / "game-ready.yaml"))
    # ensure register has fireworks
    doc = register_mod.ensure_register()
    assert any(a.get("id") == "fireworks-vol-1-niagara" for a in doc.get("assets") or [])

    src = tmp_path / "sample.glb"
    src.write_bytes(b"glTF")
    row = gr.register_element(
        asset_id="fireworks-vol-1-niagara",
        kind="model-gltf",
        path=src,
        pack="FireworksV1",
        note="unit-test",
    )
    assert row["id"].startswith("gr-")
    listed = gr.list_elements(asset_id="fireworks-vol-1-niagara")
    assert len(listed) == 1
    assert listed[0]["kind"] == "model-gltf"
    path = gr.resolve_safe_file(listed[0])
    assert path.is_file()


def test_ingest_manifest_export_models(tmp_path, monkeypatch):
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("VELLUM_GAME_READY_PATH", str(tmp_path / "game-ready.yaml"))
    mesh = tmp_path / "SM_Test.glb"
    mesh.write_bytes(b"glb")
    man = tmp_path / "export-models.manifest.json"
    man.write_text(
        json.dumps(
            {
                "job": "export-models",
                "pack": "FireworksV1",
                "ok": True,
                "exported": [
                    {"class": "StaticMesh", "asset": "/Game/X.SM_Test", "path": str(mesh)}
                ],
            }
        ),
        encoding="utf-8",
    )
    result = gr.ingest_manifest(man, asset_id="fireworks-vol-1-niagara", pack="FireworksV1")
    assert result["registered"] == 1
    assert result["elements"][0]["kind"] == "model-gltf"


def test_publish_to_lane(tmp_path, monkeypatch):
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("VELLUM_GAME_READY_PATH", str(tmp_path / "game-ready.yaml"))
    src = tmp_path / "clip.webm"
    src.write_bytes(b"webm")
    row = gr.register_element(
        asset_id="fireworks-vol-1-niagara",
        kind="vfx-clip",
        path=src,
        pack="FireworksV1",
    )
    published = gr.publish_to_lane(row["id"], "slots")
    assert "slots" in published["lanes"]
    lane_path = Path(published["lane_paths"]["slots"])
    assert lane_path.is_file()
