# Vellum Unreal capture — Phase B author (MRQ + Sequencer).
# Runs inside Unreal Editor via -ExecutePythonScript.
# Creates/saves: capture map, Level Sequence (camera cut + Niagara life cycle),
# MoviePipeline config with deferred pass + GPU warm-up.
#
# Black stills (peak_rgb=0) happen when Niagara is left as a loose level actor
# without a Sequencer life-cycle track and/or MRQ GPU warm-up. Follow Epic’s
# Niagara-in-Sequencer + MRQ AntiAliasing warm-up contract.

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path


ACTOR_PREFIX = "VellumMRQ_"
DEFAULT_FRAMES = 120
DEFAULT_FPS = 30
# Frames before playback start used as camera-cut warm-up head.
WARMUP_FRAMES = 60


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
        # Always rebuild from scratch — stale configs caused silent black renders.
        try:
            unreal_mod.EditorAssetLibrary.delete_asset(full)
        except Exception:  # noqa: BLE001
            pass
    tools = unreal_mod.AssetToolsHelpers.get_asset_tools()
    factory = getattr(unreal_mod, "MoviePipelinePrimaryConfigFactory", None)
    if factory is not None:
        created = tools.create_asset(asset_name, package_path, cfg_cls, factory())
        if created is not None:
            return created
    try:
        saved = tools.create_asset(asset_name, package_path, cfg_cls, None)
        if saved is not None:
            return saved
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError(
        f"could_not_create_mrq_config:{full} — ensure Movie Render Queue + Sequencer Scripting plugins"
    )


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


def _set_prop(obj, names: tuple[str, ...], value) -> bool:
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


def _spawn(unreal_mod, actor_sub, actor_class=None, obj=None, loc=None, rot=None, label: str = "", notes: list[str] | None = None):
    """Spawn a *persistent* level actor. The 4th arg to spawn_* is transient — never True."""
    if loc is None:
        loc = unreal_mod.Vector(0.0, 0.0, 0.0)
    if rot is None:
        rot = unreal_mod.Rotator(0.0, 0.0, 0.0)
    actor = None
    if obj is not None:
        actor = actor_sub.spawn_actor_from_object(obj, loc, rot, False)
    elif actor_class is not None:
        actor = actor_sub.spawn_actor_from_class(actor_class, loc, rot, False)
    if actor is None:
        return None
    if label:
        try:
            actor.set_actor_label(label)
        except Exception:  # noqa: BLE001
            pass
    # Ensure it participates in level save (transient was the black-frame root cause).
    try:
        if bool(actor.is_editor_only_actor()):
            if notes is not None:
                notes.append(f"warn_editor_only:{label or actor.get_name()}")
    except Exception:  # noqa: BLE001
        pass
    try:
        actor.set_is_temporarily_hidden_in_editor(False)
    except Exception:  # noqa: BLE001
        pass
    return actor


def _count_vellum_actors(actor_sub) -> int:
    n = 0
    try:
        for actor in actor_sub.get_all_level_actors():
            try:
                if actor.get_actor_label().startswith(ACTOR_PREFIX):
                    n += 1
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return n
    return n


def _spawn_lights(unreal_mod, actor_sub, notes: list[str]) -> None:
    # Fireworks are mostly emissive; lights keep non-emissive fill from pure black void.
    try:
        light = _spawn(
            unreal_mod,
            actor_sub,
            actor_class=unreal_mod.DirectionalLight,
            loc=unreal_mod.Vector(0.0, 0.0, 1200.0),
            rot=unreal_mod.Rotator(-55.0, 35.0, 0.0),
            label=f"{ACTOR_PREFIX}Light",
            notes=notes,
        )
        if light:
            comp = light.get_component_by_class(unreal_mod.DirectionalLightComponent)
            if comp is not None:
                _set_prop(comp, ("intensity",), 8.0)
                _set_prop(comp, ("indirect_lighting_intensity",), 1.0)
        notes.append("directional_light")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"light_failed:{exc}")
    try:
        sky = _spawn(
            unreal_mod,
            actor_sub,
            actor_class=unreal_mod.SkyLight,
            loc=unreal_mod.Vector(0.0, 0.0, 500.0),
            label=f"{ACTOR_PREFIX}Sky",
            notes=notes,
        )
        if sky:
            comp = sky.get_component_by_class(unreal_mod.SkyLightComponent)
            if comp is not None:
                _set_prop(comp, ("intensity",), 1.5)
                _set_prop(comp, ("real_time_capture", "b_real_time_capture"), True)
        notes.append("sky_light")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"sky_failed:{exc}")


