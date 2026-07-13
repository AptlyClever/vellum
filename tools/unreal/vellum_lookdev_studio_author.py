# Vellum Lookdev Studio — build once inside Unreal (Python Editor Script).
# Creates a permanent "photo studio" map:
#   /Game/Vellum/Maps/VellumLookdevStudio
# with lights, a center stand/mark, and a mid camera aimed at the mark.
#
# Capture jobs load this map instead of inventing a new empty void every time.

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

STUDIO_MAP = "/Game/Vellum/Maps/VellumLookdevStudio"
PREFIX = "VellumStudio_"
# Bump when lighting/layout must rebuild on every host without a manual ForceStudio.
STUDIO_BUILD = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cfg() -> dict[str, str]:
    return {
        "out-dir": os.environ.get("VELLUM_OUT_DIR") or "",
        "map-path": os.environ.get("VELLUM_STUDIO_MAP") or STUDIO_MAP,
    }


def _set_prop(obj, names, value) -> bool:
    for name in names:
        try:
            obj.set_editor_property(name, value)
            return True
        except Exception:  # noqa: BLE001
            try:
                setattr(obj, name, value)
                return True
            except Exception:  # noqa: BLE001
                continue
    return False


def _spawn(unreal_mod, actor_sub, *, actor_class=None, obj=None, loc=None, rot=None, label: str = ""):
    if loc is None:
        loc = unreal_mod.Vector(0.0, 0.0, 0.0)
    if rot is None:
        rot = unreal_mod.Rotator(0.0, 0.0, 0.0)
    actor = None
    if obj is not None:
        actor = actor_sub.spawn_actor_from_object(obj, loc, rot, False)
    else:
        actor = actor_sub.spawn_actor_from_class(actor_class, loc, rot, False)
    if actor is None:
        return None
    if label:
        try:
            actor.set_actor_label(label)
        except Exception:  # noqa: BLE001
            pass
    try:
        actor.set_folder_path("VellumStudio")
    except Exception:  # noqa: BLE001
        pass
    return actor


def _clear_studio_actors(actor_sub, notes: list[str]) -> None:
    removed = 0
    try:
        for actor in list(actor_sub.get_all_level_actors()):
            try:
                label = actor.get_actor_label()
            except Exception:  # noqa: BLE001
                continue
            if label.startswith(PREFIX):
                actor_sub.destroy_actor(actor)
                removed += 1
    except Exception as exc:  # noqa: BLE001
        notes.append(f"clear_failed:{exc}")
    notes.append(f"cleared_studio_actors:{removed}")


def _open_or_create_map(unreal_mod, map_path: str, notes: list[str]) -> bool:
    try:
        if unreal_mod.EditorAssetLibrary.does_asset_exist(map_path):
            ok = unreal_mod.EditorLoadingAndSavingUtils.load_map(map_path)
            notes.append(f"load_map:{bool(ok)}")
            return bool(ok)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"load_map_failed:{exc}")
    try:
        unreal_mod.EditorLevelLibrary.new_level(map_path)
        notes.append("new_level")
        return True
    except Exception as exc:  # noqa: BLE001
        notes.append(f"new_level_failed:{exc}")
    try:
        unreal_mod.EditorLevelLibrary.new_blank_map(False)
        notes.append("new_blank_map")
        return True
    except Exception as exc:  # noqa: BLE001
        notes.append(f"new_blank_failed:{exc}")
        return False


def _save_map(unreal_mod, map_path: str, notes: list[str], errors: list[str]) -> None:
    try:
        world = unreal_mod.EditorLevelLibrary.get_editor_world()
        unreal_mod.EditorLoadingAndSavingUtils.save_map(world, map_path)
        notes.append("saved_map")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"save_map_failed:{exc}")
        try:
            unreal_mod.EditorLevelLibrary.save_current_level()
            notes.append("save_current_level")
        except Exception as exc2:  # noqa: BLE001
            errors.append(f"save_current_failed:{exc2}")
            raise
    try:
        unreal_mod.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    except Exception:  # noqa: BLE001
        pass
    if not unreal_mod.EditorAssetLibrary.does_asset_exist(map_path):
        # new_blank_map may need an explicit save as asset path
        try:
            world = unreal_mod.EditorLevelLibrary.get_editor_world()
            unreal_mod.EditorLoadingAndSavingUtils.save_map(world, map_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"map_missing:{map_path}:{exc}")
            raise RuntimeError(f"map_not_saved:{map_path}") from exc


