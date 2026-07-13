# Vellum Unreal capture — Phase B setup, still runs INSIDE Unreal Editor
# (Python Editor Script Plugin), via:
#   UnrealEditor-Cmd.exe <uproject> -ExecutePythonScript=<staged script>
#
# Bakes ONE Niagara system into a persistent, on-disk capture map
# (/Game/Vellum/Maps/VellumNiagaraCapture by default) using ONLY actor
# placement + component properties — no Blueprint graph, no GameMode code.
#
# Why no Blueprint: the stock Python Editor Script Plugin cannot add/wire
# Blueprint graph nodes (no EdGraphPin exposure to Python; confirmed against
# Epic's own Python API docs and forum threads). So instead of a BeginPlay
# graph that reads job.json at runtime, THIS script reads job.json and bakes
# its content directly into the level while we still have full Editor Python
# access. Niagara auto_activate + SceneCapture stills happen here in-editor.
# `-game` HighResShot was abandoned (blank window, zero PNGs).
#
# Config (Saved/VellumCapture/job.json, staged alongside this script):
#   {
#     "asset_id": "...",
#     "map_path": "/Game/Vellum/Maps/VellumNiagaraCapture",
#     "system_object_path": "/Game/FireworksV1/....NS_Foo",
#     "system_name": "NS_Foo",
#     "width": 1920, "height": 1080,
#     "still_path": "C:/epic/.../Saved/VellumCapture/stills/....png"  # optional
#   }
#
# Writes Saved/VellumCapture/bake-result.json with ok/errors/still_path.

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

ACTOR_LABEL_PREFIX = "VellumCapture_"


def _job_path() -> Path:
    env = os.environ.get("VELLUM_JOB_JSON", "").strip()
    if env:
        return Path(env)
    out_dir = os.environ.get("VELLUM_OUT_DIR", "").strip()
    if out_dir:
        return Path(out_dir) / "job.json"
    return Path("Saved/VellumCapture/job.json")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _editor_world(unreal_mod):
    try:
        return unreal_mod.get_editor_subsystem(unreal_mod.UnrealEditorSubsystem).get_editor_world()
    except Exception:  # noqa: BLE001
        return unreal_mod.EditorLevelLibrary.get_editor_world()


def _level_subsystem(unreal_mod):
    try:
        return unreal_mod.get_editor_subsystem(unreal_mod.LevelEditorSubsystem)
    except Exception:  # noqa: BLE001
        return None


def _actor_subsystem(unreal_mod):
    try:
        return unreal_mod.get_editor_subsystem(unreal_mod.EditorActorSubsystem)
    except Exception:  # noqa: BLE001
        return None


def _open_or_create_map(unreal_mod, map_path: str, notes: list[str]) -> bool:
    lvl_sub = _level_subsystem(unreal_mod)
    exists = False
    try:
        exists = unreal_mod.EditorAssetLibrary.does_asset_exist(map_path)
    except Exception:  # noqa: BLE001
        exists = False

    try:
        if exists:
            if lvl_sub is not None:
                lvl_sub.load_level(map_path)
            else:
                unreal_mod.EditorLevelLibrary.load_level(map_path)
            notes.append("loaded_existing_map")
        else:
            if lvl_sub is not None:
                lvl_sub.new_level(map_path)
            else:
                unreal_mod.EditorLevelLibrary.new_level(map_path)
            notes.append("created_new_map")
        return True
    except Exception as exc:  # noqa: BLE001
        notes.append(f"open_or_create_failed:{exc}")
        return False


def _clear_previous_capture_actors(unreal_mod, actor_sub, notes: list[str]) -> None:
    if actor_sub is None:
        return
    try:
        actors = actor_sub.get_all_level_actors()
    except Exception:  # noqa: BLE001
        return
    removed = 0
    for actor in actors:
        try:
            label = actor.get_actor_label()
        except Exception:  # noqa: BLE001
            continue
        if label.startswith(ACTOR_LABEL_PREFIX):
            try:
                actor_sub.destroy_actor(actor)
                removed += 1
            except Exception:  # noqa: BLE001
                pass
    notes.append(f"cleared_previous_actors:{removed}")


