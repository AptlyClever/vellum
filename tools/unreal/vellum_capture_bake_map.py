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
# access. What ends up in the map needs zero custom code to "run" under
# `-game`:
#   - NiagaraComponent.auto_activate = True -> system starts simulating on
#     BeginPlay natively (this is how every Niagara component behaves; no
#     script required).
#   - CameraActor.auto_activate_for_player = PLAYER0 -> the engine calls
#     PlayerController.SetViewTarget(this) on BeginPlay natively (this is the
#     literal purpose of that property; also no script required).
# The runner then launches `-game` on this map with
# `-ExecCmds="HighResShot ...,quit"` (tools/unreal/run_vellum_capture.ps1) to
# get an actual rendered frame — something UnrealEditor-Cmd's editor world
# never has under -unattended.
#
# Config (Saved/VellumCapture/job.json, staged alongside this script):
#   {
#     "asset_id": "...",
#     "map_path": "/Game/Vellum/Maps/VellumNiagaraCapture",
#     "system_object_path": "/Game/FireworksV1/....NS_Foo",
#     "system_name": "NS_Foo",
#     "width": 1920, "height": 1080
#   }
#
# Writes Saved/VellumCapture/bake-result.json with ok/errors.

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

    try:
        if not job_path.is_file():
            raise FileNotFoundError(f"job.json not found at {job_path}")
        job = json.loads(job_path.read_text(encoding="utf-8"))
        map_path = str(job.get("map_path") or map_path)
        system_object_path = str(job.get("system_object_path") or "")
        baked_system = str(job.get("system_name") or "")
        baked_object_path = system_object_path
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
        if system_asset is None:
            raise RuntimeError(f"load_failed:{system_object_path}")

        niagara_actor = _spawn_niagara(
            unreal, actor_sub, system_asset, unreal.Vector(0.0, 0.0, 0.0), notes
        )
        if niagara_actor is None:
            raise RuntimeError("spawn_niagara_failed")

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
            raise RuntimeError("map_save_failed")

        ok = True
        unreal.log(f"Vellum bake-map saved {map_path} system={baked_system} notes={','.join(notes)}")
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
            "notes": notes,
            "errors": errors,
            "ok": ok,
        },
    )


if __name__ == "__main__":
    main()
