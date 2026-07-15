"""
Conversion Factory job: batch-export StaticMesh / SkeletalMesh / AnimSequence to glTF/GLB.

Run via UnrealEditor-Cmd -ExecutePythonScript=... with env:
  VELLUM_PACK, VELLUM_CONTENT_ROOT (optional), VELLUM_PIPELINE_WORK, VELLUM_VAULT_GAME_READY
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Allow importing sibling _common when executed from disk
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import unreal  # type: ignore

from _common import (
    pack_content_root,
    pack_name,
    quit_editor,
    vault_game_ready,
    wait_for_asset_registry,
    work_dir,
    write_manifest,
)


def _assets_of_class(class_path: str, package_root: str):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    filt = unreal.ARFilter(
        class_paths=[unreal.TopLevelAssetPath("/Script/Engine", class_path)],
        package_paths=[unreal.Name(package_root)],
        recursive_paths=True,
    )
    return list(registry.get_assets(filt) or [])


def run() -> dict[str, Any]:
    """Export meshes; does not quit the editor (safe to call from factory_all)."""
    root = pack_content_root()
    pack = pack_name()
    wait_for_asset_registry(root)
    out_dir = vault_game_ready() / "models" / pack
    out_dir.mkdir(parents=True, exist_ok=True)
    options = unreal.GLTFExportOptions()
    try:
        options.export_uniform_scale = 1.0
    except Exception:
        pass

    exported = []
    errors = []
    classes = ["StaticMesh", "SkeletalMesh", "AnimSequence"]
    for cls in classes:
        for asset_data in _assets_of_class(cls, root):
            name = str(asset_data.asset_name)
            pkg = str(asset_data.package_name)
            try:
                obj = unreal.EditorAssetLibrary.load_asset(f"{pkg}.{name}")
                if obj is None:
                    errors.append(f"load_failed:{pkg}.{name}")
                    continue
                dest = out_dir / f"{cls}_{name}.glb"
                ok = unreal.GLTFExporter.export_to_gltf(obj, str(dest), options, set())
                if ok and dest.exists() and dest.stat().st_size > 0:
                    exported.append(
                        {
                            "class": cls,
                            "asset": f"{pkg}.{name}",
                            "path": str(dest),
                            "bytes": dest.stat().st_size,
                        }
                    )
                else:
                    errors.append(f"export_failed:{pkg}.{name}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"exception:{pkg}.{name}:{exc}")

    manifest = {
        "job": "export-models",
        "pack": pack,
        "content_root": root,
        "ok": len(exported) > 0 and not errors,
        "exported_count": len(exported),
        "exported": exported,
        "errors": errors,
        "note": "Enable GLTFExporter plugin in AuroraVellum if exports are empty.",
    }
    # Soft-ok when pack has zero meshes (pure Niagara packs)
    if len(exported) == 0 and len(errors) == 0:
        manifest["ok"] = True
        manifest["skipped"] = "no_mesh_assets_in_pack"

    man_path = work_dir() / pack / "export-models.manifest.json"
    write_manifest(man_path, manifest)
    write_manifest(out_dir / "manifest.json", manifest)
    unreal.log(f"[VellumPipeline] export-models pack={pack} exported={len(exported)} errors={len(errors)}")
    return manifest


def main() -> None:
    manifest = run()
    quit_editor(0 if manifest["ok"] else 1)


if __name__ == "__main__":
    main()