def _get_niagara_component(unreal_mod, actor):
    if actor is None:
        return None
    if hasattr(actor, "niagara_component") and actor.niagara_component:
        return actor.niagara_component
    try:
        return actor.get_component_by_class(unreal_mod.NiagaraComponent)
    except Exception:  # noqa: BLE001
        return None


def _spawn_niagara(unreal_mod, actor_sub, system_asset, location, notes: list[str]):
    actor = None
    try:
        actor = actor_sub.spawn_actor_from_object(
            system_asset, location, unreal_mod.Rotator(0.0, 0.0, 0.0), True
        )
    except Exception as exc:  # noqa: BLE001
        notes.append(f"spawn_from_object_failed:{exc}")
    if actor is None:
        try:
            actor = actor_sub.spawn_actor_from_class(
                unreal_mod.NiagaraActor, location, unreal_mod.Rotator(0.0, 0.0, 0.0), True
            )
        except Exception as exc:  # noqa: BLE001
            notes.append(f"spawn_niagara_actor_failed:{exc}")
            return None
        comp = _get_niagara_component(unreal_mod, actor)
        if comp is not None and system_asset is not None:
            try:
                comp.set_asset(system_asset)
            except Exception:  # noqa: BLE001
                try:
                    comp.set_editor_property("asset", system_asset)
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"set_asset_failed:{exc}")
    if actor is not None:
        try:
            actor.set_actor_label(f"{ACTOR_LABEL_PREFIX}System")
        except Exception:  # noqa: BLE001
            pass
    comp = _get_niagara_component(unreal_mod, actor)
    if comp is not None:
        try:
            comp.set_editor_property("auto_activate", True)
            notes.append("auto_activate_set")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"auto_activate_failed:{exc}")
        # Warm up so particles exist on the first rendered -game frame
        # (HighResShot often fires before a multi-second fireworks bloom).
        for prop, val in (
            ("warmup_time", 1.75),
            ("WarmupTime", 1.75),
            ("warmup_tick_count", 60),
            ("WarmupTickCount", 60),
        ):
            try:
                comp.set_editor_property(prop, val)
                notes.append(f"set_{prop}={val}")
                break
            except Exception:  # noqa: BLE001
                continue
    return actor


def _camera_pose_for_actor(unreal_mod, actor, upward_bias: float = 0.45):
    try:
        origin, extent = actor.get_actor_bounds(True)
    except Exception:  # noqa: BLE001
        origin = actor.get_actor_location()
        extent = unreal_mod.Vector(200.0, 200.0, 400.0)

    radius = max(float(extent.x), float(extent.y), float(extent.z), 200.0)
    dist = max(radius * 5.0, 900.0)
    cam = unreal_mod.Vector(
        float(origin.x) - dist * 0.85,
        float(origin.y) - dist * 0.55,
        float(origin.z) + dist * upward_bias,
    )
    look_at = unreal_mod.Vector(
        float(origin.x),
        float(origin.y),
        float(origin.z) + radius * 1.2,
    )
    try:
        rot = unreal_mod.MathLibrary.find_look_at_rotation(cam, look_at)
    except Exception:  # noqa: BLE001
        rot = unreal_mod.Rotator(-25.0, 40.0, 0.0)
    return cam, rot