def _niagara_component(unreal_mod, actor):
    comp = getattr(actor, "niagara_component", None)
    if comp is not None:
        return comp
    try:
        return actor.get_component_by_class(unreal_mod.NiagaraComponent)
    except Exception:  # noqa: BLE001
        return None


def _spawn_niagara(unreal_mod, actor_sub, system_asset, notes: list[str]):
    loc = unreal_mod.Vector(0.0, 0.0, 0.0)
    actor = None
    try:
        actor = _spawn(
            unreal_mod,
            actor_sub,
            obj=system_asset,
            loc=loc,
            label=f"{ACTOR_PREFIX}System",
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001
        notes.append(f"spawn_from_object_failed:{exc}")
    if actor is None:
        try:
            actor = _spawn(
                unreal_mod,
                actor_sub,
                actor_class=unreal_mod.NiagaraActor,
                loc=loc,
                label=f"{ACTOR_PREFIX}System",
                notes=notes,
            )
            comp = _niagara_component(unreal_mod, actor) if actor else None
            if comp is not None:
                try:
                    comp.set_asset(system_asset)
                except Exception:  # noqa: BLE001
                    _set_prop(comp, ("asset",), system_asset)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"spawn_niagara_actor_failed:{exc}")
            return None
    if actor is None:
        return None

    comp = _niagara_component(unreal_mod, actor)
    if comp is None:
        notes.append("niagara_component_missing")
        return actor

    _set_prop(comp, ("auto_activate", "b_auto_activate"), True)
    _set_prop(comp, ("auto_destroy", "b_auto_destroy"), False)
    _set_prop(comp, ("force_solo", "b_force_solo"), True)
    try:
        comp.set_rendering_enabled(True)
    except Exception:  # noqa: BLE001
        pass
    try:
        if hasattr(comp, "set_age_update_mode"):
            mode = getattr(unreal_mod, "NiagaraAgeUpdateMode", None)
            desired = getattr(mode, "DESIRED_AGE", None) if mode else None
            if desired is not None:
                comp.set_age_update_mode(desired)
                comp.set_desired_age(1.0)
        comp.reset_system()
        comp.activate(True)
        notes.append("niagara_activated")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"niagara_activate_failed:{exc}")
    return actor


def _fireworks_camera_pose(unreal_mod):
    """Fixed aerial lookdev framing — do not trust empty pre-sim Niagara bounds."""
    # Origin at system spawn; shells bloom upward into Z+.
    look = unreal_mod.Vector(0.0, 0.0, 700.0)
    cam = unreal_mod.Vector(-2200.0, -1600.0, 500.0)
    try:
        rot = unreal_mod.MathLibrary.find_look_at_rotation(cam, look)
    except Exception:  # noqa: BLE001
        rot = unreal_mod.Rotator(-15.0, 36.0, 0.0)
    return cam, rot


def _configure_cine_camera(unreal_mod, camera, notes: list[str]) -> None:
    try:
        cine = camera.get_cine_camera_component()
    except Exception:  # noqa: BLE001
        cine = None
    if cine is None:
        try:
            cine = camera.get_component_by_class(unreal_mod.CineCameraComponent)
        except Exception:  # noqa: BLE001
            cine = None
    if cine is None:
        notes.append("cine_component_missing")
        return

    _set_prop(cine, ("current_focal_length",), 35.0)
    _set_prop(cine, ("current_aperture",), 2.8)
    try:
        cine.set_field_of_view(55.0)
    except Exception:  # noqa: BLE001
        pass

    # Manual exposure — auto-exposure on an empty night sky will crush fireworks.
    try:
        pps = cine.post_process_settings
        _set_prop(pps, ("override_auto_exposure_method", "b_override_auto_exposure_method"), True)
        method = getattr(unreal_mod, "AutoExposureMethod", None)
        manual = getattr(method, "AEM_MANUAL", None) if method else None
        if manual is not None:
            _set_prop(pps, ("auto_exposure_method",), manual)
        _set_prop(pps, ("override_auto_exposure_bias", "b_override_auto_exposure_bias"), True)
        _set_prop(pps, ("auto_exposure_bias",), 2.0)
        _set_prop(pps, ("override_auto_exposure_min_brightness", "b_override_auto_exposure_min_brightness"), True)
        _set_prop(pps, ("auto_exposure_min_brightness",), 1.0)
        _set_prop(pps, ("override_auto_exposure_max_brightness", "b_override_auto_exposure_max_brightness"), True)
        _set_prop(pps, ("auto_exposure_max_brightness",), 1.0)
        notes.append("cine_manual_exposure")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"cine_exposure_failed:{exc}")


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


