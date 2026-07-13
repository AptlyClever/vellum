# Vellum Unreal capture — runs INSIDE Unreal Editor (Python plugin).
#
# Invoked by run_vellum_capture.ps1 via:
#   UnrealEditor-Cmd.exe <uproject> -ExecutePythonScript="<this> -- args"
#
# Goals (best-effort, unsupervised):
# 1) Inventory NiagaraSystem assets under a content root (default FireworksV1)
# 2) Write inspect manifest JSON for Vellum scratch_record
# 3) Attempt HighResShot stills when Editor world is available
#
# This does NOT talk to Epic Launcher / Humble. Redeem stays human.

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _args() -> dict[str, str]:
    raw = sys.argv[1:]
    out: dict[str, str] = {}
    i = 0
    while i < len(raw):
        tok = raw[i]
        if tok.startswith("--") and i + 1 < len(raw):
            out[tok[2:]] = raw[i + 1]
            i += 2
        else:
            i += 1
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    import unreal  # type: ignore

    args = _args()
    asset_id = args.get("asset-id", "fireworks-vol-1-niagara")
    content_root = args.get("content-root", "/Game/FireworksV1")
    out_dir = Path(args.get("out-dir", str(Path(unreal.Paths.project_saved_dir()) / "VellumCapture")))
    max_systems = int(args.get("max-systems", "3"))
    width = int(args.get("width", "1920"))
    height = int(args.get("height", "1080"))

    out_dir.mkdir(parents=True, exist_ok=True)
    stills_dir = out_dir / "stills"
    stills_dir.mkdir(parents=True, exist_ok=True)

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    # Filter Niagara systems under content root
    ar_filter = unreal.ARFilter(
        class_names=["NiagaraSystem"],
        package_paths=[content_root],
        recursive_paths=True,
    )
    assets = list(registry.get_assets(ar_filter) or [])
    systems = []
    for a in assets[: max(1, max_systems)]:
        systems.append(
            {
                "object_path": str(a.get_full_name()) if hasattr(a, "get_full_name") else str(a),
                "package_name": str(a.package_name),
                "asset_name": str(a.asset_name),
            }
        )

    stills: list[dict[str, str]] = []
    capture_errors: list[str] = []

    # Best-effort viewport still. Full Niagara framing is pack-specific; we
    # still produce a timestamped HighResShot so the pipeline is automated.
    try:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        still_path = stills_dir / f"{asset_id}-{stamp}.png"
        # AutomationLibrary wants a path without forcing camera; viewport current.
        unreal.AutomationLibrary.take_high_res_screenshot(
            width,
            height,
            str(still_path),
        )
        # Give slate a moment to flush (scripted runs are async-ish).
        time.sleep(2.0)
        if still_path.is_file():
            stills.append({"path": str(still_path), "kind": "niagara-render"})
        else:
            # UE sometimes writes under Saved/Screenshots instead
            shot_root = Path(unreal.Paths.project_saved_dir()) / "Screenshots"
            candidates = sorted(shot_root.rglob("*.png")) if shot_root.is_dir() else []
            if candidates:
                newest = candidates[-1]
                dest = stills_dir / f"{asset_id}-{stamp}.png"
                dest.write_bytes(newest.read_bytes())
                stills.append({"path": str(dest), "kind": "niagara-render"})
            else:
                capture_errors.append("highresshot_file_missing")
    except Exception as exc:  # noqa: BLE001
        capture_errors.append(f"highresshot:{exc}")

    manifest = {
        "schema_version": 1,
        "tool": "vellum_capture",
        "asset_id": asset_id,
        "content_root": content_root,
        "created_at": _now(),
        "engine": unreal.SystemLibrary.get_engine_version(),
        "project_dir": unreal.Paths.project_dir(),
        "niagara_systems_found": len(assets),
        "niagara_systems": systems,
        "stills": stills,
        "errors": capture_errors,
        "ok": len(systems) > 0,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    unreal.log(f"Vellum capture wrote {manifest_path} systems={len(systems)} stills={len(stills)}")


if __name__ == "__main__":
    main()
