# Vellum Unreal capture — Phase B author (MRQ + Sequencer).
# Runs inside Unreal Editor via -ExecutePythonScript.
# Creates/saves: capture map, Level Sequence, MoviePipeline config.
# Does NOT render; PowerShell cmdline MRQ does that (docs/ue-mrq-capture.md §12.3).
#
# Job JSON (VELLUM_JOB_JSON):
#   system_object_path, system_name, map_path, sequence_path, config_path,
#   output_dir, width, height, frame_count, frame_rate

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path


ACTOR_PREFIX = "VellumMRQ_"
DEFAULT_FRAMES = 120
DEFAULT_FPS = 30


def _job_path() -> Path:
    raw = os.environ.get("VELLUM_JOB_JSON") or ""
    if not raw:
        raise FileNotFoundError("VELLUM_JOB_JSON not set")
    return Path(raw)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _actor_subsystem(unreal_mod):
    try:
        return unreal_mod.get_editor_subsystem(unreal_mod.EditorActorSubsystem)
    except Exception:  # noqa: BLE001
        return None


def _ensure_dir_asset(unreal_mod, package_path: str) -> None:
    # package_path like /Game/Vellum/Sequences — create folders if missing
    parts = [p for p in package_path.strip("/").split("/") if p]
    if not parts or parts[0] != "Game":
        return
    cur = "/Game"
    for part in parts[1:]:
        nxt = f"{cur}/{part}"
        try:
            if not unreal_mod.EditorAssetLibrary.does_directory_exist(nxt):
                unreal_mod.EditorAssetLibrary.make_directory(nxt)
        except Exception:  # noqa: BLE001
            pass
        cur = nxt


def _load_or_create_level_sequence(unreal_mod, package_path: str, asset_name: str):
    full = f"{package_path}/{asset_name}"
    _ensure_dir_asset(unreal_mod, package_path)
    if unreal_mod.EditorAssetLibrary.does_asset_exist(full):
        return unreal_mod.EditorAssetLibrary.load_asset(full)
    tools = unreal_mod.AssetToolsHelpers.get_asset_tools()
    return tools.create_asset(
        asset_name,
        package_path,
        unreal_mod.LevelSequence,
        unreal_mod.LevelSequenceFactoryNew(),
    )


def _load_or_create_mrq_config(unreal_mod, package_path: str, asset_name: str):
    full = f"{package_path}/{asset_name}"
    _ensure_dir_asset(unreal_mod, package_path)
    cfg_cls = getattr(unreal_mod, "MoviePipelinePrimaryConfig", None) or getattr(
        unreal_mod, "MoviePipelineMasterConfig", None
    )
    if cfg_cls is None:
        raise RuntimeError("MoviePipelinePrimaryConfig/MasterConfig missing — enable Movie Render Queue plugin")
    if unreal_mod.EditorAssetLibrary.does_asset_exist(full):
        return unreal_mod.EditorAssetLibrary.load_asset(full)
    # Create empty config asset via factory if available; else construct and save.
    tools = unreal_mod.AssetToolsHelpers.get_asset_tools()
    factory = getattr(unreal_mod, "MoviePipelinePrimaryConfigFactory", None)
    if factory is not None:
        return tools.create_asset(asset_name, package_path, cfg_cls, factory())
    # Fallback: duplicate engine default if present, else new UObject saved via asset tools hack
    config = unreal_mod.new_object(cfg_cls)
    # Save via create_asset with None factory often fails; use AssetTools.create_asset with factory None
    try:
        saved = tools.create_asset(asset_name, package_path, cfg_cls, None)
        if saved is not None:
            return saved
    except Exception:  # noqa: BLE001
        pass
    # Last resort: write into an existing package by renaming a DataAsset path — require plugin factory.
    raise RuntimeError(
        f"could_not_create_mrq_config:{full} — ensure Movie Render Queue + Sequencer Scripting plugins"
    )


