# Vellum Unreal capture — Phase A, inventory only. Runs INSIDE Unreal Editor
# (Python Editor Script Plugin), via:
#   UnrealEditor-Cmd.exe <uproject> -ExecutePythonScript=<staged script>
#
# Stills are NOT attempted here anymore. UnrealEditor-Cmd has no live viewport
# under -unattended, so HighResShot and editor SceneCapture2D both returned
# empty/zero PNGs no matter how the scene was staged. See
# docs/scratch-inspect-niagara.md for the game-mode capture map that replaced
# that dead end (tools/unreal/vellum_capture_bake_map.py + a `-game` launch).
#
# Config via env (preferred) or --key=value:
#   VELLUM_ASSET_ID, VELLUM_CONTENT_ROOT, VELLUM_OUT_DIR, VELLUM_MAX_SYSTEMS

from __future__ import annotations

import json
import os
import sys
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
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _list_niagara(unreal_mod, registry, content_root: str) -> list:
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


def _resolve_content_root(unreal_mod, registry, preferred: str) -> tuple[str, list]:
    """Try preferred root, then /Game (§12.4 = C)."""
    roots: list[str] = []
    for root in (preferred, "/Game"):
        if root and root not in roots:
            roots.append(root)
    for root in roots:
        try:
            registry.scan_paths_synchronous([root], True)
        except Exception:  # noqa: BLE001
            pass
        assets = _list_niagara(unreal_mod, registry, root)
        if assets:
            return root, assets
    return preferred or "/Game", []


def _asset_object_path(asset_data) -> str:
    pkg = str(asset_data.package_name)
    name = str(asset_data.asset_name)
    return f"{pkg}.{name}"


def _pick_systems(assets: list, max_n: int) -> list:
    """Prefer firework-ish names; otherwise alphabetical."""
    keywords = (
        "finale",
        "burst",
        "shell",
        "rocket",
        "fountain",
        "willow",
        "chrysanthemum",
        "peony",
        "sparkler",
        "cracker",
        "mine",
        "comet",
    )
    scored: list[tuple[int, str, object]] = []
    for a in assets:
        name = str(a.asset_name)
        low = name.lower()
        score = sum(3 for k in keywords if k in low)
        if low.startswith("ns_") or low.startswith("fx_"):
            score += 1
        if "test" in low or "tmp" in low:
            score -= 5
        scored.append((score, name.lower(), a))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [t[2] for t in scored[: max(0, max_n)]]


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

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest-inventory.json"

    systems: list[dict[str, str]] = []
    picked_paths: list[str] = []
    errors: list[str] = []
    assets: list = []

    unreal.log(
        f"Vellum inventory start asset_id={asset_id} content_root={content_root} "
        f"out_dir={out_dir} max_systems={max_systems}"
    )

    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        content_root, assets = _resolve_content_root(unreal, registry, content_root)
        unreal.log(f"Vellum inventory resolved content_root={content_root} count={len(assets)}")
        picked = _pick_systems(assets, max_systems)
        for a in picked:
            obj_path = _asset_object_path(a)
            systems.append(
                {
                    "object_path": obj_path,
                    "package_name": str(a.package_name),
                    "asset_name": str(a.asset_name),
                }
            )
            picked_paths.append(obj_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"inventory:{exc}")
        errors.append(traceback.format_exc()[-1200:])
        unreal.log_error(f"Vellum inventory failed: {exc}")

    manifest = {
        "schema_version": 1,
        "tool": "vellum_capture_inventory",
        "mode": "inventory_only",
        "asset_id": asset_id,
        "content_root": content_root,
        "content_root_preferred": args["content-root"],
        "created_at": _now(),
        "engine": unreal.SystemLibrary.get_engine_version(),
        "project_dir": unreal.Paths.project_dir(),
        "niagara_systems_found": len(assets),
        "niagara_systems": systems,
        "picked_object_paths": picked_paths,
        "errors": errors,
        "ok": True,
    }
    _write_manifest(manifest_path, manifest)
    unreal.log(
        f"Vellum inventory wrote {manifest_path} "
        f"systems_found={len(assets)} picked={len(picked_paths)}"
    )


if __name__ == "__main__":
    main()