def _add_possessable(unreal_mod, sequence, actor, notes: list[str], tag: str):
    try:
        binding = sequence.add_possessable(actor)
        notes.append(f"{tag}_possessable")
        return binding
    except Exception as exc:  # noqa: BLE001
        try:
            binding = unreal_mod.MovieSceneSequenceExtensions.add_possessable(sequence, actor)
            notes.append(f"{tag}_possessable_ext")
            return binding
        except Exception as exc2:  # noqa: BLE001
            notes.append(f"{tag}_possessable_failed:{exc}/{exc2}")
            raise


def _set_section_range(section, start: int, end: int, notes: list[str], tag: str) -> None:
    try:
        section.set_range(int(start), int(end))
        notes.append(f"{tag}_range:{start}:{end}")
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        section.set_start_frame_bounded(int(start), True)
        section.set_end_frame_bounded(int(end), True)
        notes.append(f"{tag}_range_bounded:{start}:{end}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"{tag}_range_failed:{exc}")


def _bind_camera_cut(unreal_mod, sequence, section, cam_binding, notes: list[str]) -> None:
    try:
        binding_id = sequence.get_binding_id(cam_binding)
        section.set_camera_binding_id(binding_id)
        notes.append("camera_cut_bound")
        return
    except Exception:
        pass
    try:
        binding_id = unreal_mod.MovieSceneSequenceExtensions.get_portable_binding_id(
            sequence, sequence, cam_binding
        )
        section.set_editor_property("camera_binding_id", binding_id)
        notes.append("camera_cut_bound_portable")
        return
    except Exception as exc:  # noqa: BLE001
        try:
            binding_id = unreal_mod.MovieSceneObjectBindingID()
            binding_id.set_editor_property("guid", cam_binding.get_id())
            section.set_editor_property("camera_binding_id", binding_id)
            notes.append("camera_cut_bound_guid")
        except Exception as exc2:  # noqa: BLE001
            notes.append(f"camera_cut_bind_failed:{exc}/{exc2}")
            raise


def _add_niagara_lifecycle(unreal_mod, binding, frame_count: int, notes: list[str]) -> None:
    """Epic contract: Niagara System Life Cycle track with Desired Age."""
    track_cls = getattr(unreal_mod, "MovieSceneNiagaraSystemTrack", None)
    if track_cls is None:
        notes.append("niagara_system_track_class_missing")
        return
    try:
        track = binding.add_track(track_cls)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"niagara_system_track_failed:{exc}")
        return
    section = track.add_section()
    _set_section_range(section, 0, int(frame_count), notes, "niagara_life")

    age_enum = getattr(unreal_mod, "NiagaraAgeUpdateMode", None)
    desired = getattr(age_enum, "DESIRED_AGE", None) if age_enum else None
    if desired is not None:
        if _set_prop(section, ("age_update_mode",), desired):
            notes.append("niagara_desired_age")

    eval_enum = getattr(unreal_mod, "NiagaraSystemSpawnSectionEvaluateBehavior", None)
    activate = getattr(eval_enum, "ACTIVATE_IF_INACTIVE", None) if eval_enum else None
    if activate is not None:
        _set_prop(section, ("section_evaluate_behavior",), activate)

    start_enum = getattr(unreal_mod, "NiagaraSystemSpawnSectionStartBehavior", None)
    start_activate = getattr(start_enum, "ACTIVATE", None) if start_enum else None
    if start_activate is not None:
        _set_prop(section, ("section_start_behavior",), start_activate)

    notes.append("niagara_lifecycle_track")


