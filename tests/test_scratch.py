from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.lookdev import ingest_niagara_render
from backend.register import ensure_register, patch_asset
from backend.scratch import record_scratch_inspect


def test_record_scratch_and_ingest_render(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    derived = tmp_path / "derived.yaml"
    vault = tmp_path / "vault"
    runs = tmp_path / "intake.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_DERIVED_PATH", str(derived))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(vault))
    monkeypatch.setenv("VELLUM_INTAKE_RUNS_PATH", str(runs))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    monkeypatch.delenv("VELLUM_VAULT_DERIVED_PATH", raising=False)
    ensure_register(force_reseed=True)

    result = record_scratch_inspect(
        "fireworks-vol-1-niagara",
        scratch_project_path=r"C:\epic\VellumImport",
        engine_version="5.8",
        notes="systems load",
    )
    assert result["asset"]["scratch_project_status"] == "inspected"
    assert "VellumImport" in result["asset"]["scratch_project_path"]

    src = tmp_path / "viewport.png"
    src.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    row = ingest_niagara_render(
        "fireworks-vol-1-niagara",
        lane="slots",
        source_file=src,
        note="test niagara still",
    )
    assert row["kind"] == "niagara-render"
    assert Path(row["path"]).is_file()
    assert "niagara" in row["path"]

    from backend.main import app

    client = TestClient(app)
    with src.open("rb") as fh:
        up = client.post(
            "/api/lookdev/ingest-render",
            data={"asset_id": "fireworks-vol-1-niagara", "lane": "hail-overlay", "note": "api"},
            files={"file": ("shot.png", fh, "image/png")},
        )
    assert up.status_code == 200
    assert up.json()["output"]["kind"] == "niagara-render"

    rec = client.post(
        "/api/scratch/record",
        json={
            "asset_id": "fireworks-vol-1-niagara",
            "scratch_project_path": r"C:\epic\VellumImport",
            "engine_version": "5.8",
        },
    )
    assert rec.status_code == 200
    assert rec.json()["asset"]["scratch_project_status"] == "inspected"
