from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.intake import get_run, propose_intake
from backend.jobs import enqueue_automatable_for_run, list_jobs, process_one_job
from backend.register import ensure_register, get_asset


def test_worker_prepares_stage_and_updates_intake(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    runs = tmp_path / "intake.yaml"
    db = tmp_path / "jobs.sqlite3"
    vault = tmp_path / "vault"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_INTAKE_RUNS_PATH", str(runs))
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(db))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(vault))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    monkeypatch.delenv("VELLUM_VAULT_INTAKE_RUNS_PATH", raising=False)
    ensure_register(force_reseed=True)

    run = propose_intake("portal-vfx-enhanced")
    jobs = enqueue_automatable_for_run(run["run_id"])
    assert len(jobs) == 3
    assert all(j["status"] == "queued" for j in jobs)

    for _ in range(5):
        done = process_one_job()
        if done is None:
            break
        assert done["status"] == "succeeded"

    updated = get_run(run["run_id"])
    assert updated is not None
    by_id = {s["step_id"]: s for s in updated["steps"]}
    assert by_id["stage_vault"]["status"] == "done"
    assert by_id["record_paths"]["status"] == "done"
    assert by_id["confirm_project_fit"]["status"] == "done"
    assert by_id["download_epic"]["status"] == "needs-human"

    asset = get_asset("portal-vfx-enhanced")
    assert asset is not None
    assert asset["raw_location"]
    stage = Path(asset["raw_location"])
    assert stage.is_dir()
    assert (stage / ".vellum-stage.json").is_file()


def test_jobs_api(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    runs = tmp_path / "intake.yaml"
    db = tmp_path / "jobs.sqlite3"
    vault = tmp_path / "vault"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_INTAKE_RUNS_PATH", str(runs))
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(db))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(vault))

    from backend.main import app

    client = TestClient(app)
    proposed = client.post(
        "/api/intake/propose",
        json={"asset_id": "hangar-x", "requested_by": "pytest"},
    )
    assert proposed.status_code == 200
    run_id = proposed.json()["run_id"]
    enq = client.post(f"/api/intake/{run_id}/enqueue-automatable")
    assert enq.status_code == 200
    assert enq.json()["count"] == 3

    # Drain queue in-process (worker not running in TestClient)
    while process_one_job() is not None:
        pass

    listed = client.get("/api/jobs", params={"asset_id": "hangar-x"})
    assert listed.status_code == 200
    assert listed.json()["count"] >= 3
    assert all(j["status"] == "succeeded" for j in listed.json()["jobs"][:3])
    assert list_jobs(status="queued") == []
