from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend import ue_hosts as ue_hosts_mod
from backend.jobs import (
    LINUX_WORKER_KINDS,
    UE_AGENT_KINDS,
    claim_next_job,
    complete_job,
    enqueue_job,
    process_one_job,
)
from backend.register import ensure_register


def test_ue_hosts_aurora_is_active() -> None:
    payload = ue_hosts_mod.public_hosts_payload()
    assert payload["active"] == "aurora"
    assert payload["active_host"]["id"] == "aurora"
    assert "F:\\Games\\UE_5.8" in payload["active_host"]["ue_editor"]
    ids = {h["id"] for h in payload["hosts"]}
    assert ids == {"aurora", "borealis"}


def test_ue_host_specs_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VELLUM_UE_HOST_SPECS_DIR", str(tmp_path / "specs"))
    from backend.main import app

    client = TestClient(app)
    posted = client.post(
        "/api/ue/hosts/specs",
        json={
            "host_id": "aurora",
            "specs": {
                "cpu": [{"name": "Test CPU", "cores": 16, "logical_processors": 32}],
                "ram_gb": 64,
                "gpus": [{"name": "Test GPU", "adapter_ram_gb": 12}],
            },
        },
    )
    assert posted.status_code == 200
    assert posted.json()["host_id"] == "aurora"
    hosts = client.get("/api/ue/hosts")
    assert hosts.status_code == 200
    active = hosts.json()["active_host"]
    assert active["host_specs"]["ram_gb"] == 64
    assert active["host_specs"]["gpus"][0]["name"] == "Test GPU"


def test_cancel_running_ue_capture(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    db = tmp_path / "jobs.sqlite3"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(db))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    ensure_register(force_reseed=True)

    job = enqueue_job(kind="ue_capture", asset_id="fireworks-vol-1-niagara", payload={})
    claimed = claim_next_job(kinds=UE_AGENT_KINDS)
    assert claimed is not None

    from backend.main import app

    client = TestClient(app)
    cancelled = client.post(f"/api/jobs/{job['job_id']}/cancel", json={})
    assert cancelled.status_code == 200
    assert cancelled.json()["job"]["status"] == "cancelled"

    again = client.post(f"/api/jobs/{job['job_id']}/cancel", json={})
    assert again.status_code == 409


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
    hosts = client.get("/api/ue/hosts")
    assert hosts.status_code == 200
    assert hosts.json()["active"] == "aurora"

    enq = client.post(
        "/api/ue/capture",
        json={"asset_id": "fireworks-vol-1-niagara", "lane": "slots"},
    )
    assert enq.status_code == 200
    body = enq.json()
    assert body["job"]["kind"] == "ue_capture"
    assert body["ue_host"] == "aurora"
    assert "F:\\Games" in body["job"]["payload"]["project_path"]
    assert body["job"]["payload"].get("force") is False
    assert body["job"]["payload"].get("max_systems") == 0

    forced = client.post(
        "/api/ue/capture",
        json={"asset_id": "fireworks-vol-1-niagara", "lane": "slots", "force": True},
    )
    assert forced.status_code == 200
    assert forced.json()["job"]["payload"]["force"] is True

    claim = client.post("/api/jobs/claim", json={"kinds": ["ue_capture"]})
    assert claim.status_code == 200
    assert claim.json()["job"]["kind"] == "ue_capture"
    jid = claim.json()["job"]["job_id"]
    reported = client.post(
        f"/api/jobs/{jid}/report",
        json={
            "result": {"notes": "test", "ue_host": "aurora"},
            "scratch_project_path": r"F:\Games\AuroraVellum",
            "engine_version": "5.8",
        },
    )
    assert reported.status_code == 200
    assert reported.json()["job"]["status"] == "succeeded"
