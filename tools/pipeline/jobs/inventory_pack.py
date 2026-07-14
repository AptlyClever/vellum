"""Inventory and load-check an Unreal pack without exporting its content."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import unreal  # type: ignore

from _common import pack_content_root, pack_name, quit_editor, work_dir, write_manifest


def main() -> None:
    root = pack_content_root()
    pack = pack_name()
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = list(registry.get_assets_by_path(unreal.Name(root), recursive=True) or [])

    class_counts: Counter[str] = Counter()
    load_errors: list[str] = []
    loaded_count = 0

    for asset_data in assets:
        class_name = str(asset_data.asset_class_path.asset_name)
        class_counts[class_name] += 1
        # Maps are packages rather than ordinary loadable asset objects.
        if class_name in {"World", "Level"}:
            continue
        object_path = f"{asset_data.package_name}.{asset_data.asset_name}"
        try:
            if unreal.EditorAssetLibrary.load_asset(str(object_path)) is None:
                load_errors.append(f"load_failed:{object_path}")
            else:
                loaded_count += 1
        except Exception as exc:  # noqa: BLE001
            load_errors.append(f"exception:{object_path}:{exc}")

    manifest = {
        "job": "inventory-pack",
        "pack": pack,
        "content_root": root,
        "ok": bool(assets) and not load_errors,
        "asset_count": len(assets),
        "loaded_count": loaded_count,
        "class_counts": dict(sorted(class_counts.items())),
        "load_errors": load_errors,
    }
    path = work_dir() / pack / "inventory-pack.manifest.json"
    write_manifest(path, manifest)
    unreal.log(
        f"[VellumPipeline] inventory-pack pack={pack} "
        f"assets={len(assets)} load_errors={len(load_errors)}"
    )
    quit_editor(0 if manifest["ok"] else 1)


if __name__ == "__main__":
    main()
