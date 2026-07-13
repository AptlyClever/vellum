# Vellum Unreal capture — runs INSIDE Unreal Editor (Python plugin).
#
# Invoked by run_vellum_capture.ps1 via:
#   UnrealEditor-Cmd.exe <uproject> -ExecutePythonScript=<staged script>
#
# Args prefer env vars (Unreal mangles backslashes / nested quotes on the CLI):
#   VELLUM_ASSET_ID, VELLUM_CONTENT_ROOT, VELLUM_OUT_DIR
# Optional CLI: --key=value / --key value
#
# Goals (best-effort, unsupervised):
# 1) Inventory NiagaraSystem assets under a content root (default FireworksV1)
# 2) Write inspect manifest JSON for Vellum scratch_record
# 3) Attempt HighResShot stills when Editor world is available
#
# This does NOT talk to Epic Launcher / Humble. Redeem stays human.

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _cli_args() -> dict[str, str]:
    """Parse ``--key value`` and ``--key=value``."""
    raw = sys.argv[1:]
    out: dict[str, str] = {}
    i = 0
    while i < len(raw):
        tok = raw[i]
        if tok.startswith("--"):
            body = tok[2:]
            if "=" in body:
                key, val = body.split("=", 1)
                out[key] = val
                i += 1
                continue
            if i + 1 < len(raw) and not raw[i + 1].startswith("--"):
                out[body] = raw[i + 1]
                i += 2
                continue
        i += 1
    return out


def _cfg() -> dict[str, str]:
    cli = _cli_args()
    return {
        "asset-id": os.environ.get("VELLUM_ASSET_ID") or cli.get("asset-id", "fireworks-vol-1-niagara"),
        "content-root": os.environ.get("VELLUM_CONTENT_ROOT") or cli.get("content-root", "/Game/FireworksV1"),
        "out-dir": os.environ.get("VELLUM_OUT_DIR") or cli.get("out-dir", ""),
        "max-systems": os.environ.get("VELLUM_MAX_SYSTEMS") or cli.get("max-systems", "3"),
        "width": os.environ.get("VELLUM_WIDTH") or cli.get("width", "1920"),
        "height": os.environ.get("VELLUM_HEIGHT") or cli.get("height", "1080"),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list_niagara(unreal_mod, registry, content_root: str) -> list:
    """UE 5.x AssetRegistry: prefer class_paths, fall back to class_names."""
    assets = []
    try:
        ar_filter = unreal_mod.ARFilter(
            class_paths=[unreal_mod.TopLevelAssetPath("/Script/Niagara", "NiagaraSystem")],
            package_paths=[content_root],
            recursive_paths=True,
        )
        assets = list(registry.get_assets(ar_filter) or [])
    except Exception:  # noqa: BLE001
        try:
            ar_filter = unreal_mod.ARFilter(
                class_names=["NiagaraSystem"],
                package_paths=[content_root],
                recursive_paths=True,
            )
            assets = list(registry.get_assets(ar_filter) or [])
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"asset_registry_filter_failed:{exc}") from exc
    return assets


def main() -> None:
    import unreal  # type: ignore

    args = _cfg()
    asset_id = args["asset-id"]
    content_root = args["content-root"]
    out_dir = Path(
        args["out-dir"]
        if args["out-dir"]
        else str(Path(unreal.Paths.project_saved_dir()) / "VellumCapture")
    )
    max_systems = int(args["max-systems"])
    width = int(args["width"])
    height = int(args["height"])

    out_dir.mkdir(parents=True, exist_ok=True)
    stills_dir = out_dir / "stills"
    stills_dir.mkdir(parents=True, exist_ok=True)

    systems: list[dict[str, str]] = []
    stills: list[dict[str, str]] = []
    capture_errors: list[str] = []
    assets: list = []

    try:
        unreal.log(
            f"Vellum capture start asset_id={asset_id} content_root={content_root} out_dir={out_dir}"
        )
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        # Ensure disk assets are known (fresh add-to-project can race registry).
        try:
            registry.scan_paths_synchronous([content_root], True)
        except Exception:  # noqa: BLE001
            pass

        assets = _list_niagara(unreal, registry, content_root)
        for a in assets[: max(1, max_systems)]:
            systems.append(
                {
                    "object_path": str(a.get_full_name()) if hasattr(a, "get_full_name") else str(a),
                    "package_name": str(a.package_name),
                    "asset_name": str(a.asset_name),
                }
            )

        # Best-effort viewport still. Full Niagara framing is pack-specific.
        try:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            still_path = stills_dir / f"{asset_id}-{stamp}.png"
            unreal.AutomationLibrary.take_high_res_screenshot(
                width,
                height,
                str(still_path).replace("\\", "/"),
            )
            time.sleep(2.0)
            if still_path.is_file():
                stills.append({"path": str(still_path), "kind": "niagara-render"})
            else:
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
    except Exception as exc:  # noqa: BLE001
        capture_errors.append(f"fatal:{exc}")
        capture_errors.append(traceback.format_exc()[-1500:])
        unreal.log_error(f"Vellum capture failed: {exc}")

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
        # Inventory alone is success for scratch_inspect; stills are best-effort.
        "ok": True,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    unreal.log(
        f"Vellum capture wrote {manifest_path} systems={len(systems)} "
        f"stills={len(stills)} errors={len(capture_errors)}"
    )


# Populated in main() so helpers can reference the unreal module.
unreal = None  # type: ignore


if __name__ == "__main__":
    main()
