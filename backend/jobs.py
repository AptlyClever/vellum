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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from . import game_ready as game_ready_mod
from . import intake as intake_mod
from . import lookdev as lookdev_mod
from . import register as register_mod

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "jobs.sqlite3"

AUTOMATABLE_STEP_IDS = frozenset(
    {"stage_vault", "record_paths", "confirm_project_fit", "derive_lookdev", "lane_sync", "headless_verify"}
)

# Handled by vellum-worker (Linux, vault-local).
LINUX_WORKER_KINDS = frozenset(
    {"prepare_stage", "record_paths", "confirm_project_fit", "derive_lookdev", "lane_sync", "headless_verify"}
)
# Handled by Windows UE agent (tools/unreal/vellum_ue_agent.ps1).
UE_AGENT_KINDS = frozenset(
    {
        "ue_capture",
        "ue_stage",
        "host_stage",
        "host_scan",
        "host_open_editor",
        "host_fab_install",
    }
)

# Running UE-agent jobs with no progress/claim heartbeat longer than this are
# failed so a dead PowerShell/Unreal does not block the single-flight queue forever.
# 180s was too aggressive for MRQ author/render quiet periods (worker kept going;
# recover still ingested while claim path thought the job was abandoned).
DEFAULT_STALE_SILENCE_SEC = int(os.environ.get("VELLUM_STALE_JOB_SEC", "1800"))


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


