# Vellum UE Lookdev Worker — boots inside UnrealEditor (long-lived).
# Started once via -ExecutePythonScript. Spawns loopback HTTP on 127.0.0.1:8771.
# Capture work runs on the editor/game thread via a slate post-tick callback.
#
# Do not run via UnrealEditor-Cmd as a one-shot: the editor must stay warm.

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

WORKER_VERSION = "lookdev-worker-2"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8771
STUDIO_MAP = "/Game/Vellum/Maps/VellumLookdevStudio"
STUDIO_BUILD_REQUIRED = 3  # match vellum_lookdev_studio_author.STUDIO_BUILD

_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "busy": False,
    "studio_ready": False,
    "map": "",
    "last_error": "",
    "started_at": time.time(),
}
_pending_job: dict[str, Any] | None = None
_pending_result: dict[str, Any] | None = None
_result_event = threading.Event()
_http_server: ThreadingHTTPServer | None = None
_tick_handle = None
_mrq_session: dict[str, Any] | None = None
_capture_session: dict[str, Any] | None = None


def _out_dir() -> Path:
    raw = os.environ.get("VELLUM_OUT_DIR") or ""
    if raw:
        return Path(raw)
    try:
        import unreal  # type: ignore

        return Path(unreal.Paths.project_saved_dir()) / "VellumCapture"
    except Exception:  # noqa: BLE001
        return Path.cwd() / "VellumCapture"


def _log(msg: str) -> None:
    try:
        import unreal  # type: ignore

        unreal.log(f"[VellumWorker] {msg}")
    except Exception:  # noqa: BLE001
        print(f"[VellumWorker] {msg}", flush=True)



