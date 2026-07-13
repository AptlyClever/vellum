"""Vellum job queue — SQLite-backed, Conduit-shaped API + worker (Slice C).

Automatable IntakeRun steps only. Epic/Unity download/redeem stay needs-human.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import intake as intake_mod
from . import lookdev as lookdev_mod
from . import register as register_mod

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "jobs.sqlite3"

AUTOMATABLE_STEP_IDS = frozenset(
    {"stage_vault", "record_paths", "confirm_project_fit", "derive_lookdev"}
)


def jobs_db_path() -> Path:
    configured = os.environ.get("VELLUM_JOBS_DB_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_DB


def vault_root() -> Path:
    configured = os.environ.get("VELLUM_VAULT_ROOT", "").strip()
    if configured:
        return Path(configured)
    try:
        root = register_mod.ensure_register().get("vault_root")
        if root:
            return Path(str(root))
    except Exception:
        pass
    return Path("/mnt/data/vault/vellum")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    path = jobs_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              job_id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              asset_id TEXT,
              intake_run_id TEXT,
              step_id TEXT,
              payload_json TEXT NOT NULL DEFAULT '{}',
              result_json TEXT,
              error TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at)"
        )
        conn.commit()
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload_json"] or "{}")
    result = json.loads(row["result_json"]) if row["result_json"] else None
    return {
        "job_id": row["job_id"],
        "kind": row["kind"],
        "status": row["status"],
        "asset_id": row["asset_id"],
        "intake_run_id": row["intake_run_id"],
        "step_id": row["step_id"],
        "payload": payload,
        "result": result,
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def enqueue_job(
    *,
    kind: str,
    asset_id: str | None = None,
    intake_run_id: str | None = None,
    step_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job_id = f"job-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    now = _now()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO jobs (
              job_id, kind, status, asset_id, intake_run_id, step_id,
              payload_json, created_at, updated_at
            ) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                kind,
                asset_id,
                intake_run_id,
                step_id,
                json.dumps(payload or {}),
                now,
                now,
            ),
        )
    job = get_job(job_id)
    assert job is not None
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(
    *,
    status: str | None = None,
    asset_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if status:
        clauses.append("status = ?")
        args.append(status)
    if asset_id:
        clauses.append("asset_id = ?")
        args.append(asset_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(max(1, min(limit, 200)))
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?",
            args,
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def claim_next_job() -> dict[str, Any] | None:
    now = _now()
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT job_id FROM jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        job_id = row["job_id"]
        conn.execute(
            """
            UPDATE jobs
            SET status = 'running', started_at = ?, updated_at = ?
            WHERE job_id = ? AND status = 'queued'
            """,
            (now, now, job_id),
        )
        if conn.total_changes == 0:
            return None
    return get_job(job_id)


def complete_job(
    job_id: str,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    now = _now()
    status = "failed" if error else "succeeded"
    with _conn() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = ?, result_json = ?, error = ?, finished_at = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (
                status,
                json.dumps(result) if result is not None else None,
                error,
                now,
                now,
                job_id,
            ),
        )
    job = get_job(job_id)
    assert job is not None
    return job


def stage_path_for_asset(asset: dict[str, Any]) -> Path:
    asset_id = str(asset.get("id"))
    engine = str(asset.get("engine") or "").lower()
    store = str(asset.get("store_lane") or "").lower()
    root = vault_root()
    lane = "unity-tier" if engine == "unity" or "unity" in store else "epic-unreal"
    return root / "01-source-bundles" / "humble-all-in-one-unreal-unity-gamedev" / lane / asset_id


def _execute_prepare_stage(job: dict[str, Any]) -> dict[str, Any]:
    asset_id = job.get("asset_id")
    if not asset_id:
        raise ValueError("asset_id required")
    asset = register_mod.get_asset(str(asset_id))
    if not asset:
        raise KeyError(f"asset_not_found:{asset_id}")
    path = stage_path_for_asset(asset)
    path.mkdir(parents=True, exist_ok=True)
    marker = path / ".vellum-stage.json"
    marker.write_text(
        json.dumps(
            {
                "asset_id": asset["id"],
                "display_name": asset.get("display_name"),
                "prepared_at": _now(),
                "note": "Staging directory prepared. Place downloaded pack files here; never commit to git.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    readme = path / "README.md"
    if not readme.is_file():
        readme.write_text(
            f"# Stage: {asset.get('display_name') or asset_id}\n\n"
            "Drop redeemed/downloaded pack contents here.\n"
            "Do not copy into product repositories.\n",
            encoding="utf-8",
        )
    return {"stage_path": str(path), "marker": str(marker)}


def _execute_record_paths(job: dict[str, Any]) -> dict[str, Any]:
    asset_id = job.get("asset_id")
    if not asset_id:
        raise ValueError("asset_id required")
    asset = register_mod.get_asset(str(asset_id))
    if not asset:
        raise KeyError(f"asset_not_found:{asset_id}")
    path = stage_path_for_asset(asset)
    path.mkdir(parents=True, exist_ok=True)
    register_mod.patch_asset(str(asset_id), raw_location=str(path))
    return {"raw_location": str(path)}


def _execute_confirm_fit(job: dict[str, Any]) -> dict[str, Any]:
    asset_id = job.get("asset_id")
    if not asset_id:
        raise ValueError("asset_id required")
    asset = register_mod.get_asset(str(asset_id))
    if not asset:
        raise KeyError(f"asset_not_found:{asset_id}")
    return {"project_fit": asset.get("project_fit") or "", "confirmed": True}


def _execute_derive_lookdev(job: dict[str, Any]) -> dict[str, Any]:
    asset_id = job.get("asset_id")
    if not asset_id:
        raise ValueError("asset_id required")
    payload = job.get("payload") or {}
    lanes = payload.get("lanes") if isinstance(payload, dict) else None
    if lanes is not None and not isinstance(lanes, list):
        lanes = None
    try:
        result = lookdev_mod.derive_stills_for_asset(
            str(asset_id),
            lanes=[str(x) for x in lanes] if lanes else None,
        )
    except ValueError as exc:
        if "no_preview_stills" in str(exc) or "raw_location_missing" in str(exc):
            return {
                "asset_id": str(asset_id),
                "skipped": True,
                "reason": str(exc),
            }
        raise
    return {
        "asset_id": result["asset_id"],
        "lanes": result["lanes"],
        "created_count": result["created_count"],
        "output_ids": [o["id"] for o in result["outputs"]],
    }


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    kind = job.get("kind")
    if kind == "prepare_stage":
        result = _execute_prepare_stage(job)
    elif kind == "record_paths":
        result = _execute_record_paths(job)
    elif kind == "confirm_project_fit":
        result = _execute_confirm_fit(job)
    elif kind == "derive_lookdev":
        result = _execute_derive_lookdev(job)
    else:
        raise ValueError(f"unknown job kind: {kind}")

    run_id = job.get("intake_run_id")
    step_id = job.get("step_id")
    if run_id and step_id:
        note = json.dumps(result)[:1500]
        step_status = "skipped" if result.get("skipped") else "done"
        try:
            intake_mod.patch_step(
                str(run_id), str(step_id), status=step_status, notes=note
            )
        except Exception as exc:  # noqa: BLE001
            result = {**result, "intake_patch_error": str(exc)}
    return result


def process_one_job() -> dict[str, Any] | None:
    job = claim_next_job()
    if not job:
        return None
    try:
        result = run_job(job)
        return complete_job(job["job_id"], result=result)
    except Exception as exc:  # noqa: BLE001
        return complete_job(job["job_id"], error=str(exc))


def enqueue_automatable_for_run(run_id: str) -> list[dict[str, Any]]:
    run = intake_mod.get_run(run_id)
    if not run:
        raise KeyError(run_id)
    asset_id = str(run.get("asset_id") or "")
    created: list[dict[str, Any]] = []
    kind_map = {
        "stage_vault": "prepare_stage",
        "record_paths": "record_paths",
        "confirm_project_fit": "confirm_project_fit",
        "derive_lookdev": "derive_lookdev",
    }
    for step in run.get("steps") or []:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("step_id") or "")
        if step_id not in AUTOMATABLE_STEP_IDS:
            continue
        if step.get("status") != "pending":
            continue
        if not step.get("automatable"):
            continue
        kind = kind_map.get(step_id)
        if not kind:
            continue
        created.append(
            enqueue_job(
                kind=kind,
                asset_id=asset_id,
                intake_run_id=run_id,
                step_id=step_id,
                payload={"source": "enqueue_automatable"},
            )
        )
    return created


def worker_loop(*, poll_seconds: float = 1.0, once: bool = False) -> None:
    while True:
        job = process_one_job()
        if once:
            return
        if job is None:
            time.sleep(poll_seconds)
