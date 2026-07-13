# Vellum Unreal capture — runs INSIDE Unreal Editor (Python plugin).
#
# Invoked by run_vellum_capture.ps1 via:
#   UnrealEditor-Cmd.exe <uproject> -ExecutePythonScript=<staged script>
#
# Config via env (preferred) or --key=value:
#   VELLUM_ASSET_ID, VELLUM_CONTENT_ROOT, VELLUM_OUT_DIR
#   VELLUM_CAPTURE_STILLS=1 (default) — framed Niagara + SceneCapture2D PNG
#   VELLUM_MAX_SYSTEMS — how many systems to frame/shoot (default 3)
#
# Prefer SceneCapture2D → render target → PNG under UnrealEditor-Cmd.
# HighResShot is fallback only (often empty with -unattended).
# Never call AutomationLibrary.take_high_res_screenshot (AV in FunctionalTesting).


from __future__ import annotations

import json
import math
import os
import sys
import time
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


def _truthy(val: str | None, default: bool = False) -> bool:
    if val is None or val == "":
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def _cfg() -> dict[str, str]:
    cli = _cli_args()
    return {
        "asset-id": os.environ.get("VELLUM_ASSET_ID") or cli.get("asset-id", "fireworks-vol-1-niagara"),
        "content-root": os.environ.get("VELLUM_CONTENT_ROOT") or cli.get("content-root", "/Game/FireworksV1"),
        "out-dir": os.environ.get("VELLUM_OUT_DIR") or cli.get("out-dir", ""),
        "max-systems": os.environ.get("VELLUM_MAX_SYSTEMS") or cli.get("max-systems", "3"),
        "width": os.environ.get("VELLUM_WIDTH") or cli.get("width", "1920"),
        "height": os.environ.get("VELLUM_HEIGHT") or cli.get("height", "1080"),
        "capture-stills": (
            os.environ.get("VELLUM_CAPTURE_STILLS")
            if os.environ.get("VELLUM_CAPTURE_STILLS") is not None
            else cli.get("capture-stills", "1")
        ),
        "sim-seconds": os.environ.get("VELLUM_SIM_SECONDS") or cli.get("sim-seconds", "1.5"),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _list_niagara(unreal_mod, registry, content_root: str) -> list:
    try:
        ar_filter = unreal_mod.ARFilter(
            class_paths=[unreal_mod.TopLevelAssetPath("/Script/Niagara", "NiagaraSystem")],
            package_paths=[content_root],
            recursive_paths=True,
        )
        return list(registry.get_assets(ar_filter) or [])
    except Exception:  # noqa: BLE001
        ar_filter = unreal_mod.ARFilter(
            class_names=["NiagaraSystem"],
            package_paths=[content_root],
            recursive_paths=True,
        )
        return list(registry.get_assets(ar_filter) or [])


def _asset_object_path(asset_data) -> str:
    pkg = str(asset_data.package_name)
    name = str(asset_data.asset_name)
    return f"{pkg}.{name}"


def _pick_systems(assets: list, max_n: int) -> list:
    """Prefer firework-ish names; otherwise alphabetical."""
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
        name = str(a.asset_name)
        low = name.lower()
        score = sum(3 for k in keywords if k in low)
        # Prefer shorter showcase names over utility/test assets.
        if low.startswith("ns_") or low.startswith("fx_"):
            score += 1
        if "test" in low or "tmp" in low:
            score -= 5
        scored.append((score, name.lower(), a))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [t[2] for t in scored[: max(0, max_n)]]


def _editor_world(unreal_mod):
    try:
        return unreal_mod.get_editor_subsystem(unreal_mod.UnrealEditorSubsystem).get_editor_world()
    except Exception:  # noqa: BLE001
        try:
            return unreal_mod.EditorLevelLibrary.get_editor_world()
        except Exception:  # noqa: BLE001
            return None


def _actor_subsystem(unreal_mod):
    try:
        return unreal_mod.get_editor_subsystem(unreal_mod.EditorActorSubsystem)
    except Exception:  # noqa: BLE001
        return None


def _prepare_capture_stage(unreal_mod) -> list[str]:
    """Blank map + dim night lighting so fireworks read clearly."""
    notes: list[str] = []
    try:
        unreal_mod.EditorLoadingAndSavingUtils.new_blank_map(False)
        notes.append("blank_map")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"blank_map_failed:{exc}")

    actor_sub = _actor_subsystem(unreal_mod)
    if not actor_sub:
        notes.append("no_actor_subsystem")
        return notes

    try:
        # Dim key light; fireworks carry their own emissive.
        light = actor_sub.spawn_actor_from_class(
            unreal_mod.DirectionalLight,
            unreal_mod.Vector(0.0, 0.0, 800.0),
            unreal_mod.Rotator(-50.0, 35.0, 0.0),
            True,
        )
        if light and hasattr(light, "set_brightness"):
            try:
                light.set_brightness(0.35)
            except Exception:  # noqa: BLE001
                pass
        notes.append("directional_light")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"light_failed:{exc}")

    try:
        actor_sub.spawn_actor_from_class(
            unreal_mod.SkyLight,
            unreal_mod.Vector(0.0, 0.0, 500.0),
            unreal_mod.Rotator(0.0, 0.0, 0.0),
            True,
        )
        notes.append("sky_light")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"skylight_failed:{exc}")

    # Darker clear color helps particle read.
    world = _editor_world(unreal_mod)
    try:
        unreal_mod.SystemLibrary.execute_console_command(world, "r.DefaultFeature.AutoExposure 0")
        unreal_mod.SystemLibrary.execute_console_command(world, "r.EyeAdaptationQuality 0")
        unreal_mod.SystemLibrary.execute_console_command(world, "r.Tonemapper.Sharpen 1")
    except Exception:  # noqa: BLE001
        pass
    return notes


