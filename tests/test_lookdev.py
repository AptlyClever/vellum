from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.jobs import enqueue_job, process_one_job
from backend.lookdev import derive_stills_for_asset, infer_lanes, list_outputs
from backend.register import ensure_register, patch_asset


def _seed_stage(tmp_path: Path, monkeypatch) -> Path:
    reg = tmp_path / "register.yaml"
    derived = tmp_path / "derived.yaml"
    vault = tmp_path / "vault"
    runs = tmp_path / "intake.yaml"
    db = tmp_path / "jobs.sqlite3"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_DERIVED_PATH", str(derived))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(vault))
    monkeypatch.setenv("VELLUM_INTAKE_RUNS_PATH", str(runs))
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(db))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    monkeypatch.delenv("VELLUM_VAULT_DERIVED_PATH", raising=False)
    monkeypatch.delenv("VELLUM_VAULT_INTAKE_RUNS_PATH", raising=False)
    ensure_register(force_reseed=True)

    stage = vault / "01-source-bundles" / "humble" / "fireworks-vol-1-niagara"
    textures = stage / "Textures"
    textures.mkdir(parents=True)
    (textures / "T_Flare01.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (textures / "T_Beam01.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (textures / "ignore.uasset").write_bytes(b"uasset")
    patch_asset(
        "fireworks-vol-1-niagara",
        redemption_status="redeemed",
        raw_location=str(stage),
    )
    return stage


def test_infer_lanes_from_fit() -> None:
    assert "slots" in infer_lanes("Slots wins, Hail stingers")
    assert "hail-overlay" in infer_lanes("Slots wins, Hail stingers")
    assert "godot-field-ops" in infer_lanes("Field Ops lookdev; industrial environment")
    assert "godot-threshold-affairs" in infer_lanes("Threshold Affairs interiors; motel anomaly")
    assert "godot-field-ops" not in infer_lanes("Threshold Affairs interiors")
    assert "godot-threshold-affairs" not in infer_lanes("Field Ops lookdev")


def test_derive_stills_copies_images_not_uassets(tmp_path: Path, monkeypatch) -> None:
    _seed_stage(tmp_path, monkeypatch)
    result = derive_stills_for_asset("fireworks-vol-1-niagara", lanes=["slots"])
    assert result["created_count"] >= 2
    outs = list_outputs(asset_id="fireworks-vol-1-niagara")
    assert outs
    vault = tmp_path / "vault"
    lookdev = vault / "04-lookdev" / "slots" / "fireworks-vol-1-niagara"
    assert (lookdev / "T_Flare01.png").is_file()
    assert not list(lookdev.glob("*.uasset"))
    hero_dir = vault / "05-derived-renders" / "slots" / "fireworks-vol-1-niagara"
    assert any(hero_dir.glob("hero-*"))


def test_derive_job_and_api(tmp_path: Path, monkeypatch) -> None:
    _seed_stage(tmp_path, monkeypatch)
    from backend.main import app

    client = TestClient(app)
    enq = client.post(
        "/api/lookdev/derive",
        json={"asset_id": "fireworks-vol-1-niagara", "lanes": ["slots", "hail-overlay"]},
    )
    assert enq.status_code == 200
    job_id = enq.json()["job"]["job_id"]

    done = process_one_job()
    assert done is not None
    assert done["job_id"] == job_id
    assert done["status"] == "succeeded"

    listed = client.get("/api/lookdev/outputs", params={"asset_id": "fireworks-vol-1-niagara"})
    assert listed.status_code == 200
    assert listed.json()["count"] >= 2
    oid = listed.json()["outputs"][0]["id"]
    file_res = client.get(f"/api/lookdev/outputs/{oid}/file")
    assert file_res.status_code == 200
