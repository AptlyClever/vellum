from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.game_ready import register_element
from backend.main import app
from tools.vellum_cli import cmd_pull


def test_vellum_cli_pull(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    gr = tmp_path / "game_ready.yaml"
    vault = tmp_path / "vault"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_GAME_READY_PATH", str(gr))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(vault))

    # Seed an asset & registered game-ready element for field-ops lane
    from backend.register import ensure_register, patch_asset
    ensure_register(force_reseed=True)
    patch_asset("japanese-old-shopping-mall-interior-environment", redemption_status="redeemed")

    dummy_model = tmp_path / "crate.glb"
    dummy_model.write_bytes(b"GLTF_DUMMY_DATA")

    row = register_element(
        asset_id="japanese-old-shopping-mall-interior-environment",
        kind="model-gltf",
        path=dummy_model,
        lanes=["field-ops"],
    )
    assert row["id"]

    target_dir = tmp_path / "godot_project" / "res" / "assets" / "vellum"
    client = TestClient(app)

    # Monkeypatch urllib.request.urlopen to route requests through FastAPI TestClient
    import json
    import io

    def fake_urlopen(req):
        url = req.full_url
        if "/api/game-ready/elements?lane=" in url:
            lane = url.split("lane=")[1].split("&")[0]
            resp = client.get(f"/api/game-ready/elements?lane={lane}")
            return io.BytesIO(resp.content)
        elif "/api/game-ready/elements/" in url and url.endswith("/file"):
            eid = url.split("/api/game-ready/elements/")[1].split("/file")[0]
            resp = client.get(f"/api/game-ready/elements/{eid}/file")
            return io.BytesIO(resp.content)
        raise ValueError(f"unhandled fake url: {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    res = cmd_pull("field-ops", target_dir, "http://testserver")
    assert res == 0
    assert (target_dir / "model-gltf" / "crate.glb").is_file()
