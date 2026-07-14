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
STUDIO_PREFIX = "VellumStudio_"
DEFAULT_MAP = "/Game/Vellum/Maps/VellumLookdevStudio"
# Max window (locked §12.2): 4s @ 30fps. Per-system estimate may be shorter.
DEFAULT_FRAMES = 120
MIN_FRAMES = 24
DEFAULT_FPS = 30
# Frames before playback start used as camera-cut warm-up head.
WARMUP_FRAMES = 30


def _editor_world(unreal_mod):
    """Prefer UnrealEditorSubsystem; fall back to deprecated EditorLevelLibrary."""
    try:
        sub = unreal_mod.get_editor_subsystem(unreal_mod.UnrealEditorSubsystem)
        if sub is not None:
            return sub.get_editor_world()
    except Exception:  # noqa: BLE001
        pass
    return _editor_world(unreal_mod)

# Extra frames after Niagara reports finished so trails decay into shot.
TAIL_PAD_FRAMES = 8


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


def _find_labeled_actor(actor_sub, label: str):
    try:
        for actor in actor_sub.get_all_level_actors():
            try:
                if actor.get_actor_label() == label:
                    return actor
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return None
    return None


def _count_vellum_actors(actor_sub) -> int:
    """Count transient MRQ possessable labels only — never studio fixtures."""
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


def _studio_slot_location(unreal_mod, actor_sub, notes: list[str]):
    for label in (f"{STUDIO_PREFIX}Slot_Center", f"{STUDIO_PREFIX}Pedestal"):
        actor = _find_labeled_actor(actor_sub, label)
        if actor is None:
            continue
        try:
            loc = actor.get_actor_location()
            notes.append(f"slot_from:{label}")
            return loc
        except Exception as exc:  # noqa: BLE001
            notes.append(f"slot_loc_failed:{label}:{exc}")
    notes.append("slot_default_origin")
    return unreal_mod.Vector(0.0, 0.0, 120.0)


def _studio_camera_pose(unreal_mod, actor_sub, notes: list[str]):
    actor = _find_labeled_actor(actor_sub, f"{STUDIO_PREFIX}Cam_Mid")
    if actor is not None:
        try:
            loc = actor.get_actor_location()
            rot = actor.get_actor_rotation()
            notes.append("camera_pose_from_studio")
            return loc, rot
        except Exception as exc:  # noqa: BLE001
            notes.append(f"studio_cam_pose_failed:{exc}")
    return _fireworks_camera_pose(unreal_mod)


def _map_has_studio_fixtures(actor_sub) -> bool:
    return _find_labeled_actor(actor_sub, f"{STUDIO_PREFIX}Slot_Center") is not None


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


def _spawn_niagara(unreal_mod, actor_sub, system_asset, notes: list[str], loc=None):
    if loc is None:
        loc = unreal_mod.Vector(0.0, 0.0, 120.0)
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
        # Leave age in default tick mode for length probe + Sequencer lifecycle.
        # DesiredAge=1.0 mid-seek was truncating author-time intent for short bursts.
        if hasattr(comp, "set_age_update_mode"):
            mode = getattr(unreal_mod, "NiagaraAgeUpdateMode", None)
            tick_mode = getattr(mode, "TICK_DELTA_TIME", None) if mode else None
            if tick_mode is not None:
                comp.set_age_update_mode(tick_mode)
        comp.reset_system()
        comp.activate(True)
        notes.append("niagara_activated")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"niagara_activate_failed:{exc}")
    return actor