def _add_spawnable(unreal_mod, sequence, actor, notes: list[str], tag: str):
    """Prefer spawnables so MRQ owns the actors even if level reload drops possessables."""
    errors: list[str] = []
    for adder, name in (
        (lambda: sequence.add_spawnable_from_instance(actor), "add_spawnable_from_instance"),
        (
            lambda: unreal_mod.MovieSceneSequenceExtensions.add_spawnable_from_instance(sequence, actor),
            "ext.add_spawnable_from_instance",
        ),
    ):
        try:
            binding = adder()
            if binding is not None:
                notes.append(f"{tag}_spawnable:{name}")
                return binding
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}:{exc}")
    notes.append(f"{tag}_spawnable_failed:{';'.join(errors[-2:])}")
    return _add_possessable(unreal_mod, sequence, actor, notes, tag)


def _configure_sequence(
    unreal_mod,
    sequence,
    camera_actor,
    niagara_actor,
    frame_count: int,
    fps: int,
    notes: list[str],
) -> None:
    warmup = int(WARMUP_FRAMES)
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
    try:
        unreal_mod.MovieSceneSequenceExtensions.set_work_range_start(sequence, float(-warmup) / float(fps))
        unreal_mod.MovieSceneSequenceExtensions.set_work_range_end(sequence, float(frame_count) / float(fps))
    except Exception:  # noqa: BLE001
        pass

    removed = 0
    for track in _list_root_tracks(unreal_mod, sequence):
        if _remove_root_track(unreal_mod, sequence, track):
            removed += 1
    notes.append(f"cleared_root_tracks:{removed}")

    try:
        for binding in list(sequence.get_bindings()):
            try:
                sequence.remove_possessable(binding)
            except Exception:  # noqa: BLE001
                try:
                    unreal_mod.MovieSceneSequenceExtensions.remove_possessable(sequence, binding)
                except Exception:  # noqa: BLE001
                    pass
        notes.append("cleared_possessables")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"clear_possessables_skipped:{exc}")

    # Spawnables: sequence recreates camera + Niagara during MRQ (-game) regardless of map.
    cam_binding = _add_spawnable(unreal_mod, sequence, camera_actor, notes, "camera")
    niagara_binding = _add_spawnable(unreal_mod, sequence, niagara_actor, notes, "niagara")
    _add_niagara_lifecycle(unreal_mod, niagara_binding, frame_count, notes)

    cut_track, add_tag = _add_root_track(unreal_mod, sequence, unreal_mod.MovieSceneCameraCutTrack)
    notes.append(f"camera_cut_track:{add_tag}")
    section = cut_track.add_section()
    _set_section_range(section, -warmup, int(frame_count), notes, "camera_cut")
    _bind_camera_cut(unreal_mod, sequence, section, cam_binding, notes)


def _add_setting(config, unreal_mod, class_names: tuple[str, ...], notes: list[str], tag: str):
    for name in class_names:
        cls = getattr(unreal_mod, name, None)
        if cls is None:
            continue
        try:
            setting = config.find_or_add_setting_by_class(cls)
            notes.append(f"{tag}:{name}")
            return setting
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{tag}_failed:{name}:{exc}")
    notes.append(f"{tag}_missing:{','.join(class_names)}")
    return None


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
        _set_prop(out, ("file_name_format",), "{sequence_name}.{frame_number}")
    _set_prop(out, ("flush_disk_writes_per_frame", "b_flush_disk_writes_per_frame"), True)
    notes.append(f"mrq_output:{output_dir}:{width}x{height}")

    _add_setting(
        config,
        unreal_mod,
        ("MoviePipelineDeferredPassBase", "MoviePipelineDeferredPass_PathTracer"),
        notes,
        "mrq_deferred_pass",
    )
    _add_setting(
        config,
        unreal_mod,
        ("MoviePipelineImageSequenceOutput_PNG", "MoviePipelineImageSequenceOutputPNG"),
        notes,
        "mrq_png",
    )

    aa = _add_setting(config, unreal_mod, ("MoviePipelineAntiAliasingSetting",), notes, "mrq_aa")
    if aa is not None:
        # GPU particles require warm-up frames submitted to the GPU (Epic MRQ docs).
        _set_prop(aa, ("engine_warm_up_count",), int(WARMUP_FRAMES))
        _set_prop(aa, ("render_warm_up_count",), 16)
        _set_prop(aa, ("render_warm_up_frames", "b_render_warm_up_frames"), True)
        _set_prop(aa, ("use_camera_cut_for_warm_up", "b_use_camera_cut_for_warm_up"), True)
        _set_prop(aa, ("spatial_sample_count",), 1)
        _set_prop(aa, ("temporal_sample_count",), 1)
        notes.append("mrq_aa_gpu_warmup")

    game = _add_setting(config, unreal_mod, ("MoviePipelineGameOverrideSetting",), notes, "mrq_game_override")
    if game is not None:
        _set_prop(game, ("cinematic_quality_settings", "b_cinematic_quality_settings"), True)

    burn = getattr(unreal_mod, "MoviePipelineBurnInSetting", None)
    if burn is not None:
        try:
            setting = config.find_or_add_setting_by_class(burn)
            setting.set_editor_property("burn_in_class", unreal_mod.SoftClassPath())
        except Exception:  # noqa: BLE001
            pass