def _spawn_floor(unreal_mod, actor_sub, notes: list[str]) -> None:
    mesh = None
    for path in (
        "/Engine/BasicShapes/Plane",
        "/Engine/BasicShapes/Cube",
    ):
        try:
            mesh = unreal_mod.EditorAssetLibrary.load_asset(path)
            if mesh is not None:
                notes.append(f"floor_mesh:{path}")
                break
        except Exception:  # noqa: BLE001
            continue
    if mesh is None:
        notes.append("floor_mesh_missing")
        return
    actor = _spawn(
        unreal_mod,
        actor_sub,
        obj=mesh,
        loc=unreal_mod.Vector(0.0, 0.0, 0.0),
        label=f"{PREFIX}Floor",
    )
    if actor is None:
        notes.append("floor_spawn_failed")
        return
    try:
        actor.set_actor_scale3d(unreal_mod.Vector(40.0, 40.0, 1.0))
    except Exception:  # noqa: BLE001
        try:
            actor.set_actor_scale3d(unreal_mod.Vector(40.0, 40.0, 0.05))
        except Exception:  # noqa: BLE001
            pass
    notes.append("floor")


def _spawn_pedestal(unreal_mod, actor_sub, notes: list[str]) -> None:
    mesh = None
    for path in ("/Engine/BasicShapes/Cylinder", "/Engine/BasicShapes/Cube"):
        try:
            mesh = unreal_mod.EditorAssetLibrary.load_asset(path)
            if mesh is not None:
                break
        except Exception:  # noqa: BLE001
            continue
    if mesh is None:
        notes.append("pedestal_mesh_missing")
        return
    actor = _spawn(
        unreal_mod,
        actor_sub,
        obj=mesh,
        loc=unreal_mod.Vector(0.0, 0.0, 50.0),
        label=f"{PREFIX}Pedestal",
    )
    if actor is None:
        notes.append("pedestal_spawn_failed")
        return
    try:
        actor.set_actor_scale3d(unreal_mod.Vector(1.2, 1.2, 1.0))
    except Exception:  # noqa: BLE001
        pass
    notes.append("pedestal")


def _spawn_slot_mark(unreal_mod, actor_sub, notes: list[str]) -> None:
    # Empty target point at the "stand" — fireworks fire from here; models sit here.
    cls = getattr(unreal_mod, "TargetPoint", None) or getattr(unreal_mod, "Actor", None)
    actor = _spawn(
        unreal_mod,
        actor_sub,
        actor_class=cls,
        loc=unreal_mod.Vector(0.0, 0.0, 120.0),
        label=f"{PREFIX}Slot_Center",
    )
    if actor is None:
        notes.append("slot_spawn_failed")
        return
    notes.append("slot_center")


def _spawn_lights(unreal_mod, actor_sub, notes: list[str]) -> None:
    # Photo studio: key + fill + rim only.
    # Never spawn SkyLight — realtime-capture-without-atmosphere blacks Lit mode
    # with the red viewport banner. Fireworks are emissive; they don't need a skylight.
    try:
        light = _spawn(
            unreal_mod,
            actor_sub,
            actor_class=unreal_mod.DirectionalLight,
            loc=unreal_mod.Vector(0.0, 0.0, 1200.0),
            rot=unreal_mod.Rotator(-55.0, 35.0, 0.0),
            label=f"{PREFIX}KeyLight",
        )
        if light:
            comp = light.get_component_by_class(unreal_mod.DirectionalLightComponent)
            if comp is not None:
                _set_prop(comp, ("intensity",), 12.0)
                _set_prop(comp, ("indirect_lighting_intensity",), 1.0)
                _set_prop(comp, ("atmosphere_sun_light", "b_atmosphere_sun_light"), False)
        notes.append("key_light")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"key_light_failed:{exc}")

    try:
        fill = _spawn(
            unreal_mod,
            actor_sub,
            actor_class=unreal_mod.PointLight,
            loc=unreal_mod.Vector(-600.0, 800.0, 400.0),
            label=f"{PREFIX}FillLight",
        )
        if fill:
            comp = fill.get_component_by_class(unreal_mod.PointLightComponent)
            if comp is not None:
                _set_prop(comp, ("intensity",), 12.0)
                _set_prop(comp, ("attenuation_radius", "AttenuationRadius"), 5000.0)
                _set_prop(comp, ("source_radius", "SourceRadius"), 120.0)
        notes.append("fill_light")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"fill_light_failed:{exc}")

    try:
        rim = _spawn(
            unreal_mod,
            actor_sub,
            actor_class=unreal_mod.PointLight,
            loc=unreal_mod.Vector(900.0, -700.0, 500.0),
            label=f"{PREFIX}RimLight",
        )
        if rim:
            comp = rim.get_component_by_class(unreal_mod.PointLightComponent)
            if comp is not None:
                _set_prop(comp, ("intensity",), 6.0)
                _set_prop(comp, ("attenuation_radius", "AttenuationRadius"), 5000.0)
        notes.append("rim_light")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"rim_light_failed:{exc}")