def _read_user_duration_seconds(unreal_mod, system_asset, comp, notes: list[str]) -> float | None:
    """Best-effort read of an author-exposed duration user parameter."""
    names = (
        "Duration",
        "LifeTime",
        "Lifetime",
        "SystemDuration",
        "BurstDuration",
        "EffectDuration",
        "User.Duration",
        "User.LifeTime",
        "User.Lifetime",
    )
    # Prefer live component getters when available.
    if comp is not None and hasattr(comp, "get_variable_float"):
        for name in names:
            try:
                result = comp.get_variable_float(name)
                val = None
                if isinstance(result, (tuple, list)) and result:
                    val = float(result[0])
                elif isinstance(result, (int, float)):
                    val = float(result)
                if val is not None and val > 0.05:
                    notes.append(f"duration_user_param:{name}={val:.3f}s")
                    return val
            except Exception:  # noqa: BLE001
                continue
    # Fall back to listing user params if UE exposes them.
    try:
        lib = getattr(unreal_mod, "NiagaraFunctionLibrary", None)
        if lib is not None and hasattr(lib, "get_all_user_parameters") and system_asset is not None:
            for info in list(lib.get_all_user_parameters(system_asset) or []):
                try:
                    pname = str(getattr(info, "name", None) or getattr(info, "parameter_name", None) or "")
                except Exception:  # noqa: BLE001
                    continue
                low = pname.lower()
                if any(k in low for k in ("duration", "lifetime", "life_time", "burst")):
                    notes.append(f"duration_user_param_seen:{pname}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"duration_user_params_failed:{exc}")
    return None


def _estimate_capture_frames(
    unreal_mod,
    *,
    system_asset,
    niagara_actor,
    fps: int,
    max_frames: int,
    notes: list[str],
) -> int:
    """Per-system capture length: probe until finished, capped by max_frames (§12.2)."""
    fps = max(1, int(fps or DEFAULT_FPS))
    ceiling = max(MIN_FRAMES, min(int(max_frames or DEFAULT_FRAMES), DEFAULT_FRAMES))
    comp = _niagara_component(unreal_mod, niagara_actor) if niagara_actor is not None else None

    hinted = _read_user_duration_seconds(unreal_mod, system_asset, comp, notes)
    if hinted is not None:
        frames = int(round(hinted * fps)) + TAIL_PAD_FRAMES
        frames = max(MIN_FRAMES, min(ceiling, frames))
        notes.append(f"frame_estimate_user:{frames}/{ceiling}")
        return frames

    if comp is None:
        notes.append(f"frame_estimate_fallback_no_comp:{ceiling}")
        return ceiling

    finished = {"v": False}

    def _mark_finished(*_args, **_kwargs) -> None:
        finished["v"] = True

    try:
        delegate = getattr(comp, "on_system_finished", None)
        if delegate is not None:
            if hasattr(delegate, "add_callable"):
                delegate.add_callable(_mark_finished)
            elif hasattr(delegate, "add_function"):
                delegate.add_function(_mark_finished)
            notes.append("duration_bound_on_system_finished")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"duration_bind_finished_failed:{exc}")

    try:
        if hasattr(comp, "set_age_update_mode"):
            mode = getattr(unreal_mod, "NiagaraAgeUpdateMode", None)
            tick_mode = getattr(mode, "TICK_DELTA_TIME", None) if mode else None
            if tick_mode is not None:
                comp.set_age_update_mode(tick_mode)
        comp.reset_system()
        comp.activate(True)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"duration_probe_reset_failed:{exc}")
        notes.append(f"frame_estimate_fallback_reset:{ceiling}")
        return ceiling

    dt = 1.0 / float(fps)
    last_active = MIN_FRAMES
    saw_active = False
    quiet = 0
    detected = None

    for frame in range(0, ceiling + 1):
        try:
            if hasattr(comp, "advance_simulation"):
                comp.advance_simulation(1, dt)
            elif hasattr(comp, "advance_simulation_by_time"):
                comp.advance_simulation_by_time(dt, dt)
            else:
                notes.append("duration_probe_no_advance")
                break
        except Exception as exc:  # noqa: BLE001
            notes.append(f"duration_advance_failed:{exc}")
            break

        if finished["v"]:
            detected = frame
            notes.append(f"duration_finished_at_frame:{frame}")
            break

        complete = False
        try:
            if hasattr(comp, "is_complete") and bool(comp.is_complete()):
                complete = True
        except Exception:  # noqa: BLE001
            pass
        if complete:
            detected = frame
            notes.append(f"duration_is_complete_at_frame:{frame}")
            break

        active = True
        try:
            if hasattr(comp, "is_active"):
                active = bool(comp.is_active())
        except Exception:  # noqa: BLE001
            active = True

        # Bounds volume as a coarse activity signal for looping/ambient systems.
        extent_alive = False
        try:
            _origin, extent = niagara_actor.get_actor_bounds(True)
            extent_alive = (abs(float(extent.x)) + abs(float(extent.y)) + abs(float(extent.z))) > 8.0
        except Exception:  # noqa: BLE001
            extent_alive = active

        if active or extent_alive:
            saw_active = True
            last_active = frame
            quiet = 0
        elif saw_active:
            quiet += 1
            if quiet >= 8:
                detected = last_active
                notes.append(f"duration_quiet_after_frame:{last_active}")
                break
    else:
        notes.append(f"duration_hit_ceiling:{ceiling}")
        detected = ceiling

    if detected is None:
        detected = ceiling

    frames = max(MIN_FRAMES, min(ceiling, int(detected) + TAIL_PAD_FRAMES))
    notes.append(f"frame_estimate_probe:{frames}/{ceiling}")

    # Rewind so Sequencer spawnable template starts at age 0.
    try:
        comp.reset_system()
        comp.activate(True)
        notes.append("duration_probe_reset_for_sequence")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"duration_probe_rearm_failed:{exc}")
    return frames


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
            _editor_world(unreal_mod).get_name()
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        world = _editor_world(unreal_mod)
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