def _camera_pose_for_actor(unreal_mod, actor, upward_bias: float = 0.45):
    """Return (cam_location, cam_rotation, look_at, radius) for fireworks framing."""
    try:
        origin, extent = actor.get_actor_bounds(True)
    except Exception:  # noqa: BLE001
        origin = actor.get_actor_location()
        extent = unreal_mod.Vector(200.0, 200.0, 400.0)

    radius = max(float(extent.x), float(extent.y), float(extent.z), 200.0)
    # Fireworks expand upward — pull back and look slightly up into the burst.
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
    return cam, rot, look_at, radius


def _set_viewport_camera(unreal_mod, location, rotation) -> None:
    try:
        unreal_mod.EditorLevelLibrary.set_level_viewport_camera_info(location, rotation)
    except Exception:  # noqa: BLE001
        pass


def _get_niagara_component(unreal_mod, actor):
    if actor is None:
        return None
    if hasattr(actor, "niagara_component") and actor.niagara_component:
        return actor.niagara_component
    try:
        return actor.get_component_by_class(unreal_mod.NiagaraComponent)
    except Exception:  # noqa: BLE001
        return None


def _activate_and_advance(unreal_mod, component, sim_seconds: float) -> list[str]:
    notes: list[str] = []
    if component is None:
        return ["no_niagara_component"]
    try:
        if hasattr(component, "set_auto_activate"):
            component.set_auto_activate(True)
        if hasattr(component, "activate_system"):
            component.activate_system(True)
        elif hasattr(component, "activate"):
            component.activate(True)
        notes.append("activated")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"activate_failed:{exc}")

    try:
        dt = 1.0 / 30.0
        ticks = max(1, int(math.ceil(sim_seconds / dt)))
        if hasattr(component, "advance_simulation"):
            component.advance_simulation(ticks, dt)
            notes.append(f"advance_simulation:{ticks}")
        elif hasattr(component, "advance_simulation_by_time"):
            component.advance_simulation_by_time(sim_seconds, dt)
            notes.append(f"advance_by_time:{sim_seconds}")
        else:
            time.sleep(sim_seconds)
            notes.append("sleep_only")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"advance_failed:{exc}")
        time.sleep(min(sim_seconds, 2.0))
    return notes


