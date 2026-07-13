from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.jobs import (
    LINUX_WORKER_KINDS,
    UE_AGENT_KINDS,
    claim_next_job,
    complete_job,
    enqueue_job,
    process_one_job,
)
from backend.register import ensure_register


def test_ue_capture_claim_is_not_taken_by_linux_kinds(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    db = tmp_path / "jobs.sqlite3"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(db))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    ensure_register(force_reseed=True)

    job = enqueue_job(
        kind="ue_capture",
        asset_id="fireworks-vol-1-niagara",
        payload={"lane": "slots"},
    )
    assert job["status"] == "queued"

    assert process_one_job(kinds=LINUX_WORKER_KINDS) is None

    claimed = claim_next_job(kinds=UE_AGENT_KINDS)
    assert claimed is not None
    assert claimed["job_id"] == job["job_id"]
    assert claimed["status"] == "running"
    complete_job(claimed["job_id"], result={"ok": True})

    from backend.main import app

    client = TestClient(app)
    enq = client.post(
        "/api/ue/capture",
        json={"asset_id": "fireworks-vol-1-niagara", "lane": "slots"},
    )
    assert enq.status_code == 200
    assert enq.json()["job"]["kind"] == "ue_capture"

    claim = client.post("/api/jobs/claim", json={"kinds": ["ue_capture"]})
    assert claim.status_code == 200
    assert claim.json()["job"]["kind"] == "ue_capture"
    jid = claim.json()["job"]["job_id"]
    reported = client.post(
        f"/api/jobs/{jid}/report",
        json={
            "result": {"notes": "test"},
            "scratch_project_path": r"C:\epic\VellumImport",
            "engine_version": "5.8",
        },
    )
    assert reported.status_code == 200
    assert reported.json()["job"]["status"] == "succeeded"
