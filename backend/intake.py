"""Vellum IntakeRun — propose staged intake plans (Slice B).

Honest about brittle Epic/Unity steps: many steps start as needs-human.
Does not download or import Epic/Unity packs (Slice E). Automatable vault steps run via jobs (Slice C).

Storage is Postgres (PX001 Wave 3), not a YAML file. The file version
(data/intake-runs.yaml) did a read-whole-file/mutate/write-whole-file round
trip on every propose_intake()/patch_step() call with no lock of any kind, and
that file is bind-mounted into two separate containers (vellum-app serving
the HTTP API, vellum-worker draining the job queue via jobs.py's run_job ->
patch_step) — a real cross-process race, not a hypothetical one. See
deploy/postgres/migrations/vellum/001__intake_runs.sql for the schema this
replaced it with.

Reads (list_runs/get_run) degrade to empty/None when Postgres is not
configured or unreachable — this module backs informational surfaces
(/api/health's recent-run count, journey timelines) that should show "no
data" rather than take the whole app down. Writes (propose_intake/patch_step)
raise instead: this is core intake state, not advisory telemetry, so a write
that silently no-ops would be worse than one that fails loudly.
"""

from __future__ import annotations

import os
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import register as register_mod

STEP_STATUSES = frozenset({"pending", "needs-human", "blocked", "done", "skipped"})
RUN_STATUSES = frozenset({"proposed", "in_progress", "blocked", "completed", "cancelled"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pg_env() -> dict[str, str]:
    """Read fresh from the environment on every call (not cached at import) so
    tests can monkeypatch per-test without reloading this module."""
    return {
        "host": os.environ.get("VELLUM_POSTGRES_HOST", "127.0.0.1"),
        "port": os.environ.get("VELLUM_POSTGRES_PORT", "5433"),
        "dbname": os.environ.get("VELLUM_POSTGRES_DB", "control_alt_fleet"),
        "user": os.environ.get("VELLUM_POSTGRES_USER", "vellum_writer"),
        "password": os.environ.get("VELLUM_POSTGRES_PASSWORD", "").strip(),
    }


def _dsn(*, required: bool) -> str | None:
    """Connection string for the fleet Postgres, or None if not configured.

    No safe default for the password: an unconfigured deploy must not guess
    at trust/peer auth against a LAN-reachable database.
    """
    cfg = _pg_env()
    if not cfg["password"]:
        if required:
            raise RuntimeError("VELLUM_POSTGRES_PASSWORD not configured")
        return None
    return (
        f"host={cfg['host']} port={cfg['port']} dbname={cfg['dbname']} "
        f"user={cfg['user']} password={cfg['password']}"
    )


def _row_to_run(row: dict[str, Any]) -> dict[str, Any]:
    def _iso(value: Any) -> str | None:
        if value is None:
            return None
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    return {
        "run_id": row["run_id"],
        "schema_version": 1,
        "kind": "vellum_intake_run",
        "asset_id": row["asset_id"],
        "display_name": row.get("display_name"),
        "engine": row.get("engine"),
        "store_lane": row.get("store_lane"),
        "source_bundle": row.get("source_bundle"),
        "status": row["status"],
        "requested_by": row.get("requested_by"),
        "note": row.get("note") or "",
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "steps": row.get("steps") or [],
    }


def _step(
    step_id: str,
    title: str,
    *,
    status: str,
    kind: str,
    detail: str,
    automatable: bool,
) -> dict[str, Any]:
    if status not in STEP_STATUSES:
        raise ValueError(f"invalid step status: {status}")
    return {
        "step_id": step_id,
        "title": title,
        "status": status,
        "kind": kind,
        "detail": detail,
        "automatable": automatable,
        "notes": "",
        "updated_at": None,
    }


def build_proposed_steps(asset: dict[str, Any]) -> list[dict[str, Any]]:
    """Build an honest intake plan from register facts. No fake automation."""
    engine = str(asset.get("engine") or "").lower()
    store = str(asset.get("store_lane") or "").lower()
    redeem = str(asset.get("redeem_window") or register_mod.redeem_window(asset.get("redemption_deadline")))
    display = str(asset.get("display_name") or asset.get("id"))
    asset_id = str(asset.get("id"))
    try:
        vault = str(register_mod.ensure_register().get("vault_root") or "/mnt/data/vault/vellum")
    except Exception:
        vault = "/mnt/data/vault/vellum"

    stage_hint = f"{vault}/01-source-bundles/example-asset-bundle/"
    if "unity" in store or engine == "unity":
        stage_hint += f"unity-tier/{asset_id}/"
    else:
        stage_hint += f"epic-unreal/{asset_id}/"

    steps: list[dict[str, Any]] = [
        _step(
            "confirm_register",
            "Confirm register identity",
            status="done",
            kind="catalog",
            detail=f"Register entry exists for {display} ({asset_id}).",
            automatable=True,
        ),
    ]

    if redeem == "expired":
        steps.append(
            _step(
                "redeem_store",
                "Redeem from original store",
                status="blocked",
                kind="redemption",
                detail=(
                    "Redeem window is expired — cannot re-fetch from the original store. "
                    "Does not invalidate already-staged local assets if present."
                ),
                automatable=False,
            )
        )
    else:
        steps.append(
            _step(
                "redeem_store",
                "Redeem from original store",
                status="needs-human",
                kind="redemption",
                detail=(
                    "Redeem via Epic Games Store / Humble as applicable. "
                    "Keys are never stored in Vellum or git."
                ),
                automatable=False,
            )
        )

    if engine == "unity" or "unity" in store:
        steps.append(
            _step(
                "reconcile_unity_contents",
                "Reconcile Unity tier contents",
                status="needs-human",
                kind="inspect",
                detail=(
                    "Unity tier is one redemption bucket — list exact packages after library inspection."
                ),
                automatable=False,
            )
        )
        steps.append(
            _step(
                "download_unity",
                "Download Unity package(s)",
                status="needs-human",
                kind="download",
                detail="Download via Unity / provider tools. Brittle; operator-driven for now.",
                automatable=False,
            )
        )
    else:
        steps.append(
            _step(
                "download_epic",
                "Download via Epic / Fab",
                status="needs-human",
                kind="download",
                detail=(
                    "Download through Epic Games Launcher or Fab. "
                    "Automation is brittle — record outcome; do not pretend full autopilot."
                ),
                automatable=False,
            )
        )

    steps.extend(
        [
            _step(
                "stage_vault",
                "Stage into private vault",
                status="pending",
                kind="stage",
                detail=f"Copy pack into {stage_hint} (never into product git repos).",
                automatable=True,
            ),
            _step(
                "record_paths",
                "Record raw_location on register",
                status="pending",
                kind="catalog",
                detail="Update register raw_location once staged. Agent/API may do this once path is known.",
                automatable=True,
            ),
            _step(
                "license_note",
                "Record license / EULA note status",
                status="needs-human",
                kind="rights",
                detail="Confirm applicable EULA notes under vault 00-admin/licenses/ (no keys).",
                automatable=False,
            ),
            _step(
                "scratch_inspect",
                f"Inspect in {engine or 'engine'} scratch project",
                status="needs-human",
                kind="inspect",
                detail=(
                    f"Open Unreal scratch (e.g. workstation project) with the staged pack. "
                    f"Vault note path: {vault}/03-scratch-projects/{engine or 'unreal'}/. "
                    "Record path + engine version via /api/scratch/record when Niagara systems load."
                ),
                automatable=False,
            ),
            _step(
                "confirm_project_fit",
                "Confirm project-fit lanes",
                status="pending",
                kind="catalog",
                detail=f"Suggested fit from register: {asset.get('project_fit') or '(none)'}",
                automatable=True,
            ),
            _step(
                "derive_lookdev",
                "Derive lookdev stills into project lanes",
                status="pending",
                kind="derive",
                detail=(
                    f"Copy preview stills (png/jpg) from staged pack into {vault}/04-lookdev/ "
                    "and 05-derived-renders/ lanes. Never copy raw .uasset packs into product repos."
                ),
                automatable=True,
            ),
        ]
    )
    return steps


def _rollup_status(steps: list[dict[str, Any]]) -> str:
    statuses = [str(s.get("status")) for s in steps]
    if any(s == "blocked" for s in statuses):
        return "blocked"
    if all(s in {"done", "skipped"} for s in statuses):
        return "completed"
    if any(s in {"needs-human", "pending"} for s in statuses):
        if any(s == "done" for s in statuses):
            return "in_progress"
        return "proposed"
    return "proposed"


def propose_intake(
    asset_id: str,
    *,
    requested_by: str = "operator",
    note: str | None = None,
) -> dict[str, Any]:
    asset = register_mod.get_asset(asset_id)
    if not asset:
        raise KeyError(asset_id)
    steps = build_proposed_steps(asset)
    run_id = f"intake-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    now = _now()
    status = _rollup_status(steps)
    clean_note = (note or "").strip()

    dsn = _dsn(required=True)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO vellum.intake_runs (
                  run_id, asset_id, display_name, engine, store_lane,
                  source_bundle, status, requested_by, note, steps,
                  created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    run_id,
                    asset["id"],
                    asset.get("display_name"),
                    asset.get("engine"),
                    asset.get("store_lane"),
                    asset.get("source_bundle"),
                    status,
                    requested_by,
                    clean_note,
                    Jsonb(steps),
                    now,
                    now,
                ),
            )
            row = cur.fetchone()
    assert row is not None
    return _row_to_run(row)


def list_runs(*, asset_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    dsn = _dsn(required=False)
    if dsn is None:
        return []
    lim = max(1, min(limit, 200))
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if asset_id:
                    cur.execute(
                        "SELECT * FROM vellum.intake_runs WHERE asset_id = %s "
                        "ORDER BY created_at DESC LIMIT %s",
                        (asset_id.strip(), lim),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM vellum.intake_runs ORDER BY created_at DESC LIMIT %s",
                        (lim,),
                    )
                rows = cur.fetchall()
    except psycopg.Error:
        return []
    return [_row_to_run(r) for r in rows]


def get_run(run_id: str) -> dict[str, Any] | None:
    dsn = _dsn(required=False)
    if dsn is None:
        return None
    rid = run_id.strip()
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM vellum.intake_runs WHERE run_id = %s", (rid,))
                row = cur.fetchone()
    except psycopg.Error:
        return None
    return _row_to_run(row) if row else None


def patch_step(
    run_id: str,
    step_id: str,
    *,
    status: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    if status is not None and status not in STEP_STATUSES:
        raise ValueError(f"invalid step status: {status}")
    now = _now()
    dsn = _dsn(required=True)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Row lock: two concurrent patches to the SAME run serialize here
            # instead of racing a whole-file read/mutate/write like the file
            # store did. Patches to different runs never contend at all.
            cur.execute(
                "SELECT * FROM vellum.intake_runs WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(run_id)
            steps = deepcopy(row.get("steps") or [])
            step = None
            for s in steps:
                if isinstance(s, dict) and s.get("step_id") == step_id:
                    step = s
                    break
            if step is None:
                raise KeyError(step_id)
            if status is not None:
                step["status"] = status
            if notes is not None:
                step["notes"] = str(notes)
            step["updated_at"] = now
            new_status = _rollup_status(steps)
            cur.execute(
                """
                UPDATE vellum.intake_runs
                SET steps = %s, status = %s, updated_at = %s
                WHERE run_id = %s
                RETURNING *
                """,
                (Jsonb(steps), new_status, now, run_id),
            )
            updated = cur.fetchone()
    assert updated is not None
    return _row_to_run(updated)