def _open_or_create_map(unreal_mod, map_path: str, notes: list[str]) -> bool:
    try:
        if unreal_mod.EditorAssetLibrary.does_asset_exist(map_path):
            ok = unreal_mod.EditorLoadingAndSavingUtils.load_map(map_path)
            notes.append(f"load_map:{ok}")
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
            # Alternate API
            unreal_mod.EditorLevelLibrary.new_blank_map(False)
            notes.append("new_blank_map")
            return True
        except Exception as exc2:  # noqa: BLE001
            notes.append(f"new_blank_map_failed:{exc2}")
            return False


def _clear_vellum_actors(unreal_mod, actor_sub, notes: list[str]) -> None:
    if actor_sub is None:
        return
    removed = 0
    try:
        for actor in actor_sub.get_all_level_actors():
            try:
                label = actor.get_actor_label()
            except Exception:  # noqa: BLE001
                continue
            if label.startswith(ACTOR_PREFIX):
                actor_sub.destroy_actor(actor)
                removed += 1
    except Exception as exc:  # noqa: BLE001
        notes.append(f"clear_actors_failed:{exc}")
    notes.append(f"cleared_actors:{removed}")


def _spawn_lights(unreal_mod, actor_sub, notes: list[str]) -> None:
    try:
        light = actor_sub.spawn_actor_from_class(
            unreal_mod.DirectionalLight,
            unreal_mod.Vector(0.0, 0.0, 600.0),
            unreal_mod.Rotator(-50.0, 30.0, 0.0),
            True,
        )
        if light:
            light.set_actor_label(f"{ACTOR_PREFIX}Light")
        notes.append("directional_light")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"light_failed:{exc}")


def _spawn_niagara(unreal_mod, actor_sub, system_asset, notes: list[str]):
    loc = unreal_mod.Vector(0.0, 0.0, 0.0)
    actor = None
    try:
        actor = actor_sub.spawn_actor_from_object(system_asset, loc, unreal_mod.Rotator(0, 0, 0), True)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"spawn_from_object_failed:{exc}")
    if actor is None:
        try:
            actor = actor_sub.spawn_actor_from_class(
                unreal_mod.NiagaraActor, loc, unreal_mod.Rotator(0, 0, 0), True
            )
            comp = actor.niagara_component if actor else None
            if comp is None and actor is not None:
                comp = actor.get_component_by_class(unreal_mod.NiagaraComponent)
            if comp is not None:
                try:
                    comp.set_asset(system_asset)
                except Exception:  # noqa: BLE001
                    comp.set_editor_property("asset", system_asset)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"spawn_niagara_actor_failed:{exc}")
            return None
    if actor is not None:
        try:
            actor.set_actor_label(f"{ACTOR_PREFIX}System")
        except Exception:  # noqa: BLE001
            pass
        comp = getattr(actor, "niagara_component", None)
        if comp is None:
            try:
                comp = actor.get_component_by_class(unreal_mod.NiagaraComponent)
            except Exception:  # noqa: BLE001
                comp = None
        if comp is not None:
            for prop, val in (("auto_activate", True), ("AutoActivate", True)):
                try:
                    comp.set_editor_property(prop, val)
                    break
                except Exception:  # noqa: BLE001
                    continue
            try:
                comp.activate(True)
            except Exception:  # noqa: BLE001
                pass
            notes.append("niagara_auto_activate")
    return actor


def _camera_pose(unreal_mod, actor):
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
        float(origin.z) + dist * 0.45,
    )
    look = unreal_mod.Vector(float(origin.x), float(origin.y), float(origin.z) + radius * 1.2)
    try:
        rot = unreal_mod.MathLibrary.find_look_at_rotation(cam, look)
    except Exception:  # noqa: BLE001
        rot = unreal_mod.Rotator(-25.0, 40.0, 0.0)
    return cam, rot


def _list_root_tracks(unreal_mod, sequence):
    ext = unreal_mod.MovieSceneSequenceExtensions
    for getter in (
        lambda: sequence.get_tracks(),
        lambda: ext.get_tracks(sequence),
        lambda: sequence.get_master_tracks(),
        lambda: ext.get_master_tracks(sequence),
    ):
        try:
            tracks = getter()
            if tracks is not None:
                return list(tracks)
        except Exception:  # noqa: BLE001
            continue
    return []


