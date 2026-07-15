"""
Conversion Factory job: export textures and sound waves to portable files.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

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

# Keep under hub MAX_RUN_ELEMENTS (500) with room for models/manifests.
MAX_TEXTURE_EXPORTS = 200
MAX_AUDIO_EXPORTS = 50


def _get_assets(class_name: str, module: str, package_root: str):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    filt = unreal.ARFilter(
        class_paths=[unreal.TopLevelAssetPath(module, class_name)],
        package_paths=[unreal.Name(package_root)],
        recursive_paths=True,
    )
    return list(registry.get_assets(filt) or [])


def run() -> dict[str, Any]:
    """Export textures/audio; does not quit the editor."""
    root = pack_content_root()
    pack = pack_name()
    wait_for_asset_registry(root)
    out_tex = vault_game_ready() / "textures" / pack
    out_aud = vault_game_ready() / "audio" / pack
    out_tex.mkdir(parents=True, exist_ok=True)
    out_aud.mkdir(parents=True, exist_ok=True)

    exported = []
    errors = []
    tex_seen = 0
    aud_seen = 0

    for asset_data in _get_assets("Texture2D", "/Script/Engine", root):
        if tex_seen >= MAX_TEXTURE_EXPORTS:
            break
        name = str(asset_data.asset_name)
        pkg = str(asset_data.package_name)
        try:
            tex = unreal.EditorAssetLibrary.load_asset(f"{pkg}.{name}")
            if tex is None:
                errors.append(f"tex_load:{name}")
                continue
            dest = out_tex / f"{name}.png"
            task = unreal.AssetExportTask()
            task.object = tex
            task.filename = str(dest)
            task.selected = False
            task.replace_identical = True
            task.prompt = False
            task.automated = True
            ok = unreal.Exporter.run_asset_export_task(task)
            if ok and dest.exists():
                exported.append(
                    {"kind": "texture", "asset": name, "path": str(dest), "bytes": dest.stat().st_size}
                )
                tex_seen += 1
            else:
                errors.append(f"tex_export:{name}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"tex_exc:{name}:{exc}")

    for asset_data in _get_assets("SoundWave", "/Script/Engine", root):
        if aud_seen >= MAX_AUDIO_EXPORTS:
            break
        name = str(asset_data.asset_name)
        pkg = str(asset_data.package_name)
        try:
            snd = unreal.EditorAssetLibrary.load_asset(f"{pkg}.{name}")
            if snd is None:
                errors.append(f"aud_load:{name}")
                continue
            dest = out_aud / f"{name}.wav"
            task = unreal.AssetExportTask()
            task.object = snd
            task.filename = str(dest)
            task.selected = False
            task.replace_identical = True
            task.prompt = False
            task.automated = True
            ok = unreal.Exporter.run_asset_export_task(task)
            if ok and dest.exists():
                exported.append(
                    {"kind": "audio", "asset": name, "path": str(dest), "bytes": dest.stat().st_size}
                )
                aud_seen += 1
            else:
                errors.append(f"aud_export:{name}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"aud_exc:{name}:{exc}")

    manifest = {
        "job": "export-media",
        "pack": pack,
        "content_root": root,
        "ok": True,
        "exported_count": len(exported),
        "exported": exported[:500],
        "errors": errors[:200],
        "error_count": len(errors),
        "texture_cap": MAX_TEXTURE_EXPORTS,
        "audio_cap": MAX_AUDIO_EXPORTS,
    }
    write_manifest(work_dir() / pack / "export-media.manifest.json", manifest)
    write_manifest(vault_game_ready() / "textures" / pack / "manifest.json", manifest)
    unreal.log(f"[VellumPipeline] export-media pack={pack} exported={len(exported)} errors={len(errors)}")
    return manifest


def main() -> None:
    run()
    quit_editor(0)


if __name__ == "__main__":
    main()