def _force_save_map(unreal_mod, map_path: str, notes: list[str], errors: list[str], expect_actors: int) -> None:
    try:
        unreal_mod.EditorLevelLibrary.set_current_level_by_name(
            unreal_mod.EditorLevelLibrary.get_editor_world().get_name()
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        world = unreal_mod.EditorLevelLibrary.get_editor_world()
        # Mark dirty so save_map is not a no-op.
        try:
            unreal_mod.EditorAssetLibrary.save_loaded_asset(world, only_if_is_dirty=False)
        except Exception:  # noqa: BLE001
            pass
        unreal_mod.EditorLoadingAndSavingUtils.save_map(world, map_path)
        notes.append("saved_map")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"save_map_failed:{exc}")
        try:
            unreal_mod.EditorLevelLibrary.save_current_level()
            notes.append("save_current_level")
        except Exception as exc2:  # noqa: BLE001
            errors.append(f"save_level_failed:{exc2}")
    try:
        unreal_mod.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
        notes.append("save_dirty_packages")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"save_dirty_failed:{exc}")
    if not unreal_mod.EditorAssetLibrary.does_asset_exist(map_path):
        errors.append(f"map_missing_after_save:{map_path}")
        raise RuntimeError(f"map_not_saved:{map_path}")
    notes.append("map_exists_after_save")
    if expect_actors > 0:
        notes.append(f"expect_level_actors:{expect_actors}")


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

        cam_loc, cam_rot = _fireworks_camera_pose(unreal)
        camera = _spawn(
            unreal,
            actor_sub,
            actor_class=unreal.CineCameraActor,
            loc=cam_loc,
            rot=cam_rot,
            label=f"{ACTOR_PREFIX}Camera",
            notes=notes,
        )
        if camera is None:
            camera = _spawn(
                unreal,
                actor_sub,
                actor_class=unreal.CameraActor,
                loc=cam_loc,
                rot=cam_rot,
                label=f"{ACTOR_PREFIX}Camera",
                notes=notes,
            )
        if camera is None:
            raise RuntimeError("spawn_camera_failed")
        _configure_cine_camera(unreal, camera, notes)
        notes.append("camera_spawned")

        live_count = _count_vellum_actors(actor_sub)
        notes.append(f"level_actors_after_spawn:{live_count}")
        if live_count < 3:
            raise RuntimeError(f"too_few_level_actors:{live_count}")

        sequence = _load_or_create_level_sequence(unreal, seq_pkg, seq_name)
        if sequence is None:
            raise RuntimeError("sequence_create_failed")
        _configure_sequence(unreal, sequence, camera, niagara, frame_count, frame_rate, notes)

        config = _load_or_create_mrq_config(unreal, cfg_pkg, cfg_name)
        _configure_mrq_config(unreal, config, output_dir.replace("\\", "/"), width, height, notes)

        try:
            unreal.EditorAssetLibrary.save_asset(f"{seq_pkg}/{seq_name}")
            notes.append("saved_sequence")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"save_sequence_failed:{exc}")
            errors.append(f"save_sequence_failed:{exc}")
        try:
            unreal.EditorAssetLibrary.save_asset(f"{cfg_pkg}/{cfg_name}")
            notes.append("saved_config")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"save_config_failed:{exc}")
            errors.append(f"save_config_failed:{exc}")

        _force_save_map(unreal, map_path, notes, errors, expect_actors=live_count)
        if errors:
            raise RuntimeError(";".join(errors[:4]))

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