def _parse_ts(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def fail_stale_running_agent_jobs(
    *,
    max_silence_sec: int | None = None,
    kinds: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Fail UE-agent jobs that look abandoned (no updated_at heartbeat).

    Root cause this fixes: agent/task restart or hung Wait leaves status=running
    forever, which also blocks single-flight ue_capture claims.
    """
    silence = (
        DEFAULT_STALE_SILENCE_SEC if max_silence_sec is None else int(max_silence_sec)
    )
    silence = max(30, silence)
    watch = kinds if kinds is not None else UE_AGENT_KINDS
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=silence)
    failed: list[dict[str, Any]] = []
    for job in list_jobs(status="running", limit=200):
        kind = str(job.get("kind") or "")
        if kind not in watch:
            continue
        # Prefer progress heartbeat (updated_at), fall back to started_at.
        stamp = _parse_ts(str(job.get("updated_at") or "")) or _parse_ts(
            str(job.get("started_at") or "")
        )
        if stamp is None:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if stamp > cutoff:
            continue
        age = int((now - stamp).total_seconds())
        reason = (
            f"stale_agent_silence:{age}s>{silence}s "
            f"kind={kind} last={stamp.isoformat()}"
        )
        done = complete_job(
            str(job["job_id"]),
            error=reason,
            result={
                "stale": True,
                "silence_sec": age,
                "max_silence_sec": silence,
                "asset_id": job.get("asset_id"),
            },
        )
        failed.append(done)
    return failed


def claim_next_job(*, kinds: frozenset[str] | None = None) -> dict[str, Any] | None:
    # Clear abandoned Windows claims before single-flight / claim selection.
    fail_stale_running_agent_jobs()
    now = _now()
    with _conn() as conn:
        # Single-flight UE captures: never claim a second while one is running.
        # Prevents dual UnrealEditor MRQ races when multiple captures were queued.
        effective = set(kinds) if kinds is not None else None
        if effective is None or "ue_capture" in effective:
            running = conn.execute(
                """
                SELECT 1 FROM jobs
                WHERE kind = 'ue_capture' AND status = 'running'
                LIMIT 1
                """
            ).fetchone()
            if running:
                if effective is None:
                    # Claiming any kind: skip captures while one runs.
                    row = conn.execute(
                        """
                        SELECT job_id FROM jobs
                        WHERE status = 'queued' AND kind != 'ue_capture'
                        ORDER BY created_at ASC
                        LIMIT 1
                        """
                    ).fetchone()
                else:
                    others = sorted(effective - {"ue_capture"})
                    if not others:
                        return None
                    placeholders = ",".join("?" for _ in others)
                    row = conn.execute(
                        f"""
                        SELECT job_id FROM jobs
                        WHERE status = 'queued' AND kind IN ({placeholders})
                        ORDER BY created_at ASC
                        LIMIT 1
                        """,
                        tuple(others),
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

        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            row = conn.execute(
                f"""
                SELECT job_id FROM jobs
                WHERE status = 'queued' AND kind IN ({placeholders})
                ORDER BY created_at ASC
                LIMIT 1
                """,
                tuple(sorted(kinds)),
            ).fetchone()
        else:
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


def progress_log_path(job_id: str) -> Path:
    path = jobs_db_path().parent / "job-progress"
    path.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)
    return path / f"{safe}.log"


def append_job_progress(job_id: str, *, message: str, log_tail: str | None = None) -> dict[str, Any]:
    """Append a heartbeat line for a running job (Windows agent / runner)."""
    job = get_job(job_id)
    if not job:
        raise KeyError("job_not_found")
    now = _now()
    line = f"{now} | {message.strip()}\n"
    if log_tail and log_tail.strip():
        for raw in log_tail.strip().splitlines()[-20:]:
            line += f"  | {raw.rstrip()}\n"
    path = progress_log_path(job_id)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.write("---\n")
    with _conn() as conn:
        conn.execute(
            "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
            (now, job_id),
        )
    return {"job_id": job_id, "path": str(path), "updated_at": now}


def read_job_progress(job_id: str, *, max_bytes: int = 32_000) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise KeyError("job_not_found")
    path = progress_log_path(job_id)
    text = ""
    if path.is_file():
        data = path.read_bytes()
        if len(data) > max_bytes:
            data = data[-max_bytes:]
        text = data.decode("utf-8", errors="replace")
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "updated_at": job.get("updated_at"),
        "log": text,
    }


def complete_job(
    job_id: str,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    now = _now()
    if status is None:
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


def patch_job_result(job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Update result payload on an already-finished job (follow-up pointers)."""
    now = _now()
    with _conn() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET result_json = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (json.dumps(result), now, job_id),
        )
    job = get_job(job_id)
    if not job:
        raise KeyError(job_id)
    return job


def cancel_job(job_id: str, *, reason: str = "operator_cancelled") -> dict[str, Any]:
    """Operator cancel for queued/running jobs (including orphaned UE captures)."""
    job = get_job(job_id)
    if not job:
        raise KeyError("job_not_found")
    if job.get("status") not in {"queued", "running"}:
        raise ValueError(f"job_status_{job.get('status')}")
    note = (reason or "operator_cancelled").strip()[:4000] or "operator_cancelled"
    return complete_job(
        job_id,
        error=note,
        status="cancelled",
        result={"cancelled": True, "reason": note},
    )


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


def _execute_lane_sync(job: dict[str, Any]) -> dict[str, Any]:
    import shutil
    payload = job.get("payload") or {}
    lane = str(payload.get("lane") or job.get("asset_id") or "godot-field-ops")
    target_dir_str = str(payload.get("target_dir") or "").strip()
    if not target_dir_str:
        raise ValueError("target_dir_required_for_lane_sync")

    dest_base = Path(target_dir_str) / "res" / "assets" / "vellum"
    quarantine_base = dest_base / ".quarantine"
    dest_base.mkdir(parents=True, exist_ok=True)

    elements = game_ready_mod.list_elements(lane=lane)
    synced_count = 0
    synced_files = []

    for el in elements:
        src_path_str = el.get("file_path") or (el.get("lane_paths") or {}).get(lane)
        if not src_path_str:
            continue
        src = Path(src_path_str)
        if not src.is_file():
            continue

        rel_dir = str(el.get("kind") or "misc")
        dest_dir = dest_base / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / src.name

        try:
            shutil.copy2(src, dest_file)
            synced_count += 1
            synced_files.append(str(dest_file))
        except Exception as exc:  # noqa: BLE001
            quarantine_dir = quarantine_base / rel_dir
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            if dest_file.exists():
                try:
                    dest_file.rename(quarantine_dir / src.name)
                except Exception:
                    pass

    manifest = {
        "lane": lane,
        "synced_count": synced_count,
        "synced_files": synced_files[:100],
        "target_dir": str(dest_base),
        "quarantine_dir": str(quarantine_base),
        "synced_at": _now(),
    }
    (dest_base / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _execute_headless_verify(job: dict[str, Any]) -> dict[str, Any]:
    import shutil
    import subprocess
    payload = job.get("payload") or {}
    target_dir_str = str(payload.get("target_dir") or "").strip()
    if not target_dir_str:
        raise ValueError("target_dir_required_for_headless_verify")

    project_dir = Path(target_dir_str)
    if not (project_dir / "project.godot").is_file() and not project_dir.is_dir():
        return {
            "target_dir": target_dir_str,
            "verified": False,
            "reason": "project_dir_not_found",
            "import_errors": 0,
        }

    godot_bin = shutil.which("godot") or shutil.which("godot4")
    if not godot_bin:
        return {
            "target_dir": target_dir_str,
            "verified": False,
            "reason": "godot_binary_not_in_path",
            "import_errors": 0,
            "status": "skipped",
        }

    try:
        proc = subprocess.run(
            [godot_bin, "--path", str(project_dir), "--headless", "-e", "--quit"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = proc.stdout + proc.stderr
        error_lines = [
            line for line in output.splitlines()
            if "ERROR:" in line or "Failed loading" in line or "SCRIPT ERROR" in line
        ]
        return {
            "target_dir": target_dir_str,
            "verified": True,
            "status": "clean" if not error_lines else "import_errors",
            "exit_code": proc.returncode,
            "import_errors": len(error_lines),
            "errors": error_lines[:20],
        }
    except subprocess.TimeoutExpired:
        return {
            "target_dir": target_dir_str,
            "verified": False,
            "status": "timeout",
            "import_errors": 1,
            "errors": ["Godot headless scan timed out after 60s"],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "target_dir": target_dir_str,
            "verified": False,
            "status": "exception",
            "import_errors": 1,
            "errors": [str(exc)],
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
    elif kind == "lane_sync":
        result = _execute_lane_sync(job)
    elif kind == "headless_verify":
        result = _execute_headless_verify(job)
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


def process_one_job(*, kinds: frozenset[str] | None = None) -> dict[str, Any] | None:
    job = claim_next_job(kinds=kinds if kinds is not None else LINUX_WORKER_KINDS)
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
        job = process_one_job(kinds=LINUX_WORKER_KINDS)
        if once:
            return
        if job is None:
            time.sleep(poll_seconds)
