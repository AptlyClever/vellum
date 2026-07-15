"""
Conversion Factory job: inventory Niagara systems and author MRQ render destinations
for alpha PNG sequences (Epic Cmd MRQ path), writing a bake plan + optional Flipbook notes.

Full rendering is executed by the Cmd launcher in run_job.ps1 (Phase C style) so this
script stays resilient and artifact-gated. Env: VELLUM_PACK, VELLUM_CONTENT_ROOT, …
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


def _list_niagara(package_root: str):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    class_paths = [
        unreal.TopLevelAssetPath("/Script/Niagara", "NiagaraSystem"),
    ]
    filt = unreal.ARFilter(
        class_paths=class_paths,
        package_paths=[unreal.Name(package_root)],
        recursive_paths=True,
    )
    assets = list(registry.get_assets(filt) or [])
    if not assets:
        all_niag = registry.get_assets_by_class(
            unreal.TopLevelAssetPath("/Script/Niagara", "NiagaraSystem"), True
        )
        assets = [
            a
            for a in (all_niag or [])
            if str(a.package_name).startswith(package_root)
        ]
    return assets


def run() -> dict[str, Any]:
    """Author bake plan; does not quit the editor."""
    root = pack_content_root()
    pack = pack_name()
    wait_for_asset_registry(root)
    wd = work_dir() / pack / "vfx"
    wd.mkdir(parents=True, exist_ok=True)
    out_dir = vault_game_ready() / "vfx" / pack
    out_dir.mkdir(parents=True, exist_ok=True)

    listed = _list_niagara(root)
    systems = []
    for asset_data in listed:
        name = str(asset_data.asset_name)
        pkg = str(asset_data.package_name)
        # Prefer *Single over *Loop siblings (product filter)
        if name.endswith("_Loop") and any(
            str(a.asset_name) == name[: -len("_Loop")] + "_Single" for a in listed
        ):
            continue
        frame_dir = wd / "mrq" / name
        frame_dir.mkdir(parents=True, exist_ok=True)
        systems.append(
            {
                "asset_name": name,
                "object_path": f"{pkg}.{name}",
                "output_dir": str(frame_dir).replace("\\", "/"),
                "bake_methods": ["mrq_alpha_png", "niagara_flipbook_baker"],
            }
        )

    plan = {
        "job": "bake-vfx",
        "pack": pack,
        "content_root": root,
        "map_path": "/Game/Vellum/Maps/VellumLookdevStudio",
        "width": 1920,
        "height": 1080,
        "frame_rate": 30,
        "frame_count": 60,
        "alpha": True,
        "systems": systems,
        "ok": True,
        "next": "run_job.ps1 launches MRQ Cmd using this plan; pack_vfx_media.ps1 builds WebM/sprite sheets",
    }
    write_manifest(wd / "bake-plan.json", plan)
    write_manifest(out_dir / "bake-plan.json", plan)

    notes = [
        "Use Niagara Editor Baker for sprite sheets when automatable; otherwise MRQ alpha PNG → ffmpeg.",
        "Enable project alpha post-process for transparent PNG (Engine/Rendering).",
    ]
    manifest = {
        "job": "bake-vfx",
        "pack": pack,
        "ok": True,
        "systems_found": len(systems),
        "plan": str(wd / "bake-plan.json"),
        "notes": notes,
    }
    write_manifest(wd / "bake-vfx.manifest.json", manifest)
    unreal.log(f"[VellumPipeline] bake-vfx plan systems={len(systems)} pack={pack}")
    (wd / "READY").write_text("ok\n", encoding="utf-8")
    return manifest


def main() -> None:
    run()
    quit_editor(0)


if __name__ == "__main__":
    main()