def _activate_niagara(unreal_mod, comp, notes: list[str]) -> None:
    if comp is None:
        return
    for prop, val in (("auto_activate", True), ("AutoActivate", True)):
        try:
            comp.set_editor_property(prop, val)
            break
        except Exception:  # noqa: BLE001
            continue
    # Ensure the system is visible to SceneCapture (not hidden / exclusive).
    for prop, val in (
        ("hidden_in_scene_capture", False),
        ("visible_in_scene_capture_only", False),
        ("visible", True),
    ):
        try:
            comp.set_editor_property(prop, val)
        except Exception:  # noqa: BLE001
            pass
    try:
        comp.activate(True)
        notes.append("niagara_activate")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"niagara_activate_failed:{exc}")
    for meth in ("reinitialize_system", "ReinitializeSystem", "reset_system", "ResetSystem"):
        if hasattr(comp, meth):
            try:
                getattr(comp, meth)()
                notes.append(f"niagara_{meth}")
                break
            except Exception:  # noqa: BLE001
                continue
    # Fireworks blooms need real simulated time. Prefer tick-count advance
    # (Epic NiagaraComponent API) over a short by-time call.
    advanced = False
    for meth, args in (
        ("advance_simulation", (180, 1.0 / 60.0)),  # ~3s
        ("AdvanceSimulation", (180, 1.0 / 60.0)),
        ("advance_simulation_by_time", (3.0, 1.0 / 60.0)),
        ("AdvanceSimulationByTime", (3.0, 1.0 / 60.0)),
    ):
        if hasattr(comp, meth):
            try:
                getattr(comp, meth)(*args)
                notes.append(f"niagara_{meth}:{args}")
                advanced = True
                break
            except Exception as exc:  # noqa: BLE001
                notes.append(f"niagara_{meth}_failed:{exc}")
    if not advanced:
        notes.append("niagara_advance_unavailable")


def _spawn_debug_marker(unreal_mod, actor_sub, location, notes: list[str]):
    """Bright cube so a working SceneCapture cannot export a pure-black frame."""
    try:
        cube = actor_sub.spawn_actor_from_class(
            unreal_mod.StaticMeshActor,
            location,
            unreal_mod.Rotator(0.0, 0.0, 0.0),
            True,
        )
    except Exception as exc:  # noqa: BLE001
        notes.append(f"debug_marker_spawn_failed:{exc}")
        return None
    if cube is None:
        return None
    try:
        cube.set_actor_label(f"{ACTOR_LABEL_PREFIX}DebugMarker")
        cube.set_actor_scale3d(unreal_mod.Vector(1.5, 1.5, 1.5))
    except Exception:  # noqa: BLE001
        pass
    try:
        mesh = unreal_mod.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube")
        smc = cube.static_mesh_component
        if mesh is not None and smc is not None:
            smc.set_static_mesh(mesh)
        notes.append("debug_marker_cube")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"debug_marker_mesh_failed:{exc}")
    return cube