def _remove_root_track(unreal_mod, sequence, track) -> bool:
    ext = unreal_mod.MovieSceneSequenceExtensions
    for remover in (
        lambda: sequence.remove_track(track),
        lambda: ext.remove_track(sequence, track),
        lambda: sequence.remove_master_track(track),
        lambda: ext.remove_master_track(sequence, track),
    ):
        try:
            remover()
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _add_root_track(unreal_mod, sequence, track_type):
    """UE 5.2+ renamed add_master_track → add_track; 5.8 removed the old alias."""
    ext = unreal_mod.MovieSceneSequenceExtensions
    errors: list[str] = []
    for adder, tag in (
        (lambda: sequence.add_track(track_type), "add_track"),
        (lambda: ext.add_track(sequence, track_type), "ext.add_track"),
        (lambda: sequence.add_master_track(track_type), "add_master_track"),
        (lambda: ext.add_master_track(sequence, track_type), "ext.add_master_track"),
    ):
        try:
            track = adder()
            if track is not None:
                return track, tag
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{tag}:{exc}")
    raise RuntimeError("add_root_track_failed:" + ";".join(errors[-4:]))


def _configure_sequence(unreal_mod, sequence, camera_actor, frame_count: int, fps: int, notes: list[str]) -> None:
    try:
        sequence.set_playback_start(0)
        sequence.set_playback_end(int(frame_count))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"playback_range_failed:{exc}")
    try:
        unreal_mod.MovieSceneSequenceExtensions.set_display_rate(
            sequence, unreal_mod.FrameRate(int(fps), 1)
        )
        notes.append(f"display_rate_{fps}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"display_rate_failed:{exc}")

    # Clear old root/master tracks if re-authoring
    removed = 0
    for track in _list_root_tracks(unreal_mod, sequence):
        if _remove_root_track(unreal_mod, sequence, track):
            removed += 1
    notes.append(f"cleared_root_tracks:{removed}")

    cam_binding = None
    try:
        cam_binding = sequence.add_possessable(camera_actor)
        notes.append("camera_possessable")
    except Exception as exc:  # noqa: BLE001
        try:
            cam_binding = unreal_mod.MovieSceneSequenceExtensions.add_possessable(sequence, camera_actor)
            notes.append("camera_possessable_ext")
        except Exception as exc2:  # noqa: BLE001
            notes.append(f"camera_possessable_failed:{exc}/{exc2}")
            raise

    cut_track, add_tag = _add_root_track(unreal_mod, sequence, unreal_mod.MovieSceneCameraCutTrack)
    notes.append(f"camera_cut_track:{add_tag}")
    section = cut_track.add_section()
    try:
        section.set_range(0, int(frame_count))
    except Exception:  # noqa: BLE001
        try:
            section.set_start_frame_bounded(0, True)
            section.set_end_frame_bounded(int(frame_count), True)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"cut_range_failed:{exc}")
    try:
        binding_id = sequence.get_binding_id(cam_binding)
        section.set_camera_binding_id(binding_id)
        notes.append("camera_cut_bound")
    except Exception:
        try:
            binding_id = unreal_mod.MovieSceneSequenceExtensions.get_portable_binding_id(
                sequence, sequence, cam_binding
            )
            section.set_editor_property("camera_binding_id", binding_id)
            notes.append("camera_cut_bound_portable")
        except Exception as exc:  # noqa: BLE001
            # Forum-proven path for 5.x: bind via Guid on MovieSceneObjectBindingID
            try:
                binding_id = unreal_mod.MovieSceneObjectBindingID()
                binding_id.set_editor_property("guid", cam_binding.get_id())
                section.set_editor_property("camera_binding_id", binding_id)
                notes.append("camera_cut_bound_guid")
            except Exception as exc2:  # noqa: BLE001
                notes.append(f"camera_cut_bind_failed:{exc}/{exc2}")
                raise