def _destroy_labeled(actor_sub, notes: list[str]) -> None:
    """Remove camera/niagara level instances after sequence spawnables are authored."""
    if actor_sub is None:
        return
    removed = 0
    try:
        for actor in list(actor_sub.get_all_level_actors()):
            try:
                label = actor.get_actor_label()
            except Exception:  # noqa: BLE001
                continue
            if label in (f"{ACTOR_PREFIX}Camera", f"{ACTOR_PREFIX}System"):
                actor_sub.destroy_actor(actor)
                removed += 1
    except Exception as exc:  # noqa: BLE001
        notes.append(f"destroy_cam_niagara_failed:{exc}")
    notes.append(f"destroyed_cam_niagara:{removed}")


def _soft(path: str) -> str:
    p = path.strip()
    if not p:
        return p
    leaf = p.rsplit("/", 1)[-1]
    if "." in leaf:
        return p
    return f"{p}.{leaf}"


def _author_one_system(
    unreal_mod,
    actor_sub,
    *,
    system_object_path: str,
    system_name: str,
    map_path: str,
    seq_pkg: str,
    cfg_pkg: str,
    output_dir: str,
    width: int,
    height: int,
    frame_count: int,
    frame_rate: int,
    notes: list[str],
    errors: list[str],
    spawn_lights: bool,
) -> dict:
    if spawn_lights:
        _clear_vellum_actors(unreal_mod, actor_sub, notes)
        if _map_has_studio_fixtures(actor_sub):
            notes.append("studio_fixtures_kept")
        else:
            _spawn_lights(unreal_mod, actor_sub, notes)
    else:
        # Later systems: wipe prior Niagara/camera possessables only.
        _destroy_labeled(actor_sub, notes)

    system_asset = unreal_mod.EditorAssetLibrary.load_asset(system_object_path)
    if system_asset is None:
        raise RuntimeError(f"load_failed:{system_object_path}")

    slot_loc = _studio_slot_location(unreal_mod, actor_sub, notes)
    niagara = _spawn_niagara(unreal_mod, actor_sub, system_asset, notes, loc=slot_loc)
    if niagara is None:
        raise RuntimeError(f"spawn_niagara_failed:{system_name}")

    # job frame_count is a ceiling; actual window follows this system's length.
    frame_count = _estimate_capture_frames(
        unreal_mod,
        system_asset=system_asset,
        niagara_actor=niagara,
        fps=frame_rate,
        max_frames=frame_count,
        notes=notes,
    )
    notes.append(f"capture_frames:{system_name}={frame_count}")

    cam_loc, cam_rot = _studio_camera_pose(unreal_mod, actor_sub, notes)
    camera = _spawn(
        unreal_mod,
        actor_sub,
        actor_class=unreal_mod.CineCameraActor,
        loc=cam_loc,
        rot=cam_rot,
        label=f"{ACTOR_PREFIX}Camera",
        notes=notes,
    )
    if camera is None:
        camera = _spawn(
            unreal_mod,
            actor_sub,
            actor_class=unreal_mod.CameraActor,
            loc=cam_loc,
            rot=cam_rot,
            label=f"{ACTOR_PREFIX}Camera",
            notes=notes,
        )
    if camera is None:
        raise RuntimeError(f"spawn_camera_failed:{system_name}")
    _configure_cine_camera(unreal_mod, camera, notes)

    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in system_name) or "system"
    seq_name = f"LS_{safe}"
    cfg_name = f"MRQ_{safe}"

    sequence = _load_or_create_level_sequence(unreal_mod, seq_pkg, seq_name)
    if sequence is None:
        raise RuntimeError(f"sequence_create_failed:{system_name}")
    _configure_sequence(unreal_mod, sequence, camera, niagara, frame_count, frame_rate, notes)

    # Level keeps studio fixtures; sequences own camera+Niagara as spawnables.
    try:
        actor_sub.destroy_actor(camera)
        actor_sub.destroy_actor(niagara)
        notes.append(f"level_cleared_after_spawnable:{system_name}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"post_spawnable_destroy_failed:{exc}")

    config = _load_or_create_mrq_config(unreal_mod, cfg_pkg, cfg_name)
    _configure_mrq_config(unreal_mod, config, output_dir.replace("\\", "/"), width, height, notes)

    try:
        unreal_mod.EditorAssetLibrary.save_asset(f"{seq_pkg}/{seq_name}")
        notes.append(f"saved_sequence:{seq_name}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"save_sequence_failed:{system_name}:{exc}")
    try:
        unreal_mod.EditorAssetLibrary.save_asset(f"{cfg_pkg}/{cfg_name}")
        notes.append(f"saved_config:{cfg_name}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"save_config_failed:{system_name}:{exc}")

    return {
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


def _build_or_update_queue(unreal_mod, package_path: str, asset_name: str, jobs: list[dict], notes: list[str]) -> str | None:
    """Create a MoviePipelineQueue asset with one executor job per system. Returns soft path."""
    full = f"{package_path}/{asset_name}"
    _ensure_dir_asset(unreal_mod, package_path)
    queue_cls = getattr(unreal_mod, "MoviePipelineQueue", None)
    if queue_cls is None:
        notes.append("queue_class_missing")
        return None
    if unreal_mod.EditorAssetLibrary.does_asset_exist(full):
        try:
            unreal_mod.EditorAssetLibrary.delete_asset(full)
        except Exception:  # noqa: BLE001
            pass
    tools = unreal_mod.AssetToolsHelpers.get_asset_tools()
    factory = getattr(unreal_mod, "MoviePipelineQueueFactory", None)
    queue = None
    try:
        if factory is not None:
            queue = tools.create_asset(asset_name, package_path, queue_cls, factory())
        else:
            queue = tools.create_asset(asset_name, package_path, queue_cls, None)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"queue_create_failed:{exc}")
        return None
    if queue is None:
        notes.append("queue_create_returned_none")
        return None

    try:
        queue.delete_all_jobs()
    except Exception:  # noqa: BLE001
        pass

    job_cls = getattr(unreal_mod, "MoviePipelineExecutorJob", None)
    for item in jobs:
        try:
            if job_cls is not None:
                qjob = queue.allocate_new_job(job_cls)
            else:
                qjob = queue.allocate_new_job()
            qjob.job_name = str(item["system_name"])
            qjob.map = unreal_mod.SoftObjectPath(_soft(str(item["map_path"])))
            qjob.sequence = unreal_mod.SoftObjectPath(_soft(str(item["sequence_path"])))
            cfg = unreal_mod.EditorAssetLibrary.load_asset(str(item["config_asset"]))
            if cfg is not None:
                qjob.set_configuration(cfg)
            notes.append(f"queue_job:{item['system_name']}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"queue_job_failed:{item.get('system_name')}:{exc}")
            return None

    try:
        unreal_mod.EditorAssetLibrary.save_asset(full)
        notes.append("saved_queue")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"save_queue_failed:{exc}")
        return None
    return _soft(full)


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
        map_path = str(job.get("map_path") or DEFAULT_MAP)
        seq_pkg = str(job.get("sequence_package") or "/Game/Vellum/Sequences")
        cfg_pkg = str(job.get("config_package") or "/Game/Vellum/MRQ")
        width = int(job.get("width") or 1920)
        height = int(job.get("height") or 1080)
        frame_count = int(job.get("frame_count") or DEFAULT_FRAMES)
        frame_rate = int(job.get("frame_rate") or DEFAULT_FPS)

        # Batch: job.systems = [{object_path, asset_name, output_dir}, ...]
        systems = list(job.get("systems") or [])
        if not systems and job.get("system_object_path"):
            systems = [
                {
                    "object_path": job.get("system_object_path"),
                    "asset_name": job.get("system_name") or "system",
                    "output_dir": job.get("output_dir"),
                }
            ]
        if not systems:
            raise ValueError("missing systems / system_object_path")

        unreal.log(f"Vellum MRQ author start count={len(systems)} map={map_path}")

        if not _open_or_create_map(unreal, map_path, notes):
            raise RuntimeError("map_open_failed")

        actor_sub = _actor_subsystem(unreal)
        if actor_sub is None:
            raise RuntimeError("no_actor_subsystem")

        authored: list[dict] = []
        for idx, sys in enumerate(systems):
            system_object_path = str(sys.get("object_path") or sys.get("system_object_path") or "")
            system_name = str(sys.get("asset_name") or sys.get("system_name") or f"system_{idx}")
            output_dir = str(sys.get("output_dir") or "")
            if not system_object_path or not output_dir:
                raise ValueError(f"system[{idx}] missing object_path/output_dir")
            notes.append(f"author_begin:{system_name}")
            item = _author_one_system(
                unreal,
                actor_sub,
                system_object_path=system_object_path,
                system_name=system_name,
                map_path=map_path,
                seq_pkg=seq_pkg,
                cfg_pkg=cfg_pkg,
                output_dir=output_dir,
                width=width,
                height=height,
                frame_count=frame_count,
                frame_rate=frame_rate,
                notes=notes,
                errors=errors,
                spawn_lights=(idx == 0),
            )
            authored.append(item)
            notes.append(f"author_ok:{system_name}")

        live_count = _count_vellum_actors(actor_sub)
        notes.append(f"level_actors_after_batch:{live_count}")
        _force_save_map(unreal, map_path, notes, errors, expect_actors=0)

        queue_path = _build_or_update_queue(
            unreal,
            cfg_pkg,
            str(job.get("queue_name") or "VellumBatchQueue"),
            authored,
            notes,
        )

        if errors:
            raise RuntimeError(";".join(errors[:4]))

        out.update(
            {
                "ok": True,
                "mode": "batch" if len(authored) > 1 else "single",
                "map_path": map_path,
                "queue_path": queue_path,
                "jobs": authored,
                # Back-compat for single-system readers:
                **(authored[0] if len(authored) == 1 else {}),
                "frame_count": frame_count,
                "frame_rate": frame_rate,
                "width": width,
                "height": height,
            }
        )
        ok = True
        unreal.log(f"Vellum MRQ author ok systems={len(authored)} queue={queue_path}")
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
    result_path = Path(result_path)
    _write_json(result_path, out)
    # Worker historically looked for author-ready.json — keep a twin so in-UE
    # Lookdev Worker never treats a successful author as author_empty.
    ready_twin = result_path.with_name("author-ready.json")
    if ready_twin.resolve() != result_path.resolve():
        _write_json(ready_twin, out)


if __name__ == "__main__":
    main()