def _spawn_camera(unreal_mod, actor_sub, notes: list[str]) -> None:
    look = unreal_mod.Vector(0.0, 0.0, 400.0)
    cam_loc = unreal_mod.Vector(-2200.0, -1600.0, 500.0)
    try:
        rot = unreal_mod.MathLibrary.find_look_at_rotation(cam_loc, look)
    except Exception:  # noqa: BLE001
        rot = unreal_mod.Rotator(-12.0, 36.0, 0.0)
    camera = _spawn(
        unreal_mod,
        actor_sub,
        actor_class=unreal_mod.CineCameraActor,
        loc=cam_loc,
        rot=rot,
        label=f"{PREFIX}Cam_Mid",
    )
    if camera is None:
        notes.append("camera_spawn_failed")
        return
    try:
        cine = camera.get_cine_camera_component()
    except Exception:  # noqa: BLE001
        cine = None
    if cine is None:
        try:
            cine = camera.get_component_by_class(unreal_mod.CineCameraComponent)
        except Exception:  # noqa: BLE001
            cine = None
    if cine is not None:
        _set_prop(cine, ("current_focal_length",), 35.0)
        _set_prop(cine, ("current_aperture",), 2.8)
        try:
            pps = cine.post_process_settings
            _set_prop(pps, ("override_auto_exposure_method", "b_override_auto_exposure_method"), True)
            method = getattr(unreal_mod, "AutoExposureMethod", None)
            manual = getattr(method, "AEM_MANUAL", None) if method else None
            if manual is not None:
                _set_prop(pps, ("auto_exposure_method",), manual)
            _set_prop(pps, ("override_auto_exposure_bias", "b_override_auto_exposure_bias"), True)
            _set_prop(pps, ("auto_exposure_bias",), 2.0)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"camera_exposure_failed:{exc}")
    notes.append("cam_mid")


def main() -> None:
    import unreal  # type: ignore

    notes: list[str] = []
    errors: list[str] = []
    cfg = _cfg()
    map_path = cfg["map-path"]
    out_dir = Path(cfg["out-dir"] or ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "studio-ready.json"

    out = {
        "schema_version": 1,
        "studio_build": STUDIO_BUILD,
        "tool": "vellum_lookdev_studio_author",
        "ok": False,
        "map_path": map_path,
        "slot_label": f"{PREFIX}Slot_Center",
        "camera_label": f"{PREFIX}Cam_Mid",
        "notes": notes,
        "errors": errors,
        "written_at": _now(),
    }

    try:
        unreal.log(f"Vellum Lookdev Studio author map={map_path}")
        if not _open_or_create_map(unreal, map_path, notes):
            raise RuntimeError("map_open_failed")

        actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        if actor_sub is None:
            raise RuntimeError("no_actor_subsystem")

        _clear_studio_actors(actor_sub, notes)
        _spawn_floor(unreal, actor_sub, notes)
        _spawn_pedestal(unreal, actor_sub, notes)
        _spawn_slot_mark(unreal, actor_sub, notes)
        _spawn_lights(unreal, actor_sub, notes)
        _spawn_camera(unreal, actor_sub, notes)
        _save_map(unreal, map_path, notes, errors)

        out["ok"] = len(errors) == 0
        notes.append("studio_ready")
        unreal.log(f"Vellum Lookdev Studio ok={out['ok']}")
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        notes.append(traceback.format_exc()[-1500:])
        unreal.log_error(f"Vellum Lookdev Studio failed: {exc}")

    result_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    unreal.log(f"Wrote {result_path}")


if __name__ == "__main__":
    main()