def _vellum_progress(job: dict[str, Any], message: str) -> None:
    base = str(job.get("vellum_base") or os.environ.get("VELLUM_BASE") or "").rstrip("/")
    job_id = str(job.get("job_id") or os.environ.get("VELLUM_JOB_ID") or "")
    if not base or not job_id:
        return
    try:
        import urllib.request

        req = urllib.request.Request(
            f"{base}/api/jobs/{job_id}/progress",
            data=json.dumps({"message": message}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as exc:  # noqa: BLE001
        _log(f"progress_failed:{exc}")


def _vault_covered_systems(job: dict[str, Any], notes: list[str]) -> set[str]:
    """Systems that already have lookdev on both slots + hail-overlay."""
    if bool(job.get("force")):
        notes.append("vault_skip_disabled_force")
        return set()
    base = str(job.get("vellum_base") or os.environ.get("VELLUM_BASE") or "").rstrip("/")
    asset_id = str(job.get("asset_id") or "")
    if not base or not asset_id:
        notes.append("vault_skip_no_base_or_asset")
        return set()
    try:
        import urllib.parse
        import urllib.request

        q = urllib.parse.urlencode({"asset_id": asset_id, "limit": "500"})
        with urllib.request.urlopen(f"{base}/api/lookdev/outputs?{q}", timeout=45) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"vault_skip_fetch_failed:{exc}")
        return set()

    lanes_needed = {"slots", "hail-overlay"}
    by_system: dict[str, set[str]] = {}
    for item in list(doc.get("outputs") or doc.get("items") or []):
        sys_name = str(item.get("system_name") or "").strip()
        lane = str(item.get("lane") or "").strip()
        kind = str(item.get("kind") or "")
        if not sys_name or not lane:
            continue
        if kind != "niagara-render":
            continue
        by_system.setdefault(sys_name, set()).add(lane)

    covered = {name for name, lanes in by_system.items() if lanes_needed.issubset(lanes)}
    notes.append(f"vault_covered:{len(covered)}")
    return covered


def _current_map_path() -> str:
    try:
        import unreal  # type: ignore

        world = unreal.EditorLevelLibrary.get_editor_world()
        if world is None:
            return ""
        return str(world.get_path_name() or world.get_name() or "")
    except Exception:  # noqa: BLE001
        return ""


def _load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _studio_build_on_disk() -> int:
    ready = _out_dir() / "studio-ready.json"
    if not ready.is_file():
        return 0
    try:
        doc = json.loads(ready.read_text(encoding="utf-8"))
        return int(doc.get("studio_build") or 0)
    except Exception:  # noqa: BLE001
        return 0


def _ensure_studio(force: bool = False) -> dict[str, Any]:
    import unreal  # type: ignore

    notes: list[str] = []
    map_path = os.environ.get("VELLUM_STUDIO_MAP") or STUDIO_MAP
    exists = unreal.EditorAssetLibrary.does_asset_exist(map_path)
    build = _studio_build_on_disk()
    stale = build < int(STUDIO_BUILD_REQUIRED)
    env_force = os.environ.get("VELLUM_FORCE_STUDIO", "").lower() in ("1", "true", "yes")
    need_author = bool(force or env_force or stale or not exists)
    notes.append(f"studio_build_disk:{build}/required:{STUDIO_BUILD_REQUIRED}")
    notes.append(f"studio_need_author:{need_author}")

    if need_author:
        studio_py = _out_dir() / "vellum_lookdev_studio_author.py"
        boot_dir = Path(__file__).resolve().parent
        candidates = [studio_py, boot_dir / "vellum_lookdev_studio_author.py"]
        ran = False
        for path in candidates:
            if not path.is_file():
                continue
            notes.append(f"studio_author:{path}")
            # Unique module name so a rebuilt script is not stuck as a stale import.
            mod_name = f"vellum_lookdev_studio_author_dyn_{int(time.time())}"
            mod = _load_module_from_path(mod_name, path)
            if hasattr(mod, "main"):
                mod.main()
            ran = True
            break
        if not ran and not exists:
            try:
                unreal.EditorLevelLibrary.new_level(map_path)
                notes.append("studio_blank_created")
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"studio_missing:{exc}", "notes": notes}
        exists = unreal.EditorAssetLibrary.does_asset_exist(map_path)
        build = _studio_build_on_disk()
        if build < int(STUDIO_BUILD_REQUIRED):
            return {
                "ok": False,
                "error": f"studio_build_still_stale:{build}",
                "notes": notes,
            }

    ok = unreal.EditorLoadingAndSavingUtils.load_map(map_path)
    notes.append(f"load_map:{map_path}:{ok}")
    with _state_lock:
        _state["studio_ready"] = bool(ok)
        _state["map"] = _current_map_path() or map_path
        _state["studio_build"] = _studio_build_on_disk()
    return {
        "ok": bool(ok),
        "map_path": map_path,
        "studio_build": _studio_build_on_disk(),
        "notes": notes,
    }


def _stage_import_path() -> None:
    out = _out_dir()
    out.mkdir(parents=True, exist_ok=True)
    boot_dir = Path(__file__).resolve().parent
    for p in (out, boot_dir):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


