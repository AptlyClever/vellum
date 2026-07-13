# Vellum Unreal capture — runs INSIDE Unreal Editor (Python plugin).
#
# Invoked by run_vellum_capture.ps1 via:
#   UnrealEditor-Cmd.exe <uproject> -ExecutePythonScript=<staged script>
#
# Config via env (preferred) or --key=value:
#   VELLUM_ASSET_ID, VELLUM_CONTENT_ROOT, VELLUM_OUT_DIR
#   VELLUM_CAPTURE_STILLS=1  → attempt HighResShot console cmd (off by default;
#                              AutomationLibrary.take_high_res_screenshot crashes
#                              UnrealEditor-Cmd / -unattended via FunctionalTesting)
#
# Goals:
# 1) Inventory NiagaraSystem assets under content root
# 2) Always write manifest.json (even if stills fail)
# 3) Optional stills via console HighResShot (best-effort)

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _cli_args() -> dict[str, str]:
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
        "capture-stills": (
            os.environ.get("VELLUM_CAPTURE_STILLS")
            or cli.get("capture-stills")
            or "0"
        ),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2) + "\n"
    # Atomic-ish replace so a mid-crash leave a prior good file when possible.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _list_niagara(unreal_mod, registry, content_root: str) -> list:
    """UE 5.x AssetRegistry: prefer class_paths, fall back to class_names."""
    try:
        ar_filter = unreal_mod.ARFilter(
            class_paths=[unreal_mod.TopLevelAssetPath("/Script/Niagara", "NiagaraSystem")],
            package_paths=[content_root],
            recursive_paths=True,
        )
        return list(registry.get_assets(ar_filter) or [])
    except Exception:  # noqa: BLE001
        ar_filter = unreal_mod.ARFilter(
            class_names=["NiagaraSystem"],
            package_paths=[content_root],
            recursive_paths=True,
        )
        return list(registry.get_assets(ar_filter) or [])


def _try_console_highresshot(unreal_mod, stills_dir: Path, asset_id: str, width: int, height: int) -> tuple[list[dict], list[str]]:
    """
    Avoid AutomationLibrary.take_high_res_screenshot — it AV's in
    UnrealEditor-Cmd / -unattended (FunctionalTesting.dll null world).
    Console HighResShot is best-effort and may still produce nothing headless.
    """
    stills: list[dict[str, str]] = []
    errors: list[str] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shot_root = Path(unreal_mod.Paths.project_saved_dir()) / "Screenshots"
    before = set()
    if shot_root.is_dir():
        before = {p.resolve() for p in shot_root.rglob("*.png")}

    try:
        world = None
        try:
            world = unreal_mod.UnrealEditorSubsystem().get_editor_world()
        except Exception:  # noqa: BLE001
            try:
                world = unreal_mod.EditorLevelLibrary.get_editor_world()
            except Exception:  # noqa: BLE001
                world = None
        cmd = f"HighResShot {width}x{height}"
        unreal_mod.SystemLibrary.execute_console_command(world, cmd)
        time.sleep(3.0)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"highresshot_console:{exc}")
        return stills, errors

    after = []
    if shot_root.is_dir():
        after = sorted(
            (p for p in shot_root.rglob("*.png") if p.resolve() not in before),
            key=lambda p: p.stat().st_mtime,
        )
    if after:
        newest = after[-1]
        dest = stills_dir / f"{asset_id}-{stamp}.png"
        dest.write_bytes(newest.read_bytes())
        stills.append({"path": str(dest), "kind": "niagara-render"})
    else:
        errors.append("highresshot_console_no_file")
    return stills, errors


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
    want_stills = str(args["capture-stills"]).strip().lower() in {"1", "true", "yes", "on"}

    out_dir.mkdir(parents=True, exist_ok=True)
    stills_dir = out_dir / "stills"
    stills_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"

    systems: list[dict[str, str]] = []
    stills: list[dict[str, str]] = []
    capture_errors: list[str] = []
    assets: list = []

    unreal.log(
        f"Vellum capture start asset_id={asset_id} content_root={content_root} "
        f"out_dir={out_dir} capture_stills={want_stills}"
    )

    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        try:
            registry.scan_paths_synchronous([content_root], True)
        except Exception:  # noqa: BLE001
            pass
        assets = _list_niagara(unreal, registry, content_root)
        for a in assets[: max(0, max_systems)]:
            systems.append(
                {
                    "object_path": str(a.get_full_name()) if hasattr(a, "get_full_name") else str(a),
                    "package_name": str(a.package_name),
                    "asset_name": str(a.asset_name),
                }
            )
    except Exception as exc:  # noqa: BLE001
        capture_errors.append(f"inventory:{exc}")
        capture_errors.append(traceback.format_exc()[-1200:])
        unreal.log_error(f"Vellum capture inventory failed: {exc}")

    # Write manifest BEFORE any still attempt. A still crash must not wipe progress.
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
        "errors": list(capture_errors),
        "ok": True,
        "stills_attempted": False,
    }
    _write_manifest(manifest_path, manifest)
    unreal.log(
        f"Vellum capture wrote inventory manifest {manifest_path} "
        f"systems={len(systems)} (stills deferred)"
    )

    if want_stills:
        # Do NOT call unreal.AutomationLibrary.take_high_res_screenshot —
        # it access-violates in FunctionalTesting under UnrealEditor-Cmd.
        more_stills, more_errors = _try_console_highresshot(
            unreal, stills_dir, asset_id, width, height
        )
        stills.extend(more_stills)
        capture_errors.extend(more_errors)
        manifest["stills"] = stills
        manifest["errors"] = capture_errors
        manifest["stills_attempted"] = True
        _write_manifest(manifest_path, manifest)
        unreal.log(
            f"Vellum capture stills done stills={len(stills)} errors={len(more_errors)}"
        )
    else:
        capture_errors.append("stills_skipped_unattended_safe_default")
        manifest["errors"] = capture_errors
        _write_manifest(manifest_path, manifest)
        unreal.log("Vellum capture skipped stills (set VELLUM_CAPTURE_STILLS=1 to attempt)")

    unreal.log(
        f"Vellum capture complete systems={len(systems)} stills={len(stills)} "
        f"errors={len(capture_errors)}"
    )


if __name__ == "__main__":
    main()
