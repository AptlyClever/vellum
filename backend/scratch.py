"""Scratch inspect recording — Unreal (and later Unity) workstation projects."""

from __future__ import annotations

from typing import Any

from . import intake as intake_mod
from . import lookdev as lookdev_mod
from . import register as register_mod


def record_scratch_inspect(
    asset_id: str,
    *,
    scratch_project_path: str,
    engine_version: str | None = None,
    notes: str | None = None,
    intake_run_id: str | None = None,
    mark_step_done: bool = True,
) -> dict[str, Any]:
    """Record that an asset was opened/inspected in a scratch Unreal project."""
    if not scratch_project_path.strip():
        raise ValueError("scratch_project_path_required")
    asset = register_mod.get_asset(asset_id)
    if not asset:
        raise KeyError(f"asset_not_found:{asset_id}")

    hint = lookdev_mod.scratch_hint_path(str(asset.get("engine") or "unreal"))
    updated = register_mod.patch_asset(
        asset_id,
        scratch_project_path=scratch_project_path.strip(),
        scratch_project_status="inspected",
        scratch_engine_version=(engine_version or "").strip() or None,
        scratch_notes=notes,
    )

    step_patch: dict[str, Any] | None = None
    if mark_step_done and intake_run_id:
        note = (
            f"scratch={scratch_project_path.strip()}; "
            f"engine={engine_version or '?'}; "
            f"vault_hint={hint}"
        )
        if notes:
            note = f"{note}; {notes}"
        try:
            step_patch = intake_mod.patch_step(
                intake_run_id,
                "scratch_inspect",
                status="done",
                notes=note[:4000],
            )
        except KeyError:
            step_patch = None

    return {
        "asset": updated,
        "vault_scratch_hint": str(hint),
        "intake_run": step_patch,
    }