def _soft(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return p
    leaf = p.rsplit("/", 1)[-1]
    if "." in leaf:
        return p
    return f"{p}.{leaf}"


def _render_queue_in_process(
    unreal_mod,
    queue_path: str,
    authored: list[dict[str, Any]],
    notes: list[str],
    errors: list[str],
) -> bool:
    subsystem = None
    for name in ("MoviePipelineQueueSubsystem", "MoviePipelineQueueEngineSubsystem"):
        cls = getattr(unreal_mod, name, None)
        if cls is None:
            continue
        try:
            subsystem = unreal_mod.get_editor_subsystem(cls)
            if subsystem is not None:
                notes.append(f"mrq_subsystem:{name}")
                break
        except Exception:  # noqa: BLE001
            continue

    executor_cls = getattr(unreal_mod, "MoviePipelineInProcessExecutor", None)
    if executor_cls is None:
        executor_cls = getattr(unreal_mod, "MoviePipelineEditorOnlyExecutor", None)
    if subsystem is None or executor_cls is None:
        errors.append("mrq_in_process_unavailable")
        notes.append("mrq_in_process_unavailable")
        return False

    queue = None
    if queue_path:
        soft = _soft(queue_path)
        try:
            queue = unreal_mod.EditorAssetLibrary.load_asset(soft.split(".")[0])
            notes.append(f"mrq_queue_loaded:{soft}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"mrq_queue_load_failed:{exc}")

    if queue is None:
        try:
            queue = subsystem.get_queue()
            queue.delete_all_jobs()
            for item in authored:
                qjob = queue.allocate_new_job()
                qjob.job_name = str(item.get("system_name") or "system")
                qjob.map = unreal_mod.SoftObjectPath(_soft(str(item.get("map_path") or STUDIO_MAP)))
                seq = str(item.get("sequence_path") or item.get("sequence_asset") or "")
                cfg = str(item.get("config_asset") or item.get("config_path") or "")
                if seq:
                    qjob.sequence = unreal_mod.SoftObjectPath(_soft(seq))
                if cfg:
                    asset = unreal_mod.EditorAssetLibrary.load_asset(cfg.split(".")[0])
                    if asset is not None:
                        qjob.set_configuration(asset)
            notes.append(f"mrq_queue_built_jobs:{len(authored)}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"mrq_queue_build_failed:{exc}")
            return False
    else:
        try:
            if hasattr(subsystem, "load_queue"):
                subsystem.load_queue(queue)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"mrq_queue_install:{exc}")

    done = {"v": False, "ok": False}

    def _on_finished(executor_instance=None, success=True):  # noqa: ANN001
        done["v"] = True
        done["ok"] = bool(success)

    try:
        executor = executor_cls()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mrq_executor_create:{exc}")
        return False

    try:
        if hasattr(executor, "on_executor_finished_delegate"):
            try:
                executor.on_executor_finished_delegate.add_callable(_on_finished)
            except Exception:  # noqa: BLE001
                try:
                    executor.on_executor_finished_delegate.add_function(_on_finished)
                except Exception as exc2:  # noqa: BLE001
                    notes.append(f"mrq_finished_bind_failed:{exc2}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"mrq_finished_delegate:{exc}")

    try:
        if hasattr(subsystem, "render_queue_with_executor_instance"):
            subsystem.render_queue_with_executor_instance(executor)
            notes.append("mrq_render_queue_with_executor_instance")
        elif hasattr(subsystem, "render_queue_with_executor"):
            subsystem.render_queue_with_executor(executor_cls)
            notes.append("mrq_render_queue_with_executor")
        else:
            errors.append("mrq_render_api_missing")
            return False
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mrq_render_start_failed:{exc}")
        return False

    # Do not sleep on the game thread (would deadlock MRQ ticks).
    # Hand the live session to the slate tick so later frames can finish the job.
    global _mrq_session
    _mrq_session = {
        "done": done,
        "subsystem": subsystem,
        "started_at": time.time(),
        "timeout_sec": float(os.environ.get("VELLUM_WORKER_MRQ_TIMEOUT_SEC") or 60 * 60),
        "notes": notes,
        "errors": errors,
    }
    notes.append("mrq_async_started")
    return True  # started; await via tick


def _run_capture_job(job: dict[str, Any]) -> dict[str, Any]:
    import unreal  # type: ignore

    _stage_import_path()
    out = _out_dir()
    notes: list[str] = []
    errors: list[str] = []

    ensure = _ensure_studio(force=bool(job.get("force_studio") or job.get("force")))
    notes.extend(ensure.get("notes") or [])
    if not ensure.get("ok"):
        return {
            "ok": False,
            "error": ensure.get("error") or "studio_not_ready",
            "notes": notes,
            "errors": [ensure.get("error") or "studio_not_ready"],
        }

    systems: list[dict[str, Any]] = list(job.get("systems") or [])
    content_root = str(job.get("content_root") or "/Game/FireworksV1")
    max_systems = int(job.get("max_systems") or 0)
    if not systems:
        try:
            inv_path = out / "vellum_capture.py"
            boot_inv = Path(__file__).resolve().parent / "vellum_capture.py"
            path = inv_path if inv_path.is_file() else boot_inv
            inv = _load_module_from_path("vellum_capture_dyn", path)
            if hasattr(inv, "inventory_systems"):
                systems = list(inv.inventory_systems(content_root=content_root, max_systems=max_systems) or [])
            else:
                os.environ["VELLUM_OUT_DIR"] = str(out).replace("\\", "/")
                os.environ["VELLUM_CONTENT_ROOT"] = content_root
                os.environ["VELLUM_MAX_SYSTEMS"] = str(max_systems)
                if hasattr(inv, "main"):
                    inv.main()
                inv_json = out / "manifest-inventory.json"
                if not inv_json.is_file():
                    inv_json = out / "inventory.json"
                if inv_json.is_file():
                    doc = json.loads(inv_json.read_text(encoding="utf-8"))
                    systems = list(doc.get("niagara_systems") or doc.get("systems") or [])
            notes.append(f"inventory_count:{len(systems)}")
            _vellum_progress(job, f"Inventory: {len(systems)} systems")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"inventory_failed:{exc}")
            notes.append(traceback.format_exc()[-1500:])

    if not systems:
        return {
            "ok": False,
            "error": errors[0] if errors else "no_systems",
            "notes": notes,
            "errors": errors or ["no_systems"],
            "niagara_systems": 0,
        }

    covered = _vault_covered_systems(job, notes)
    if covered:
        before = len(systems)
        systems = [
            s
            for s in systems
            if str(s.get("asset_name") or s.get("system_name") or "") not in covered
        ]
        notes.append(f"vault_skip_applied:{before - len(systems)}_of_{before}")
        _vellum_progress(job, f"Vault skip: rendering {len(systems)} (skipped {before - len(systems)})")
        if not systems:
            manifest = {
                "ok": True,
                "mode": "lookdev-worker",
                "worker_version": WORKER_VERSION,
                "niagara_systems_found": before,
                "authored": 0,
                "frame_total": 0,
                "stills_attempted": False,
                "stills": [],
                "skipped_vault": sorted(covered),
                "errors": [],
                "notes": notes,
                "mrq_ok": True,
                "error": "",
            }
            (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            return manifest

    _vellum_progress(job, f"Authoring {len(systems)} systems on Lookdev Studio…")
    mrq_root = out / "mrq"
    mrq_root.mkdir(parents=True, exist_ok=True)
    author_systems: list[dict[str, Any]] = []
    for sys_doc in systems:
        name = str(sys_doc.get("asset_name") or sys_doc.get("system_name") or "")
        obj = str(sys_doc.get("object_path") or sys_doc.get("system_object_path") or "")
        if not name or not obj:
            continue
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name) or "system"
        seq_out = mrq_root / safe
        seq_out.mkdir(parents=True, exist_ok=True)
        author_systems.append(
            {
                "asset_name": name,
                "system_name": name,
                "object_path": obj,
                "system_object_path": obj,
                "output_dir": str(seq_out).replace("\\", "/"),
            }
        )

    frame_count = int(job.get("frame_count") or 120)
    frame_rate = int(job.get("frame_rate") or 30)
    width = int(job.get("width") or 1920)
    height = int(job.get("height") or 1080)
    map_path = str(job.get("map_path") or STUDIO_MAP)

    job_path = out / "worker-job.json"
    author_job = {
        "asset_id": job.get("asset_id") or "",
        "map_path": map_path,
        "width": width,
        "height": height,
        "frame_count": frame_count,
        "frame_rate": frame_rate,
        "sequence_package": "/Game/Vellum/Sequences",
        "config_package": "/Game/Vellum/MRQ",
        "queue_name": "VellumBatchQueue",
        "systems": author_systems,
    }
    job_path.write_text(json.dumps(author_job, indent=2) + "\n", encoding="utf-8")
    os.environ["VELLUM_JOB_JSON"] = str(job_path).replace("\\", "/")
    os.environ["VELLUM_OUT_DIR"] = str(out).replace("\\", "/")

    try:
        author_path = out / "vellum_capture_mrq_author.py"
        boot_author = Path(__file__).resolve().parent / "vellum_capture_mrq_author.py"
        path = author_path if author_path.is_file() else boot_author
        author = _load_module_from_path("vellum_capture_mrq_author_dyn", path)
        if hasattr(author, "main"):
            author.main()
        notes.append("author_main_ok")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"author_failed:{exc}")
        notes.append(traceback.format_exc()[-2000:])
        return {
            "ok": False,
            "error": str(errors[0]),
            "notes": notes,
            "errors": errors,
            "niagara_systems": len(author_systems),
        }

    author_ready = out / "author-ready.json"
    authored: list[dict[str, Any]] = []
    queue_path = ""
    if author_ready.is_file():
        try:
            doc = json.loads(author_ready.read_text(encoding="utf-8"))
            authored = list(doc.get("jobs") or [])
            queue_path = str(doc.get("queue_path") or "")
            if not doc.get("ok"):
                errors.extend(list(doc.get("errors") or [])[:8])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"author_ready_parse:{exc}")

    if not authored:
        return {
            "ok": False,
            "error": errors[0] if errors else "author_empty",
            "notes": notes,
            "errors": errors or ["author_empty"],
            "niagara_systems": len(author_systems),
        }

    try:
        started = _render_queue_in_process(unreal, queue_path, authored, notes, errors)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mrq_in_process_failed:{exc}")
        notes.append(traceback.format_exc()[-1500:])
        started = False

    if not started:
        frame_total = 0
        for item in authored:
            od = Path(str(item.get("output_dir") or ""))
            if od.is_dir():
                frame_total += len(list(od.glob("*.png")) + list(od.glob("*.jpg")))
        manifest = {
            "ok": False,
            "mode": "lookdev-worker",
            "worker_version": WORKER_VERSION,
            "niagara_systems_found": len(author_systems),
            "authored": len(authored),
            "queue_path": queue_path,
            "frame_total": frame_total,
            "stills_attempted": True,
            "stills": [],
            "errors": errors or ["mrq_start_failed"],
            "notes": notes,
            "mrq_ok": False,
            "error": (errors[0] if errors else "mrq_start_failed"),
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest

    # Defer finish to later ticks while MRQ runs (must not block this tick).
    global _capture_session
    _capture_session = {
        "out": out,
        "authored": authored,
        "author_systems": author_systems,
        "queue_path": queue_path,
        "notes": notes,
        "errors": errors,
    }
    return None


def _finalize_capture_manifest(mrq_ok: bool) -> dict[str, Any]:
    global _capture_session, _mrq_session
    sess = _capture_session or {}
    out: Path = sess.get("out") or _out_dir()
    authored = list(sess.get("authored") or [])
    notes = list(sess.get("notes") or [])
    errors = list(sess.get("errors") or [])
    if _mrq_session:
        notes = list(_mrq_session.get("notes") or notes)
        errors = list(_mrq_session.get("errors") or errors)
    frame_total = 0
    for item in authored:
        od = Path(str(item.get("output_dir") or ""))
        if od.is_dir():
            frame_total += len(list(od.glob("*.png")) + list(od.glob("*.jpg")))
    ok = bool(frame_total > 0) or (mrq_ok and not errors)
    if errors and frame_total == 0:
        ok = False
    manifest = {
        "ok": ok,
        "mode": "lookdev-worker",
        "worker_version": WORKER_VERSION,
        "niagara_systems_found": len(sess.get("author_systems") or []),
        "authored": len(authored),
        "queue_path": sess.get("queue_path") or "",
        "frame_total": frame_total,
        "stills_attempted": True,
        "stills": [],
        "errors": errors,
        "notes": notes,
        "mrq_ok": mrq_ok,
        "error": (errors[0] if (errors and not ok) else ""),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _capture_session = None
    _mrq_session = None
    return manifest


def _poll_mrq_session() -> dict[str, Any] | None:
    """If MRQ is running, return None until finished; then return final manifest."""
    global _mrq_session
    if not _mrq_session:
        return None
    done = _mrq_session.get("done") or {}
    subsystem = _mrq_session.get("subsystem")
    notes = _mrq_session.setdefault("notes", [])
    errors = _mrq_session.setdefault("errors", [])
    try:
        if hasattr(subsystem, "is_rendering") and not bool(subsystem.is_rendering()):
            if not done.get("v"):
                done["v"] = True
                done["ok"] = True
                notes.append("mrq_is_rendering_false")
    except Exception:  # noqa: BLE001
        pass
    if not done.get("v"):
        if time.time() - float(_mrq_session.get("started_at") or time.time()) > float(
            _mrq_session.get("timeout_sec") or 3600
        ):
            errors.append("mrq_timeout")
            notes.append("mrq_timeout")
            return _finalize_capture_manifest(False)
        return None
    notes.append(f"mrq_finished_ok:{done.get('ok')}")
    return _finalize_capture_manifest(bool(done.get("ok")))


def _health_payload() -> dict[str, Any]:
    with _state_lock:
        return {
            "ok": True,
            "version": WORKER_VERSION,
            "map": _state.get("map") or _current_map_path(),
            "busy": bool(_state.get("busy")),
            "studio_ready": bool(_state.get("studio_ready")),
            "studio_build": int(_state.get("studio_build") or _studio_build_on_disk()),
            "studio_build_required": int(STUDIO_BUILD_REQUIRED),
            "last_error": _state.get("last_error") or "",
            "uptime_sec": int(time.time() - float(_state.get("started_at") or time.time())),
        }


def _enqueue_and_wait(job: dict[str, Any], *, timeout_sec: float) -> dict[str, Any]:
    global _pending_job, _pending_result
    with _state_lock:
        if _state.get("busy") or _pending_job is not None:
            return {"ok": False, "error": "worker_busy"}
        _pending_result = None
        _result_event.clear()
        _pending_job = dict(job)

    if not _result_event.wait(timeout=timeout_sec):
        with _state_lock:
            _pending_job = None
            _state["busy"] = False
        return {"ok": False, "error": "worker_timeout"}

    with _state_lock:
        result = dict(_pending_result or {"ok": False, "error": "no_result"})
        _pending_result = None
    return result


def _on_editor_tick_dispatch(_delta: float) -> bool:
    global _pending_job, _pending_result, _capture_session

    # File inbox — agent can drop a job without depending on a blocking HTTP reply.
    try:
        inbox = _out_dir() / "worker-inbox" / "job.json"
        if (
            inbox.is_file()
            and _pending_job is None
            and not _state.get("busy")
            and _mrq_session is None
        ):
            job = json.loads(inbox.read_text(encoding="utf-8"))
            try:
                inbox.unlink()
            except Exception:  # noqa: BLE001
                pass
            with _state_lock:
                _pending_result = None
                _result_event.clear()
                _pending_job = dict(job)
            _log(f"inbox_accepted job_id={job.get('job_id')}")
    except Exception as exc:  # noqa: BLE001
        _log(f"inbox_failed:{exc}")

    # Continue in-flight MRQ without accepting a new job.
    if _mrq_session is not None and _capture_session is not None:
        finished = _poll_mrq_session()
        if finished is not None:
            _log(f"capture_end ok={finished.get('ok')} frames={finished.get('frame_total')}")
            with _state_lock:
                _pending_result = finished
                _state["busy"] = False
                _state["map"] = _current_map_path()
                _state["last_error"] = str(finished.get("error") or "")
            try:
                outbox = _out_dir() / "worker-outbox"
                outbox.mkdir(parents=True, exist_ok=True)
                (outbox / "result.json").write_text(json.dumps(finished, indent=2) + "\n", encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            _result_event.set()
        return True

    with _state_lock:
        job = _pending_job
        if job is None or _state["busy"]:
            return True
        _state["busy"] = True
        _pending_job = None

    result: dict[str, Any] | None
    try:
        if job.get("_op") == "ensure_studio":
            result = _ensure_studio(force=bool(job.get("force_studio")))
        else:
            _log(f"capture_begin job_id={job.get('job_id')}")
            result = _run_capture_job(job)
            if result is None:
                # MRQ started; stay busy until _poll_mrq_session finishes.
                _log("capture_mrq_async_waiting")
                return True
            _log(f"capture_end ok={result.get('ok')} frames={result.get('frame_total')}")
    except Exception as exc:  # noqa: BLE001
        result = {
            "ok": False,
            "error": str(exc),
            "errors": [str(exc)],
            "notes": [traceback.format_exc()[-2000:]],
        }
        _log(f"capture_crash {exc}")

    with _state_lock:
        _pending_result = result
        _state["busy"] = False
        _state["map"] = _current_map_path()
        _state["last_error"] = str((result or {}).get("error") or "")
    if result is not None:
        try:
            outbox = _out_dir() / "worker-outbox"
            outbox.mkdir(parents=True, exist_ok=True)
            (outbox / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    _result_event.set()
    return True

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        _log("http " + (fmt % args))

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/v1/health"):
            self._send(200, _health_payload())
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            body = {}

        if path == "/v1/ensure_studio":
            result = _enqueue_and_wait(
                {"_op": "ensure_studio", "force_studio": bool(body.get("force"))},
                timeout_sec=120,
            )
            self._send(200 if result.get("ok") else 500, result)
            return

        if path == "/v1/capture":
            timeout = float(
                body.get("timeout_sec")
                or os.environ.get("VELLUM_WORKER_JOB_TIMEOUT_SEC")
                or 6 * 60 * 60
            )
            result = _enqueue_and_wait(body, timeout_sec=timeout)
            self._send(200 if result.get("ok") else 500, result)
            return

        if path == "/v1/shutdown":
            def _stop() -> None:
                time.sleep(0.2)
                if _http_server is not None:
                    _http_server.shutdown()

            threading.Thread(target=_stop, daemon=True).start()
            self._send(200, {"ok": True, "stopping": True})
            return

        self._send(404, {"ok": False, "error": "not_found"})


def main() -> None:
    global _http_server, _tick_handle
    import unreal  # type: ignore

    host = os.environ.get("VELLUM_WORKER_HOST") or DEFAULT_HOST
    port = int(os.environ.get("VELLUM_WORKER_PORT") or DEFAULT_PORT)
    _out_dir().mkdir(parents=True, exist_ok=True)

    try:
        _tick_handle = unreal.register_slate_post_tick_callback(_on_editor_tick_dispatch)
        _log(f"tick_registered handle={_tick_handle}")
    except Exception as exc:  # noqa: BLE001
        _log(f"tick_register_failed:{exc}")

    try:
        boot = _ensure_studio(force=False)
        _log(f"boot_studio ok={boot.get('ok')} notes={boot.get('notes')}")
    except Exception as exc:  # noqa: BLE001
        _log(f"boot_studio_failed:{exc}")

    server = ThreadingHTTPServer((host, port), _Handler)
    _http_server = server
    ready_path = _out_dir() / "worker-ready.json"
    ready_path.write_text(
        json.dumps(
            {
                "ok": True,
                "version": WORKER_VERSION,
                "host": host,
                "port": port,
                "map": STUDIO_MAP,
                "pid": os.getpid(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _log(f"listening http://{host}:{port} version={WORKER_VERSION}")

    # CRITICAL: never serve_forever on the ExecutePythonScript thread.
    # That froze the editor after loading the map — Capture waited forever because
    # slate ticks (which run /v1/capture work) never got the GIL/editor time.
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.5},
        name="VellumWorkerHTTP",
        daemon=False,
    )
    thread.start()
    _log("http_background_thread_started — editor stays ticking for Capture")
    # Return: UnrealEditor remains open; tick callback drives Capture jobs.


if __name__ == "__main__":
    main()