def _export_render_target(unreal_mod, world, rt, dest: Path) -> tuple[bool, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            dest.unlink()
        except Exception:  # noqa: BLE001
            pass

    # Preferred: RenderingLibrary writes PNG beside the project.
    try:
        unreal_mod.RenderingLibrary.export_render_target(
            world,
            rt,
            str(dest.parent).replace("\\", "/"),
            dest.name,
        )
        if dest.is_file() and dest.stat().st_size > 64:
            return True, "export_render_target"
    except Exception as exc:  # noqa: BLE001
        last = f"export_render_target:{exc}"
    else:
        last = "export_render_target_empty"

    try:
        opts = unreal_mod.ImageWriteOptions()
        opts.set_editor_property("format", unreal_mod.DesiredImageFormat.PNG)
        opts.set_editor_property("overwrite_file", True)
        opts.set_editor_property("async", False)
        unreal_mod.ImageWriteBlueprintLibrary.export_to_disk(
            rt, str(dest).replace("\\", "/"), opts
        )
        time.sleep(0.5)
        if dest.is_file() and dest.stat().st_size > 64:
            return True, "image_write_blueprint"
        last = "image_write_empty"
    except Exception as exc:  # noqa: BLE001
        last = f"image_write:{exc}"
    return False, last


def _capture_scene_to_png(
    unreal_mod,
    subject_actor,
    dest: Path,
    width: int,
    height: int,
) -> tuple[bool, list[str]]:
    """
    Headless-safe still: SceneCapture2D → render target → PNG.
    HighResShot needs a live editor viewport and usually yields nothing under
    UnrealEditor-Cmd -unattended.
    """
    notes: list[str] = []
    world = _editor_world(unreal_mod)
    actor_sub = _actor_subsystem(unreal_mod)
    if world is None or actor_sub is None:
        return False, ["no_world_or_actor_subsystem"]

    cam, rot, _look, _radius = _camera_pose_for_actor(unreal_mod, subject_actor)
    _set_viewport_camera(unreal_mod, cam, rot)  # best-effort; SceneCapture is authoritative

    sc_actor = None
    try:
        sc_actor = actor_sub.spawn_actor_from_class(
            unreal_mod.SceneCapture2D,
            cam,
            rot,
            True,
        )
        if sc_actor is None:
            return False, ["spawn_scenecapture_failed"]

        sc = None
        if hasattr(sc_actor, "capture_component2d") and sc_actor.capture_component2d:
            sc = sc_actor.capture_component2d
        else:
            try:
                sc = sc_actor.get_component_by_class(unreal_mod.SceneCaptureComponent2D)
            except Exception:  # noqa: BLE001
                sc = None
        if sc is None:
            return False, ["no_scenecapture_component"]

        rt = unreal_mod.RenderingLibrary.create_render_target2D(
            world,
            int(width),
            int(height),
            unreal_mod.TextureRenderTargetFormat.RTF_RGBA8,
        )
        if rt is None:
            return False, ["create_rt_failed"]

        sc.set_editor_property("texture_target", rt)
        try:
            sc.set_editor_property("fov_angle", 70.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            sc.set_editor_property("capture_every_frame", False)
            sc.set_editor_property("capture_on_movement", False)
        except Exception:  # noqa: BLE001
            pass
        try:
            sc.set_editor_property(
                "capture_source",
                unreal_mod.SceneCaptureSource.SCS_FINAL_COLOR_LDR,
            )
        except Exception:  # noqa: BLE001
            try:
                sc.capture_source = unreal_mod.SceneCaptureSource.SCS_FINAL_COLOR_LDR
            except Exception:  # noqa: BLE001
                notes.append("capture_source_default")
        try:
            sc.set_editor_property(
                "primitive_render_mode",
                unreal_mod.SceneCapturePrimitiveRenderMode.PRM_RENDER_SCENE_PRIMITIVES,
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            sc.set_editor_property(
                "clear_color",
                unreal_mod.LinearColor(0.01, 0.02, 0.05, 1.0),
            )
        except Exception:  # noqa: BLE001
            pass

        # Ensure transform stuck after spawn.
        try:
            sc_actor.set_actor_location_and_rotation(cam, rot, False, True)
        except Exception:  # noqa: BLE001
            try:
                sc_actor.set_actor_location(cam, False, True)
                sc_actor.set_actor_rotation(rot, True)
            except Exception:  # noqa: BLE001
                pass

        sc.capture_scene()
        notes.append("capture_scene")
        # Second capture after a short settle helps Niagara GPU systems.
        time.sleep(0.25)
        sc.capture_scene()
        notes.append("capture_scene_2")

        ok, how = _export_render_target(unreal_mod, world, rt, dest)
        notes.append(how)
        return ok, notes
    except Exception as exc:  # noqa: BLE001
        notes.append(f"scenecapture_exc:{exc}")
        notes.append(traceback.format_exc()[-600:])
        return False, notes
    finally:
        _destroy_actor(unreal_mod, sc_actor)


def _console_highresshot_fallback(
    unreal_mod, stills_dir: Path, dest: Path, width: int, height: int
) -> tuple[bool, list[str]]:
    notes: list[str] = []
    shot_root = Path(unreal_mod.Paths.project_saved_dir()) / "Screenshots"
    before = set()
    if shot_root.is_dir():
        before = {p.resolve() for p in shot_root.rglob("*.png")}
    world = _editor_world(unreal_mod)
    try:
        unreal_mod.SystemLibrary.execute_console_command(world, f"HighResShot {width}x{height}")
        notes.append("highresshot_console")
        time.sleep(2.5)
    except Exception as exc:  # noqa: BLE001
        return False, [f"highresshot_failed:{exc}"]
    if not shot_root.is_dir():
        return False, notes + ["no_screenshots_dir"]
    new_pngs = sorted(
        (p for p in shot_root.rglob("*.png") if p.resolve() not in before),
        key=lambda p: p.stat().st_mtime,
    )
    if not new_pngs:
        return False, notes + ["highresshot_no_file"]
    dest.write_bytes(new_pngs[-1].read_bytes())
    notes.append("highresshot_copied")
    return True, notes


def _destroy_actor(unreal_mod, actor) -> None:
    if actor is None:
        return
    actor_sub = _actor_subsystem(unreal_mod)
    try:
        if actor_sub and hasattr(actor_sub, "destroy_actor"):
            actor_sub.destroy_actor(actor)
        else:
            actor.destroy_actor()
    except Exception:  # noqa: BLE001
        pass


def _spawn_niagara(unreal_mod, system_asset, location):
    """Spawn a NiagaraActor with the given system. Prefer spawn_from_object."""
    actor_sub = _actor_subsystem(unreal_mod)
    actor = None
    if actor_sub:
        try:
            actor = actor_sub.spawn_actor_from_object(
                system_asset,
                location,
                unreal_mod.Rotator(0.0, 0.0, 0.0),
                True,
            )
        except Exception:  # noqa: BLE001
            actor = None
        if actor is None:
            try:
                actor = actor_sub.spawn_actor_from_class(
                    unreal_mod.NiagaraActor,
                    location,
                    unreal_mod.Rotator(0.0, 0.0, 0.0),
                    True,
                )
            except Exception:  # noqa: BLE001
                actor = None
    if actor is None:
        try:
            actor = unreal_mod.EditorLevelLibrary.spawn_actor_from_class(
                unreal_mod.NiagaraActor,
                location,
                unreal_mod.Rotator(0.0, 0.0, 0.0),
            )
        except Exception:  # noqa: BLE001
            return None

    comp = _get_niagara_component(unreal_mod, actor)
    if comp is not None and system_asset is not None:
        try:
            if hasattr(comp, "set_asset"):
                comp.set_asset(system_asset)
            elif hasattr(comp, "set_editor_property"):
                comp.set_editor_property("asset", system_asset)
        except Exception:  # noqa: BLE001
            pass
    return actor


def _capture_framed_stills(
    unreal_mod,
    assets: list,
    stills_dir: Path,
    asset_id: str,
    max_systems: int,
    width: int,
    height: int,
    sim_seconds: float,
) -> tuple[list[dict], list[str]]:
    stills: list[dict[str, str]] = []
    errors: list[str] = []

    stage_notes = _prepare_capture_stage(unreal_mod)
    unreal_mod.log(f"Vellum capture stage: {', '.join(stage_notes)}")

    picked = _pick_systems(assets, max_systems)
    if not picked:
        errors.append("no_systems_to_frame")
        return stills, errors

    for idx, asset_data in enumerate(picked):
        name = str(asset_data.asset_name)
        obj_path = _asset_object_path(asset_data)
        unreal_mod.log(f"Vellum capture framing [{idx + 1}/{len(picked)}] {obj_path}")
        actor = None
        try:
            system_asset = unreal_mod.EditorAssetLibrary.load_asset(obj_path)
            if system_asset is None:
                errors.append(f"load_failed:{name}")
                continue

            loc = unreal_mod.Vector(float(idx) * 2500.0, 0.0, 0.0)
            actor = _spawn_niagara(unreal_mod, system_asset, loc)
            if actor is None:
                errors.append(f"spawn_failed:{name}")
                continue

            comp = _get_niagara_component(unreal_mod, actor)
            adv_notes = _activate_and_advance(unreal_mod, comp, sim_seconds)
            unreal_mod.log(f"Vellum capture sim {name}: {', '.join(adv_notes)}")

            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:80]
            dest = stills_dir / f"{asset_id}-{safe}-{stamp}.png"

            ok, shot_notes = _capture_scene_to_png(unreal_mod, actor, dest, width, height)
            unreal_mod.log(f"Vellum capture scenecapture {name}: {', '.join(shot_notes)}")

            if not ok:
                ok2, fb_notes = _console_highresshot_fallback(
                    unreal_mod, stills_dir, dest, width, height
                )
                shot_notes.extend(fb_notes)
                unreal_mod.log(f"Vellum capture fallback {name}: {', '.join(fb_notes)}")
                ok = ok2

            if not ok or not dest.is_file():
                errors.append(f"no_png:{name}:{'|'.join(shot_notes)}")
                continue

            stills.append(
                {
                    "path": str(dest),
                    "kind": "niagara-render",
                    "system": name,
                    "object_path": obj_path,
                    "method": "|".join(shot_notes),
                }
            )
            unreal_mod.log(f"Vellum capture saved still {dest} bytes={dest.stat().st_size}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"frame:{name}:{exc}")
            errors.append(traceback.format_exc()[-800:])
            unreal_mod.log_error(f"Vellum capture frame failed for {name}: {exc}")
        finally:
            _destroy_actor(unreal_mod, actor)

    return stills, errors


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
    width = int(args["width"])
    height = int(args["height"])
    sim_seconds = float(args["sim-seconds"])
    want_stills = _truthy(args["capture-stills"], default=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    stills_dir = out_dir / "stills"
    stills_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"

    systems: list[dict[str, str]] = []
    stills: list[dict[str, str]] = []
    capture_errors: list[str] = []
    assets: list = []

    unreal.log(
        f"Vellum capture start asset_id={asset_id} content_root={content_root} "
        f"out_dir={out_dir} capture_stills={want_stills} max_systems={max_systems}"
    )

    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        try:
            registry.scan_paths_synchronous([content_root], True)
        except Exception:  # noqa: BLE001
            pass
        assets = _list_niagara(unreal, registry, content_root)
        # Inventory lists the same preferred subset we might shoot, plus count of all.
        for a in _pick_systems(assets, max(max_systems, 12)):
            systems.append(
                {
                    "object_path": _asset_object_path(a),
                    "package_name": str(a.package_name),
                    "asset_name": str(a.asset_name),
                }
            )
    except Exception as exc:  # noqa: BLE001
        capture_errors.append(f"inventory:{exc}")
        capture_errors.append(traceback.format_exc()[-1200:])
        unreal.log_error(f"Vellum capture inventory failed: {exc}")

    # Persist inventory before any framing/screenshot work.
    manifest = {
        "schema_version": 1,
        "tool": "vellum_capture",
        "mode": "framed_niagara_spawn",
        "asset_id": asset_id,
        "content_root": content_root,
        "created_at": _now(),
        "engine": unreal.SystemLibrary.get_engine_version(),
        "project_dir": unreal.Paths.project_dir(),
        "niagara_systems_found": len(assets),
        "niagara_systems": systems,
        "stills": stills,
        "errors": list(capture_errors),
        "ok": True,
        "stills_attempted": False,
    }
    _write_manifest(manifest_path, manifest)
    unreal.log(
        f"Vellum capture wrote inventory manifest {manifest_path} "
        f"systems_found={len(assets)} listed={len(systems)}"
    )

    if want_stills:
        more_stills, more_errors = _capture_framed_stills(
            unreal,
            assets,
            stills_dir,
            asset_id,
            max_systems,
            width,
            height,
            sim_seconds,
        )
        stills.extend(more_stills)
        capture_errors.extend(more_errors)
        manifest["stills"] = stills
        manifest["errors"] = capture_errors
        manifest["stills_attempted"] = True
        _write_manifest(manifest_path, manifest)
        unreal.log(
            f"Vellum capture stills done stills={len(stills)} errors={len(more_errors)}"
        )
    else:
        capture_errors.append("stills_skipped")
        manifest["errors"] = capture_errors
        _write_manifest(manifest_path, manifest)
        unreal.log("Vellum capture skipped stills")

    unreal.log(
        f"Vellum capture complete systems={len(assets)} stills={len(stills)} "
        f"errors={len(capture_errors)}"
    )


if __name__ == "__main__":
    main()