def _png_max_rgb(path: Path) -> int:
    """Return max RGB channel in a PNG (0 => pure black). Stdlib only."""
    import struct
    import zlib

    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return -1
    i = 8
    idat = b""
    width = height = color = None
    while i < len(data):
        ln = struct.unpack(">I", data[i : i + 4])[0]
        i += 4
        typ = data[i : i + 4]
        i += 4
        chunk = data[i : i + ln]
        i += ln + 4
        if typ == b"IHDR":
            width, height, _bit, color = struct.unpack(">IIBB", chunk[:10])
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
    if not width or color not in (2, 6):
        return -1
    raw = zlib.decompress(idat)
    bpp = 4 if color == 6 else 3
    stride = width * bpp
    mx = 0
    o = 0
    prev = bytearray(stride)
    step_y = max(1, height // 80)
    for y in range(height):
        f = raw[o]
        o += 1
        row = bytearray(raw[o : o + stride])
        o += stride
        if f == 1:
            for x in range(stride):
                row[x] = (row[x] + (row[x - bpp] if x >= bpp else 0)) & 255
        elif f == 2:
            for x in range(stride):
                row[x] = (row[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                left = row[x - bpp] if x >= bpp else 0
                row[x] = (row[x] + ((left + prev[x]) // 2)) & 255
        elif f == 4:
            for x in range(stride):
                a = row[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                row[x] = (row[x] + pr) & 255
        elif f != 0:
            return -1
        if y % step_y == 0:
            for x in range(0, width, max(1, width // 80)):
                r = row[x * bpp]
                g = row[x * bpp + 1]
                b = row[x * bpp + 2]
                mx = max(mx, r, g, b)
                if mx >= 32:
                    return mx
        prev = row
    return mx


def _capture_still(
    unreal_mod,
    actor_sub,
    world,
    cam_loc,
    cam_rot,
    width: int,
    height: int,
    still_path: Path,
    notes: list[str],
    errors: list[str],
    show_only_actors=None,
) -> bool:
    """SceneCapture2D → PNG. Rejects pure-black frames (known empty export)."""
    still_path.parent.mkdir(parents=True, exist_ok=True)
    if still_path.is_file():
        try:
            still_path.unlink()
        except Exception:  # noqa: BLE001
            pass

    capture_actor = None
    try:
        # Clear color with alpha=1 — UE 5.6+ black PNG exports are often alpha-related
        # (Epic forums: export black despite valid RT preview when alpha defaults wrong).
        rt = unreal_mod.RenderingLibrary.create_render_target2d(
            world, int(width), int(height), unreal_mod.TextureRenderTargetFormat.RTF_RGBA8
        )
        if rt is None:
            errors.append("create_render_target_failed")
            return False
        try:
            rt.set_editor_property(
                "clear_color", unreal_mod.LinearColor(0.015, 0.02, 0.04, 1.0)
            )
        except Exception:  # noqa: BLE001
            pass
        notes.append(f"rt_{width}x{height}")

        capture_actor = actor_sub.spawn_actor_from_class(
            unreal_mod.SceneCapture2D, cam_loc, cam_rot, True
        )
        if capture_actor is None:
            errors.append("spawn_scene_capture_failed")
            return False
        try:
            capture_actor.set_actor_label(f"{ACTOR_LABEL_PREFIX}SceneCapture")
        except Exception:  # noqa: BLE001
            pass

        comp = None
        try:
            comp = capture_actor.get_capture_component2d()
        except Exception:  # noqa: BLE001
            comp = None
        if comp is None:
            try:
                comp = capture_actor.get_component_by_class(unreal_mod.SceneCaptureComponent2D)
            except Exception:  # noqa: BLE001
                comp = None
        if comp is None:
            errors.append("no_scene_capture_component")
            return False

        try:
            comp.set_editor_property("texture_target", rt)
        except Exception:
            try:
                comp.texture_target = rt
            except Exception as exc:  # noqa: BLE001
                errors.append(f"set_texture_target_failed:{exc}")
                return False

        for prop, val in (
            ("capture_every_frame", False),
            ("capture_on_movement", False),
            ("always_persist_rendering_state", True),
            ("b_always_persist_rendering_state", True),
        ):
            try:
                comp.set_editor_property(prop, val)
            except Exception:  # noqa: BLE001
                pass
        try:
            comp.set_editor_property(
                "capture_source", unreal_mod.SceneCaptureSource.SCS_FINAL_COLOR_LDR
            )
            notes.append("capture_source_final_color_ldr")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"capture_source_failed:{exc}")
        try:
            # Legacy primitive mode renders the full scene (incl. translucency/Niagara).
            comp.set_editor_property(
                "primitive_render_mode",
                unreal_mod.SceneCapturePrimitiveRenderMode.PRM_RENDER_SCENE_PRIMITIVES,
            )
            notes.append("primitive_render_mode_legacy")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"primitive_render_mode_failed:{exc}")
        if show_only_actors:
            try:
                comp.set_editor_property(
                    "primitive_render_mode",
                    unreal_mod.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST,
                )
                comp.set_editor_property("show_only_actors", list(show_only_actors))
                notes.append(f"show_only_actors:{len(show_only_actors)}")
            except Exception as exc:  # noqa: BLE001
                notes.append(f"show_only_failed:{exc}")

        for i in range(3):
            try:
                comp.capture_scene()
                notes.append(f"capture_scene_{i}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"capture_scene_failed:{exc}")
                return False
            try:
                unreal_mod.SystemLibrary.execute_console_command(world, "r.FlushRenderingCommands")
            except Exception:  # noqa: BLE001
                pass

        export_dir = str(still_path.parent).replace("\\", "/")
        export_name = still_path.name
        try:
            unreal_mod.RenderingLibrary.export_render_target(world, rt, export_dir, export_name)
            notes.append(f"export_render_target:{export_dir}/{export_name}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"export_render_target_failed:{exc}")
            return False

        if not still_path.is_file():
            candidates = list(still_path.parent.glob(still_path.stem + ".*"))
            if candidates:
                candidates[0].replace(still_path)
                notes.append(f"renamed_export:{candidates[0].name}")
            else:
                errors.append(f"export_missing_file:{still_path}")
                return False

        size = still_path.stat().st_size
        notes.append(f"still_bytes:{size}")
        if size < 64:
            errors.append(f"still_too_small:{size}")
            return False

        # Hard quality gate: previous "success" stills were 1920x1080 pure black.
        mx = _png_max_rgb(still_path)
        notes.append(f"still_max_rgb:{mx}")
        if mx < 8:
            errors.append(f"still_pure_black:max_rgb={mx}")
            try:
                still_path.unlink()
            except Exception:  # noqa: BLE001
                pass
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        errors.append(f"capture_still_failed:{exc}")
        return False
    finally:
        if capture_actor is not None and actor_sub is not None:
            try:
                actor_sub.destroy_actor(capture_actor)
            except Exception:  # noqa: BLE001
                pass


def _stage_lighting(unreal_mod, actor_sub, notes: list[str]) -> None:
    try:
        light = actor_sub.spawn_actor_from_class(
            unreal_mod.DirectionalLight,
            unreal_mod.Vector(0.0, 0.0, 800.0),
            unreal_mod.Rotator(-50.0, 35.0, 0.0),
            True,
        )
        if light is not None:
            light.set_actor_label(f"{ACTOR_LABEL_PREFIX}Light")
            if hasattr(light, "set_brightness"):
                try:
                    light.set_brightness(0.35)
                except Exception:  # noqa: BLE001
                    pass
        notes.append("directional_light")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"light_failed:{exc}")

    try:
        sky = actor_sub.spawn_actor_from_class(
            unreal_mod.SkyLight,
            unreal_mod.Vector(0.0, 0.0, 500.0),
            unreal_mod.Rotator(0.0, 0.0, 0.0),
            True,
        )
        if sky is not None:
            sky.set_actor_label(f"{ACTOR_LABEL_PREFIX}Sky")
        notes.append("sky_light")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"skylight_failed:{exc}")


def main() -> None:
    import unreal  # type: ignore

    job_path = _job_path()
    result_path = job_path.parent / "bake-result.json"
    notes: list[str] = []
    errors: list[str] = []
    ok = False
    baked_system = ""
    baked_object_path = ""
    map_path = "/Game/Vellum/Maps/VellumNiagaraCapture"
    still_path_out = ""

    try:
        if not job_path.is_file():
            raise FileNotFoundError(f"job.json not found at {job_path}")
        job = json.loads(job_path.read_text(encoding="utf-8"))
        map_path = str(job.get("map_path") or map_path)
        system_object_path = str(job.get("system_object_path") or "")
        baked_system = str(job.get("system_name") or "")
        baked_object_path = system_object_path
        width = int(job.get("width") or 1920)
        height = int(job.get("height") or 1080)
        still_override = str(job.get("still_path") or "").strip()
        if not system_object_path:
            raise ValueError("job.json missing system_object_path")

        unreal.log(f"Vellum bake-map start map={map_path} system={system_object_path}")

        if not _open_or_create_map(unreal, map_path, notes):
            raise RuntimeError("could_not_open_or_create_map")

        actor_sub = _actor_subsystem(unreal)
        if actor_sub is None:
            raise RuntimeError("no_actor_subsystem")

        _clear_previous_capture_actors(unreal, actor_sub, notes)
        _stage_lighting(unreal, actor_sub, notes)

        system_asset = unreal.EditorAssetLibrary.load_asset(system_object_path)
        if system_asset is None and "." not in system_object_path.split("/")[-1]:
            # Tolerate package-only paths.
            system_asset = unreal.EditorAssetLibrary.load_asset(system_object_path)
        if system_asset is None and " " in system_object_path:
            # Tolerate "NiagaraSystem /Game/Foo.Foo" soft-path dumps.
            system_asset = unreal.EditorAssetLibrary.load_asset(system_object_path.split()[-1])
        if system_asset is None:
            raise RuntimeError(f"load_failed:{system_object_path}")

        niagara_actor = _spawn_niagara(
            unreal, actor_sub, system_asset, unreal.Vector(0.0, 0.0, 0.0), notes
        )
        if niagara_actor is None:
            raise RuntimeError("spawn_niagara_failed")

        # Simulate BEFORE framing — empty Niagara bounds put the camera in the wrong place.
        _activate_niagara(unreal, _get_niagara_component(unreal, niagara_actor), notes)

        marker = _spawn_debug_marker(
            unreal, actor_sub, unreal.Vector(0.0, 0.0, 50.0), notes
        )

        cam_loc, cam_rot = _camera_pose_for_actor(unreal, niagara_actor)
        camera = actor_sub.spawn_actor_from_class(unreal.CameraActor, cam_loc, cam_rot, True)
        if camera is None:
            raise RuntimeError("spawn_camera_failed")
        camera.set_actor_label(f"{ACTOR_LABEL_PREFIX}Camera")
        try:
            camera.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
            notes.append("camera_auto_activate_player0")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"camera_auto_activate_failed:{exc}")

        world = _editor_world(unreal)
        if world is None:
            raise RuntimeError("no_editor_world")

        if still_override:
            still_path = Path(still_override)
        else:
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in baked_system) or "system"
            still_path = job_path.parent / "stills" / f"{job.get('asset_id') or 'asset'}-{safe}.png"

        show_only = [a for a in (niagara_actor, marker, camera) if a is not None]
        # Include lights already labeled in the level.
        try:
            for actor in actor_sub.get_all_level_actors():
                try:
                    label = actor.get_actor_label()
                except Exception:  # noqa: BLE001
                    continue
                if label.startswith(ACTOR_LABEL_PREFIX) and actor not in show_only:
                    show_only.append(actor)
        except Exception:  # noqa: BLE001
            pass

        captured = _capture_still(
            unreal,
            actor_sub,
            world,
            cam_loc,
            cam_rot,
            width,
            height,
            still_path,
            notes,
            errors,
            show_only_actors=None,  # full scene; show-only can hide skylight contribution
        )
        if captured:
            still_path_out = str(still_path).replace("\\", "/")
            notes.append(f"still_ok:{still_path_out}")
        else:
            raise RuntimeError("scene_capture_still_failed")

        saved = False
        try:
            saved = bool(unreal.EditorLoadingAndSavingUtils.save_map(world, map_path))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"save_map_failed:{exc}")
        if not saved:
            try:
                saved = bool(unreal.EditorLevelLibrary.save_current_level())
                notes.append("save_current_level_fallback")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"save_failed:{exc}")
        if not saved:
            notes.append("map_save_skipped_or_failed")

        ok = True
        unreal.log(
            f"Vellum bake-map still={still_path_out} system={baked_system} notes={','.join(notes)}"
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        errors.append(traceback.format_exc()[-1200:])
        try:
            unreal.log_error(f"Vellum bake-map failed: {exc}")
        except Exception:  # noqa: BLE001
            pass

    _write_json(
        result_path,
        {
            "schema_version": 1,
            "tool": "vellum_capture_bake_map",
            "map_path": map_path,
            "system_name": baked_system,
            "system_object_path": baked_object_path,
            "still_path": still_path_out,
            "notes": notes,
            "errors": errors,
            "ok": ok,
        },
    )


if __name__ == "__main__":
    main()
