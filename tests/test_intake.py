from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.intake import get_run, list_runs, patch_step, propose_intake
from backend.register import ensure_register


def test_propose_intake_has_honest_steps(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    runs = tmp_path / "intake-runs.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_INTAKE_RUNS_PATH", str(runs))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    monkeypatch.delenv("VELLUM_VAULT_INTAKE_RUNS_PATH", raising=False)
    ensure_register(force_reseed=True)

    run = propose_intake("portal-vfx-enhanced", requested_by="pytest")
    assert run["kind"] == "vellum_intake_run"
    assert run["asset_id"] == "portal-vfx-enhanced"
    assert run["status"] in {"proposed", "in_progress", "blocked"}
    step_ids = [s["step_id"] for s in run["steps"]]
    assert "confirm_register" in step_ids
    assert "download_epic" in step_ids
    confirm = next(s for s in run["steps"] if s["step_id"] == "confirm_register")
    download = next(s for s in run["steps"] if s["step_id"] == "download_epic")
    assert confirm["status"] == "done"
    assert download["status"] == "needs-human"
    assert download["automatable"] is False


def test_unity_plan_includes_reconcile(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    runs = tmp_path / "intake-runs.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_INTAKE_RUNS_PATH", str(runs))
    ensure_register(force_reseed=True)
    unity = next(a for a in ensure_register()["assets"] if a.get("engine") == "unity")
    run = propose_intake(unity["id"])
    ids = [s["step_id"] for s in run["steps"]]
    assert "reconcile_unity_contents" in ids
    assert "download_unity" in ids


def test_patch_step_rollups(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    runs = tmp_path / "intake-runs.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_INTAKE_RUNS_PATH", str(runs))
    ensure_register(force_reseed=True)
    run = propose_intake("hangar-x")
    updated = patch_step(run["run_id"], "stage_vault", status="done", notes="staged")
    step = next(s for s in updated["steps"] if s["step_id"] == "stage_vault")
    assert step["status"] == "done"
    assert step["notes"] == "staged"
    assert get_run(run["run_id"])["run_id"] == run["run_id"]
    assert list_runs(asset_id="hangar-x")


def test_intake_api(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    runs = tmp_path / "intake-runs.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_INTAKE_RUNS_PATH", str(runs))
    monkeypatch.delenv("VELLUM_VAULT_INTAKE_RUNS_PATH", raising=False)

    from backend.main import app

    client = TestClient(app)
    r = client.post(
        "/api/intake/propose",
        json={"asset_id": "portal-vfx-enhanced", "requested_by": "agent"},
    )
    assert r.status_code == 200
    run = r.json()
    assert run["requested_by"] == "agent"
    listed = client.get("/api/intake", params={"asset_id": "portal-vfx-enhanced"})
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1
    got = client.get(f"/api/intake/{run['run_id']}")
    assert got.status_code == 200
    patched = client.patch(
        f"/api/intake/{run['run_id']}/steps/confirm_project_fit",
        json={"status": "done", "notes": "fit ok"},
    )
    assert patched.status_code == 200
    step = next(s for s in patched.json()["steps"] if s["step_id"] == "confirm_project_fit")
    assert step["status"] == "done"
