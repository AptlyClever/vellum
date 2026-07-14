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


def test_ingest_run_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("VELLUM_GAME_READY_PATH", str(tmp_path / "game-ready.yaml"))
    register_mod.ensure_register()

    run = tmp_path / "run"
    (run / "models" / "FireworksV1").mkdir(parents=True)
    (run / "models" / "FireworksV1" / "SM_Rocket.glb").write_bytes(b"glb")
    (run / "textures" / "FireworksV1").mkdir(parents=True)
    (run / "textures" / "FireworksV1" / "T_Spark.png").write_bytes(b"png")
    (run / "vfx" / "FireworksV1").mkdir(parents=True)
    (run / "vfx" / "FireworksV1" / "bake-plan.json").write_text("{}", encoding="utf-8")
    (run / "vfx" / "FireworksV1" / "pack-manifest.json").write_text("{}", encoding="utf-8")
    (run / "models" / "FireworksV1" / "ignore.tmp").write_bytes(b"x")

    result = gr.ingest_run_archive(
        run, asset_id="fireworks-vol-1-niagara", pack="FireworksV1"
    )
    assert result["ok"] is True
    assert result["registered"] == 4
    assert result["skipped"] == 1
    kinds = {r["kind"] for r in gr.list_elements(asset_id="fireworks-vol-1-niagara", limit=50)}
    assert kinds == {"model-gltf", "texture", "bake-plan"}


def test_upload_run_endpoint(tmp_path, monkeypatch):
    import io
    import zipfile

    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("VELLUM_GAME_READY_PATH", str(tmp_path / "game-ready.yaml"))
    register_mod.ensure_register()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("models/FireworksV1/SM_Rocket.glb", b"glb")
    buf.seek(0)
    client = TestClient(app)
    res = client.post(
        "/api/assets/fireworks-vol-1-niagara/game-ready/upload-run",
        data={"pack": "FireworksV1"},
        files={"archive": ("run.zip", buf, "application/zip")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["registered"] == 1
    assert gr.list_elements(asset_id="fireworks-vol-1-niagara", limit=5)[0]["kind"] == "model-gltf"


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
