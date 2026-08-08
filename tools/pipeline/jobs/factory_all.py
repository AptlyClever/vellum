"""
Conversion Factory: export-models + export-media + bake-vfx in one UE boot.

Avoids paying three cold-start costs per pack. Individual job scripts remain
available for targeted reruns.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import unreal  # type: ignore

from _common import pack_name, quit_editor, work_dir, write_manifest
from bake_vfx import run as run_bake
from export_media import run as run_media
from export_models import run as run_models


def run() -> dict[str, Any]:
    pack = pack_name()
    results: dict[str, Any] = {}
    failures: list[str] = []

    for label, fn in (
        ("export-models", run_models),
        ("export-media", run_media),
        ("bake-vfx", run_bake),
    ):
        try:
            m = fn()
            results[label] = {
                "ok": bool(m.get("ok", True)),
                "exported_count": m.get("exported_count", m.get("systems_found")),
            }
            if not m.get("ok", True):
                failures.append(label)
        except Exception as exc:  # noqa: BLE001
            results[label] = {"ok": False, "error": str(exc)}
            failures.append(label)
            unreal.log_error(f"[VellumPipeline] factory-all {label} failed: {exc}")

    manifest = {
        "job": "factory-all",
        "pack": pack,
        "ok": len(failures) == 0,
        "jobs": results,
        "failures": failures,
    }
    write_manifest(work_dir() / pack / "factory-all.manifest.json", manifest)
    unreal.log(
        f"[VellumPipeline] factory-all pack={pack} ok={manifest['ok']} failures={failures}"
    )
    return manifest


def main() -> None:
    manifest = run()
    quit_editor(0 if manifest["ok"] else 1)


if __name__ == "__main__":
    main()
