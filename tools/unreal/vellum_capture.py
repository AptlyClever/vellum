# Vellum Unreal capture — Phase A, inventory only. Runs INSIDE Unreal Editor
# (Python Editor Script Plugin), via:
#   UnrealEditor-Cmd.exe <uproject> -ExecutePythonScript=<staged script>
#
# Finds NiagaraSystem assets for MRQ capture (docs/ue-mrq-capture.md).
# Remote Desktop does NOT affect this step (Asset Registry / filesystem only).

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
        "max-systems": os.environ.get("VELLUM_MAX_SYSTEMS") or cli.get("max-systems", "0"),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _prime_asset_registry(unreal_mod, registry, notes: list[str]) -> None:
    # Do NOT time.sleep on the game thread — it stalls registry completion under
    # -ExecutePythonScript. Prefer synchronous scan + search_all_assets.
    try:
        registry.search_all_assets(True)
        notes.append("search_all_assets")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"search_all_assets_failed:{exc}")
    try:
        loading = bool(registry.is_loading_assets())
        notes.append(f"is_loading_assets={loading}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"is_loading_assets_failed:{exc}")


def _is_niagara_system_data(asset_data) -> bool:
    for attr in ("asset_class_path", "asset_class"):
        try:
            val = str(getattr(asset_data, attr))
            if "NiagaraSystem" in val:
                return True
        except Exception:  # noqa: BLE001
            continue
    try:
        cls_path = asset_data.asset_class_path
        if str(getattr(cls_path, "asset_name", "")) == "NiagaraSystem":
            return True
        if str(cls_path).endswith("NiagaraSystem"):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _list_niagara_ar(unreal_mod, registry, content_root: str, notes: list[str]) -> list:
    found: list = []
    try:
        ar_filter = unreal_mod.ARFilter(
            class_paths=[unreal_mod.TopLevelAssetPath("/Script/Niagara", "NiagaraSystem")],
            package_paths=[content_root],
            recursive_paths=True,
        )
        found = list(registry.get_assets(ar_filter) or [])
        notes.append(f"ar_class_paths:{content_root}:{len(found)}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"ar_class_paths_failed:{content_root}:{exc}")
    if found:
        return found
    try:
        ar_filter = unreal_mod.ARFilter(
            class_names=["NiagaraSystem"],
            package_paths=[content_root],
            recursive_paths=True,
        )
        found = list(registry.get_assets(ar_filter) or [])
        notes.append(f"ar_class_names:{content_root}:{len(found)}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"ar_class_names_failed:{content_root}:{exc}")
    return found


def _object_path_from_soft(path: str) -> str:
    p = str(path).strip()
    if not p:
        return p
    if "." in p.rsplit("/", 1)[-1]:
        return p
    name = p.rsplit("/", 1)[-1]
    return f"{p}.{name}"


def _list_niagara_library(unreal_mod, content_root: str, notes: list[str]) -> list[str]:
    """Return soft object paths for Niagara systems via EditorAssetLibrary."""
    paths: list[str] = []
    try:
        listed = unreal_mod.EditorAssetLibrary.list_assets(content_root, True, False) or []
    except Exception as exc:  # noqa: BLE001
        notes.append(f"list_assets_failed:{content_root}:{exc}")
        return []
    notes.append(f"list_assets:{content_root}:{len(listed)}")
    for path in listed:
        p = str(path)
        try:
            data = unreal_mod.EditorAssetLibrary.find_asset_data(p)
            if data and _is_niagara_system_data(data):
                pkg = str(getattr(data, "package_name", "") or p.split(".", 1)[0])
                name = str(getattr(data, "asset_name", "") or pkg.rsplit("/", 1)[-1])
                paths.append(f"{pkg}.{name}")
                continue
        except Exception:  # noqa: BLE001
            pass
        # Name heuristic when class metadata is missing during early registry
        leaf = p.rsplit("/", 1)[-1]
        name = leaf.split(".", 1)[0]
        low = name.lower()
        if low.startswith("ns_") or "niagara" in low:
            paths.append(_object_path_from_soft(p))
    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for op in paths:
        if op not in seen:
            seen.add(op)
            uniq.append(op)
    notes.append(f"list_assets_niagaraish:{content_root}:{len(uniq)}")
    return uniq


def _asset_object_path(asset_data) -> str:
    pkg = str(asset_data.package_name)
    name = str(asset_data.asset_name)
    return f"{pkg}.{name}"


class _PathAsset:
    """Minimal stand-in when we only have a soft path string."""

    def __init__(self, object_path: str):
        self._object_path = _object_path_from_soft(object_path)
        if "." in self._object_path:
            pkg, name = self._object_path.rsplit(".", 1)
        else:
            pkg, name = self._object_path, self._object_path.rsplit("/", 1)[-1]
        self.package_name = pkg
        self.asset_name = name


def _prefer_single_over_loop(assets: list) -> list:
    """Keep unique lookdev targets: drop *_Loop when a *_Single sibling exists."""
    names = {str(getattr(a, "asset_name", a)) for a in assets}
    kept: list = []
    for a in assets:
        name = str(getattr(a, "asset_name", a))
        if name.endswith("_Loop"):
            sibling = name[: -len("_Loop")] + "_Single"
            if sibling in names:
                continue
        kept.append(a)
    return kept


def _pick_systems(assets: list, max_n: int) -> list:
    # max_n <= 0 means the whole pack (after Single-over-Loop de-dupe).
    assets = _prefer_single_over_loop(list(assets))
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
        name = str(getattr(a, "asset_name", a))
        low = name.lower()
        score = sum(3 for k in keywords if k in low)
        if low.startswith("ns_") or low.startswith("fx_"):
            score += 1
        # Prefer one-shot shells over loops for a readable burst arc in ≤4s.
        if low.endswith("_single") or "_single" in low:
            score += 4
        if low.endswith("_loop") or "_loop" in low:
            score -= 1
        if "test" in low or "tmp" in low:
            score -= 5
        scored.append((score, low, a))
    scored.sort(key=lambda t: (-t[0], t[1]))
    ordered = [t[2] for t in scored]
    if max_n <= 0:
        return ordered
    return ordered[:max_n]


def _disk_diagnostics(unreal_mod, notes: list[str]) -> dict:
    diag: dict = {}
    try:
        content_dir = Path(str(unreal_mod.Paths.project_content_dir()))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"project_content_dir_failed:{exc}")
        return diag
    diag["project_content_dir"] = str(content_dir)
    candidates = [
        content_dir / "FireworksV1",
        content_dir / "Fireworks",
        content_dir / "FX",
    ]
    for folder in candidates:
        exists = folder.is_dir()
        notes.append(f"disk:{folder.name}:{'yes' if exists else 'no'}")
        if not exists:
            continue
        uassets = list(folder.rglob("*.uasset"))
        ns_ish = [p for p in uassets if p.name.lower().startswith("ns_")]
        diag[folder.name] = {
            "path": str(folder),
            "uasset_count": len(uassets),
            "ns_prefix_count": len(ns_ish),
            "sample": [p.name for p in ns_ish[:8] or uassets[:8]],
        }
    # Top-level Content folders for "where did Fab put it?"
    try:
        top = sorted([p.name for p in content_dir.iterdir() if p.is_dir()])[:40]
        diag["content_top_dirs"] = top
        notes.append(f"content_top_dirs:{','.join(top[:15])}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"content_list_failed:{exc}")
    return diag


def _resolve_systems(unreal_mod, registry, preferred: str, notes: list[str]) -> tuple[str, list]:
    roots: list[str] = []
    for root in (
        preferred,
        "/Game/FireworksV1",
        "/Game/Fireworks",
        "/Game",
    ):
        if root and root not in roots:
            roots.append(root)

    for root in roots:
        try:
            registry.scan_paths_synchronous([root], True)
            notes.append(f"scan:{root}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"scan_failed:{root}:{exc}")

        ar_hits = _list_niagara_ar(unreal_mod, registry, root, notes)
        if ar_hits:
            return root, ar_hits

        lib_paths = _list_niagara_library(unreal_mod, root, notes)
        if lib_paths:
            return root, [_PathAsset(p if "." in p else f"{p}.{p.rsplit('/', 1)[-1]}") for p in lib_paths]

    return preferred or "/Game", []


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
    notes: list[str] = []
    assets: list = []
    disk = {}

    unreal.log(
        f"Vellum inventory start asset_id={asset_id} content_root={content_root} "
        f"out_dir={out_dir} max_systems={max_systems}"
    )

    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        _prime_asset_registry(unreal, registry, notes)
        disk = _disk_diagnostics(unreal, notes)
        content_root, assets = _resolve_systems(unreal, registry, content_root, notes)
        unreal.log(
            f"Vellum inventory resolved content_root={content_root} count={len(assets)} notes={','.join(notes[-8:])}"
        )
        picked = _pick_systems(assets, max_systems)
        for a in picked:
            if isinstance(a, _PathAsset):
                obj_path = a._object_path
                pkg, name = a.package_name, a.asset_name
            else:
                obj_path = _asset_object_path(a)
                pkg, name = str(a.package_name), str(a.asset_name)
            systems.append(
                {
                    "object_path": obj_path,
                    "package_name": pkg,
                    "asset_name": name,
                }
            )
            picked_paths.append(obj_path)
        if not assets:
            errors.append(
                "no_niagara_systems_found — check Fab Add-to-Project landed under "
                "Content/FireworksV1 (see disk diagnostics). Not an RDP issue."
            )
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
        "notes": notes,
        "disk": disk,
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
