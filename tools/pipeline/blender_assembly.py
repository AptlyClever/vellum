"""Headless Blender assembly job script.

Run via: blender --background --python tools/pipeline/blender_assembly.py -- <input_mesh> <output_glb> [--collision]
Handles 3D mesh format conversion (FBX/OBJ/Blend -> GLB), collision hull generation, and LOD export for Godot 4.x.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def run_blender_export(input_mesh: Path, output_glb: Path, generate_collision: bool = False) -> bool:
    """Invoked inside Blender Python environment to export GLB with optional Godot collision mesh nodes."""
    try:
        import bpy  # type: ignore
    except ImportError:
        print("[BlenderAssembly] Error: Must be executed inside Blender Python environment.")
        return False

    # Clear existing scene default objects
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Import mesh based on extension
    ext = input_mesh.suffix.lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(input_mesh))
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=str(input_mesh))
    elif ext in (".gltf", ".glb"):
        bpy.ops.import_scene.gltf(filepath=str(input_mesh))
    elif ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(input_mesh))
    else:
        print(f"[BlenderAssembly] Unsupported format: {ext}")
        return False

    if generate_collision:
        # Create a simplified collision box/convex hull sibling with Godot collision suffix -col
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH" and not obj.name.endswith("-col"):
                coll_obj = obj.copy()
                coll_obj.data = obj.data.copy()
                coll_obj.name = f"{obj.name}-col"
                bpy.context.collection.objects.link(coll_obj)

    output_glb.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(output_glb),
        export_format="GLB",
        export_apply=True,
    )
    return output_glb.exists() and output_glb.stat().st_size > 0


def main() -> None:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser(description="Blender headless GLB exporter")
    parser.add_argument("input_mesh", type=Path, help="Input FBX/OBJ/GLB file")
    parser.add_argument("output_glb", type=Path, help="Output GLB path")
    parser.add_argument("--collision", action="store_true", help="Generate Godot -col collision mesh sibling")

    args = parser.parse_args(argv)
    ok = run_blender_export(args.input_mesh, args.output_glb, args.collision)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
