"""Vellum IntakeRun — propose staged intake plans (Slice B).

Honest about brittle Epic/Unity steps: many steps start as needs-human.
Does not download or import yet (Slice C/E).
"""

from __future__ import annotations

import os
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import register as register_mod

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = ROOT / "data" / "intake-runs.yaml"

STEP_STATUSES = frozenset({"pending", "needs-human", "blocked", "done", "skipped"})
RUN_STATUSES = frozenset({"proposed", "in_progress", "blocked", "completed", "cancelled"})


def runs_path() -> Path:
    configured = os.environ.get("VELLUM_INTAKE_RUNS_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_RUNS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_runs() -> dict[str, Any]:
    path = runs_path()
    if not path.is_file():
        return {"version": 1, "runs": []}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"version": 1, "runs": []}
    runs = raw.get("runs")
    if not isinstance(runs, list):
        raw["runs"] = []
    return raw


def _save_runs(doc: dict[str, Any]) -> None:
    path = runs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    vault_mirror = os.environ.get("VELLUM_VAULT_INTAKE_RUNS_PATH", "").strip()
    if vault_mirror:
        mirror = Path(vault_mirror)
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


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

    stage_hint = f"{vault}/01-source-bundles/humble-all-in-one-unreal-unity-gamedev/"
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
                    f"Open scratch under {vault}/03-scratch-projects/{engine or 'unreal'}/ "
                    "and confirm the pack loads. Import scripts come later (Slice E)."
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
                "Optional lookdev still / clip",
                status="pending",
                kind="derive",
                detail=(
                    f"Later: write derived outputs under {vault}/04-lookdev/ "
                    "(Slice F). Skip until inspect succeeds."
                ),
                automatable=False,
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
    run = {
        "run_id": run_id,
        "schema_version": 1,
        "kind": "vellum_intake_run",
        "asset_id": asset["id"],
        "display_name": asset.get("display_name"),
        "engine": asset.get("engine"),
        "store_lane": asset.get("store_lane"),
        "source_bundle": asset.get("source_bundle"),
        "status": _rollup_status(steps),
        "requested_by": requested_by,
        "note": (note or "").strip(),
        "created_at": _now(),
        "updated_at": _now(),
        "steps": steps,
    }
    doc = _load_runs()
    runs = list(doc.get("runs") or [])
    runs.insert(0, run)
    doc["runs"] = runs[:200]
    doc["version"] = 1
    _save_runs(doc)
    return deepcopy(run)


def list_runs(*, asset_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    doc = _load_runs()
    runs = [deepcopy(r) for r in (doc.get("runs") or []) if isinstance(r, dict)]
    if asset_id:
        aid = asset_id.strip()
        runs = [r for r in runs if r.get("asset_id") == aid]
    return runs[: max(1, min(limit, 200))]


def get_run(run_id: str) -> dict[str, Any] | None:
    rid = run_id.strip()
    for run in list_runs(limit=200):
        if run.get("run_id") == rid:
            return run
    return None


def patch_step(
    run_id: str,
    step_id: str,
    *,
    status: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    doc = _load_runs()
    runs = doc.get("runs") or []
    target = None
    for run in runs:
        if isinstance(run, dict) and run.get("run_id") == run_id:
            target = run
            break
    if target is None:
        raise KeyError(run_id)
    steps = target.get("steps") or []
    step = None
    for s in steps:
        if isinstance(s, dict) and s.get("step_id") == step_id:
            step = s
            break
    if step is None:
        raise KeyError(step_id)
    if status is not None:
        if status not in STEP_STATUSES:
            raise ValueError(f"invalid step status: {status}")
        step["status"] = status
    if notes is not None:
        step["notes"] = str(notes)
    step["updated_at"] = _now()
    target["status"] = _rollup_status(steps)
    target["updated_at"] = _now()
    _save_runs(doc)
    return deepcopy(target)
