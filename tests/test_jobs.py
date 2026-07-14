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
    assert len(jobs) == 4
    assert all(j["status"] == "queued" for j in jobs)

    for _ in range(8):
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
    assert by_id["derive_lookdev"]["status"] == "skipped"
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
    assert enq.json()["count"] == 4

    # Drain queue in-process (worker not running in TestClient)
    while process_one_job() is not None:
        pass

    listed = client.get("/api/jobs", params={"asset_id": "hangar-x"})
    assert listed.status_code == 200
    assert listed.json()["count"] >= 3
    assert all(j["status"] == "succeeded" for j in listed.json()["jobs"][:3])
    assert list_jobs(status="queued") == []


def test_job_progress_api(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    runs = tmp_path / "intake.yaml"
    db = tmp_path / "jobs.sqlite3"
    vault = tmp_path / "vault"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_INTAKE_RUNS_PATH", str(runs))
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(db))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(vault))

    from backend import jobs as jobs_mod
    from backend.main import app
    from backend.register import ensure_register

    ensure_register(force_reseed=True)
    job = jobs_mod.enqueue_job(kind="ue_capture", asset_id="hangar-x", payload={})
    claimed = jobs_mod.claim_next_job(kinds=frozenset({"ue_capture"}))
    assert claimed is not None
    assert claimed["job_id"] == job["job_id"]

    client = TestClient(app)
    post = client.post(
        f"/api/jobs/{job['job_id']}/progress",
        json={"message": "Phase A inventory still running (30s)", "log_tail": "LogPython: ok\n"},
    )
    assert post.status_code == 200
    got = client.get(f"/api/jobs/{job['job_id']}/progress")
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "running"
    assert "Phase A inventory" in body["log"]
    assert "LogPython: ok" in body["log"]


def test_ue_capture_claim_is_single_flight(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    from backend import jobs as jobs_mod

    first = jobs_mod.enqueue_job(kind="ue_capture", asset_id="a", payload={})
    second = jobs_mod.enqueue_job(kind="ue_capture", asset_id="b", payload={})
    stage = jobs_mod.enqueue_job(kind="host_stage", asset_id="c", payload={})
    claimed = jobs_mod.claim_next_job(kinds=frozenset({"ue_capture", "host_stage"}))
    assert claimed["job_id"] == first["job_id"]
    # While first capture runs, do not claim the second capture — stage is fine.
    next_job = jobs_mod.claim_next_job(kinds=frozenset({"ue_capture", "host_stage"}))
    assert next_job is not None
    assert next_job["job_id"] == stage["job_id"]
    assert next_job["kind"] == "host_stage"
    blocked = jobs_mod.claim_next_job(kinds=frozenset({"ue_capture"}))
    assert blocked is None
    jobs_mod.complete_job(first["job_id"], result={"ok": True})
    resumed = jobs_mod.claim_next_job(kinds=frozenset({"ue_capture"}))
    assert resumed is not None
    assert resumed["job_id"] == second["job_id"]


def test_stale_running_ue_capture_is_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("VELLUM_STALE_JOB_SEC", "30")
    from backend import jobs as jobs_mod
    from datetime import datetime, timedelta, timezone

    job = jobs_mod.enqueue_job(kind="ue_capture", asset_id="stuck-pack", payload={})
    claimed = jobs_mod.claim_next_job(kinds=frozenset({"ue_capture"}))
    assert claimed and claimed["job_id"] == job["job_id"]
    # Backdate updated_at/started_at to simulate abandoned agent.
    old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    with jobs_mod._conn() as conn:
        conn.execute(
            "UPDATE jobs SET updated_at = ?, started_at = ? WHERE job_id = ?",
            (old, old, job["job_id"]),
        )
    failed = jobs_mod.fail_stale_running_agent_jobs(max_silence_sec=30)
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"
    assert "stale_agent_silence" in (failed[0].get("error") or "")
    # Queue can move again.
    nxt = jobs_mod.enqueue_job(kind="ue_capture", asset_id="next-pack", payload={})
    got = jobs_mod.claim_next_job(kinds=frozenset({"ue_capture"}))
    assert got and got["job_id"] == nxt["job_id"]