def _add_setting(config, unreal_mod, class_names: tuple[str, ...], notes: list[str], tag: str):
    for name in class_names:
        cls = getattr(unreal_mod, name, None)
        if cls is None:
            continue
        try:
            config.find_or_add_setting_by_class(cls)
            notes.append(f"{tag}:{name}")
            return True
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{tag}_failed:{name}:{exc}")
    notes.append(f"{tag}_missing:{','.join(class_names)}")
    return False


def _configure_mrq_config(unreal_mod, config, output_dir: str, width: int, height: int, notes: list[str]) -> None:
    out_cls = unreal_mod.MoviePipelineOutputSetting
    out = config.find_or_add_setting_by_class(out_cls)
    try:
        out.output_directory = unreal_mod.DirectoryPath(output_dir)
    except Exception:  # noqa: BLE001
        out.set_editor_property("output_directory", unreal_mod.DirectoryPath(output_dir))
    try:
        out.output_resolution = unreal_mod.IntPoint(int(width), int(height))
    except Exception:  # noqa: BLE001
        out.set_editor_property("output_resolution", unreal_mod.IntPoint(int(width), int(height)))
    try:
        out.file_name_format = "{sequence_name}.{frame_number}"
    except Exception:  # noqa: BLE001
        try:
            out.set_editor_property("file_name_format", "{sequence_name}.{frame_number}")
        except Exception:  # noqa: BLE001
            pass
    # Flush each frame to disk immediately (helps diagnose mid-run failures)
    for prop, val in (
        ("flush_disk_writes_per_frame", True),
        ("b_flush_disk_writes_per_frame", True),
    ):
        try:
            out.set_editor_property(prop, val)
            break
        except Exception:  # noqa: BLE001
            continue
    notes.append(f"mrq_output:{output_dir}:{width}x{height}")

    # Without a deferred/render pass, MRQ can exit 0 and write ZERO frames.
    _add_setting(
        config,
        unreal_mod,
        (
            "MoviePipelineDeferredPassBase",
            "MoviePipelineDeferredPass_PathTracer",
        ),
        notes,
        "mrq_deferred_pass",
    )
    _add_setting(
        config,
        unreal_mod,
        (
            "MoviePipelineImageSequenceOutput_PNG",
            "MoviePipelineImageSequenceOutputPNG",
        ),
        notes,
        "mrq_png",
    )
    _add_setting(
        config,
        unreal_mod,
        ("MoviePipelineAntiAliasingSetting",),
        notes,
        "mrq_aa",
    )

    # Disable burn-in if present
    burn = getattr(unreal_mod, "MoviePipelineBurnInSetting", None)
    if burn is not None:
        try:
            setting = config.find_or_add_setting_by_class(burn)
            setting.set_editor_property("burn_in_class", unreal_mod.SoftClassPath())
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    import unreal  # type: ignore

    notes: list[str] = []
    errors: list[str] = []
    ok = False
    result_path = Path()
    out = {
        "schema_version": 1,
        "tool": "vellum_capture_mrq_author",
        "ok": False,
        "notes": notes,
        "errors": errors,
    }

    try:
        job_path = _job_path()
        result_path = job_path.parent / "author-result.json"
        job = json.loads(job_path.read_text(encoding="utf-8"))
        system_object_path = str(job.get("system_object_path") or "")
        system_name = str(job.get("system_name") or "system")
        map_path = str(job.get("map_path") or "/Game/Vellum/Maps/VellumNiagaraCapture")
        seq_pkg = str(job.get("sequence_package") or "/Game/Vellum/Sequences")
        cfg_pkg = str(job.get("config_package") or "/Game/Vellum/MRQ")
        width = int(job.get("width") or 1920)
        height = int(job.get("height") or 1080)
        frame_count = int(job.get("frame_count") or DEFAULT_FRAMES)
        frame_rate = int(job.get("frame_rate") or DEFAULT_FPS)
        output_dir = str(job.get("output_dir") or "")
        if not system_object_path:
            raise ValueError("missing system_object_path")
        if not output_dir:
            raise ValueError("missing output_dir")

        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in system_name) or "system"
        seq_name = f"LS_{safe}"
        cfg_name = f"MRQ_{safe}"

        unreal.log(f"Vellum MRQ author start system={system_object_path}")

        if not _open_or_create_map(unreal, map_path, notes):
            raise RuntimeError("map_open_failed")

        actor_sub = _actor_subsystem(unreal)
        if actor_sub is None:
            raise RuntimeError("no_actor_subsystem")
        _clear_vellum_actors(unreal, actor_sub, notes)
        _spawn_lights(unreal, actor_sub, notes)

        system_asset = unreal.EditorAssetLibrary.load_asset(system_object_path)
        if system_asset is None:
            raise RuntimeError(f"load_failed:{system_object_path}")

        niagara = _spawn_niagara(unreal, actor_sub, system_asset, notes)
        if niagara is None:
            raise RuntimeError("spawn_niagara_failed")

        cam_loc, cam_rot = _camera_pose(unreal, niagara)
        camera = actor_sub.spawn_actor_from_class(unreal.CineCameraActor, cam_loc, cam_rot, True)
        if camera is None:
            camera = actor_sub.spawn_actor_from_class(unreal.CameraActor, cam_loc, cam_rot, True)
        if camera is None:
            raise RuntimeError("spawn_camera_failed")
        camera.set_actor_label(f"{ACTOR_PREFIX}Camera")
        notes.append("camera_spawned")

        sequence = _load_or_create_level_sequence(unreal, seq_pkg, seq_name)
        if sequence is None:
            raise RuntimeError("sequence_create_failed")
        _configure_sequence(unreal, sequence, camera, frame_count, frame_rate, notes)

        config = _load_or_create_mrq_config(unreal, cfg_pkg, cfg_name)
        _configure_mrq_config(unreal, config, output_dir.replace("\\", "/"), width, height, notes)

        # Persist
        try:
            unreal.EditorAssetLibrary.save_asset(f"{seq_pkg}/{seq_name}")
            notes.append("saved_sequence")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"save_sequence_failed:{exc}")
        try:
            unreal.EditorAssetLibrary.save_asset(f"{cfg_pkg}/{cfg_name}")
            notes.append("saved_config")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"save_config_failed:{exc}")
        try:
            world = unreal.EditorLevelLibrary.get_editor_world()
            unreal.EditorLoadingAndSavingUtils.save_map(world, map_path)
            notes.append("saved_map")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"save_map_failed:{exc}")
            try:
                unreal.EditorLevelLibrary.save_current_level()
                notes.append("save_current_level")
            except Exception as exc2:  # noqa: BLE001
                errors.append(f"save_level_failed:{exc2}")
        try:
            unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
            notes.append("save_dirty_packages")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"save_dirty_failed:{exc}")

        out.update(
            {
                "ok": True,
                "system_name": system_name,
                "system_object_path": system_object_path,
                "map_path": map_path,
                "sequence_path": f"{seq_pkg}/{seq_name}.{seq_name}",
                "sequence_asset": f"{seq_pkg}/{seq_name}",
                "config_path": f"{cfg_pkg}/{cfg_name}.{cfg_name}",
                "config_asset": f"{cfg_pkg}/{cfg_name}",
                "output_dir": output_dir.replace("\\", "/"),
                "frame_count": frame_count,
                "frame_rate": frame_rate,
                "width": width,
                "height": height,
            }
        )
        ok = True
        unreal.log(f"Vellum MRQ author ok sequence={seq_name} config={cfg_name}")
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        errors.append(traceback.format_exc()[-1500:])
        try:
            unreal.log_error(f"Vellum MRQ author failed: {exc}")
        except Exception:  # noqa: BLE001
            pass
        ok = False

    out["ok"] = ok
    out["notes"] = notes
    out["errors"] = errors
    if not result_path:
        result_path = Path(os.environ.get("VELLUM_OUT_DIR") or ".") / "author-result.json"
    _write_json(Path(result_path), out)


if __name__ == "__main__":
    main()
