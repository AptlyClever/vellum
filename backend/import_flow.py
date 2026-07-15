"""Product import/reconcile flow — Library, vault, conversion, availability.

Epic/Fab acquisition remains a human UI boundary when required. Once content
appears in AuroraVellum, reconcile owns register, stage, P4, validation, and
machine conversion. "Lookdev" is not an operator gate.
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import fab_library as fab_library_mod
from . import lookdev as lookdev_mod
from . import register as register_mod
from . import ue_hosts as ue_hosts_mod

TRUSTED_CAPTURE_NOTE = "via mrq-batch"
TRUSTED_CAPTURE_AFTER = os.environ.get(
    "VELLUM_TRUSTED_CAPTURE_AFTER", "2026-07-13T23:15:00"
)
INACTIVE_REDEMPTION_STATES = {
    "superseded",
    "retired",
    "archived",
    "deleted",
}


def _is_inactive_asset(asset: dict[str, Any]) -> bool:
    return (
        str(asset.get("redemption_status") or "").lower()
        in INACTIVE_REDEMPTION_STATES
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def vault_root() -> Path:
    configured = os.environ.get("VELLUM_VAULT_ROOT", "").strip()
    if configured:
        return Path(configured)
    try:
        root = register_mod.ensure_register().get("vault_root")
        if root:
            return Path(str(root))
    except Exception:
        pass
    return Path("/mnt/data/vault/vellum")


def stage_dest_for_asset(asset: dict[str, Any]) -> Path:
    """Canonical vault folder for an Epic/Unreal pack stage."""
    aid = str(asset.get("id") or "unknown")
    bundle = "humble-all-in-one-unreal-unity-gamedev"
    engine = str(asset.get("engine") or "unreal").lower()
    lane = "epic-unreal" if engine == "unreal" else "unity"
    return vault_root() / "01-source-bundles" / bundle / lane / aid


def content_root_from_folder_name(folder_name: str) -> str:
    name = (folder_name or "").strip().strip("/\\")
    if not name:
        return "/Game"
    # Unreal Content/<Folder> maps to /Game/<Folder>
    return f"/Game/{name}"


def _has_trusted_capture(asset_id: str) -> bool:
    outs = lookdev_mod.list_outputs(asset_id=asset_id, limit=200)
    systems: set[str] = set()
    lanes_by: dict[str, set[str]] = {}
    for o in outs:
        note = str(o.get("note") or "")
        if TRUSTED_CAPTURE_NOTE not in note:
            continue
        created = str(o.get("created_at") or "")
        if created < TRUSTED_CAPTURE_AFTER:
            continue
        sn = str(o.get("system_name") or "").strip()
        lane = str(o.get("lane") or "").strip()
        if not sn or lane not in ("slots", "hail-overlay"):
            continue
        lanes_by.setdefault(sn, set()).add(lane)
    for sn, lanes in lanes_by.items():
        if lanes >= {"slots", "hail-overlay"}:
            systems.add(sn)
    return len(systems) > 0


def _has_pack_derive(asset_id: str) -> bool:
    outs = lookdev_mod.list_outputs(asset_id=asset_id, limit=40)
    for o in outs:
        kind = str(o.get("kind") or "")
        if kind in {"hero-still", "still", "niagara-render"}:
            return True
    return False


def _has_niagara_lookdev(asset_id: str) -> bool:
    """MRQ / viewport still evidence — not Fab catalog thumbs."""
    if _has_trusted_capture(asset_id):
        return True
    outs = lookdev_mod.list_outputs(asset_id=asset_id, limit=80)
    for o in outs:
        kind = str(o.get("kind") or "")
        if kind in {"niagara-render", "niagara-sequence"}:
            return True
    return False


def lookdev_mode_for_asset(asset: dict[str, Any] | None) -> str:
    """Required post-stage lookdev path for this pack.

    niagara_mrq — agent must Capture (MRQ); Fab thumbs are preview only.
    texture — Derive (loose png/jpg or Fab catalog thumb).
    """
    if not asset:
        return "texture"
    aid = str(asset.get("id") or "").lower()
    name = str(asset.get("display_name") or "").lower()
    ptype = str(asset.get("package_type") or "").lower()
    blob = f"{aid} {name} {ptype}"
    if "niagara" in blob or "vefect" in blob:
        return "niagara_mrq"
    if re.search(r"\bvfx\b", blob) or "-vfx" in aid or "vfx-" in aid:
        return "niagara_mrq"
    # Packed FX naming without the letters VFX
    if any(
        tok in aid
        for tok in (
            "explosion",
            "slash-trail",
            "toon-abilities",
            "fireworks",
            "portal-",
            "magic-cast",
            "basic-vfx",
            "free-niagara",
        )
    ):
        return "niagara_mrq"
    return "texture"


def lookdev_satisfied(asset_id: str, *, asset: dict[str, Any] | None = None) -> bool:
    row = asset or register_mod.get_asset(asset_id)
    mode = lookdev_mode_for_asset(row)
    # Prefer the bulk index (one catalog parse) over per-call catalog scans.
    if asset_id in _lookdev_asset_ids():
        return True
    if mode == "niagara_mrq":
        return _has_niagara_lookdev(asset_id)
    return _has_pack_derive(asset_id) or _has_trusted_capture(asset_id)


AVAILABILITY_STATES = (
    "ready",
    "on_disk",
    "vault",
    "installable",
    "need_download",
    "deferred",
)

# List/ops paths must not stampede NFS (Path.exists per asset) or rebuild catalogs.
_AV_INDEX_CACHE: dict[str, Any] | None = None
_AV_INDEX_CACHE_AT: float = 0.0
_AV_INDEX_CACHE_KEY: str = ""
_AV_INDEX_TTL_SEC = float(os.environ.get("VELLUM_AVAILABILITY_TTL_SEC") or 20)


_LOOKDEV_IDS_CACHE: set[str] | None = None
_LOOKDEV_IDS_CACHE_AT: float = 0.0
_LOOKDEV_IDS_TTL_SEC = float(os.environ.get("VELLUM_LOOKDEV_IDS_TTL_SEC") or 30)


def _lookdev_asset_ids() -> set[str]:
    """Ids with lookdev evidence (cached — catalog walk is list-path cost)."""
    import time

    global _LOOKDEV_IDS_CACHE, _LOOKDEV_IDS_CACHE_AT
    now = time.monotonic()
    if (
        _LOOKDEV_IDS_CACHE is not None
        and (now - _LOOKDEV_IDS_CACHE_AT) < _LOOKDEV_IDS_TTL_SEC
    ):
        return _LOOKDEV_IDS_CACHE

    outs = lookdev_mod.load_catalog().get("outputs") or []
    derive_ids: set[str] = set()
    niagara_ids: set[str] = set()
    capture_lanes: dict[str, dict[str, set[str]]] = {}
    for o in outs:
        if not isinstance(o, dict):
            continue
        aid = str(o.get("asset_id") or "").strip()
        if not aid:
            continue
        kind = str(o.get("kind") or "")
        if kind in {"hero-still", "still"}:
            derive_ids.add(aid)
        if kind in {"niagara-render", "niagara-sequence"}:
            niagara_ids.add(aid)
        note = str(o.get("note") or "")
        if TRUSTED_CAPTURE_NOTE not in note:
            continue
        created = str(o.get("created_at") or "")
        if created < TRUSTED_CAPTURE_AFTER:
            continue
        sn = str(o.get("system_name") or "").strip()
        lane = str(o.get("lane") or "").strip()
        if not sn or lane not in ("slots", "hail-overlay"):
            continue
        capture_lanes.setdefault(aid, {}).setdefault(sn, set()).add(lane)
    trusted: set[str] = set()
    for aid, by_system in capture_lanes.items():
        if any(lanes >= {"slots", "hail-overlay"} for lanes in by_system.values()):
            trusted.add(aid)
    # Texture path packs may count Fab/texture derive; Niagara must have MRQ evidence.
    ok: set[str] = set(niagara_ids) | set(trusted)
    assets_by_id = {
        str(a.get("id") or ""): a
        for a in register_mod.list_assets()
        if isinstance(a, dict) and a.get("id")
    }
    for aid in derive_ids:
        asset = assets_by_id.get(aid)
        if lookdev_mode_for_asset(asset) == "texture":
            ok.add(aid)
    # Conversion Factory evidence (product path): any game-ready catalog
    # element counts — the reconcile loop on Aurora runs the factory jobs and
    # uploads outputs, so this bit flips without any operator action.
    from . import game_ready as game_ready_mod

    for el in game_ready_mod.load_catalog().get("elements") or []:
        if isinstance(el, dict) and el.get("asset_id"):
            ok.add(str(el["asset_id"]))
    _LOOKDEV_IDS_CACHE = ok
    _LOOKDEV_IDS_CACHE_AT = now
    return ok


def availability_row(
    *,
    on_disk: bool,
    staged: bool,
    lookdev: bool,
    installable: bool,
    deferred: bool = False,
) -> dict[str, str]:
    """Single list-row truth: can we use this pack now?"""
    if on_disk and staged and lookdev:
        return {
            "state": "ready",
            "label": "Ready",
            "detail": "on disk · staged · converted",
        }
    if on_disk:
        missing = []
        if not staged:
            missing.append("stage (auto)")
        if not lookdev:
            missing.append("conversion (auto)")
        detail = "on F: · awaiting " + (" + ".join(missing) if missing else "finish")
        return {"state": "on_disk", "label": "On disk", "detail": detail}
    if installable:
        return {
            "state": "installable",
            "label": "Installable",
            "detail": "VaultCache → install",
        }
    if staged:
        detail = "vault staged" + (" · converted" if lookdev else " · awaiting conversion (auto)")
        return {"state": "vault", "label": "Vault only", "detail": detail}
    if deferred:
        return {
            "state": "deferred",
            "label": "Deferred",
            "detail": "Complete Project pack · create/migrate only if needed",
        }
    return {
        "state": "need_download",
        "label": "Not on Aurora",
        "detail": "not under F:\\Games\\AuroraVellum\\Content (parked)",
    }


def clear_ops_caches() -> None:
    """Drop list/ops caches after register or lookdev mutations."""
    global _AV_INDEX_CACHE, _AV_INDEX_CACHE_AT, _AV_INDEX_CACHE_KEY
    global _LOOKDEV_IDS_CACHE, _LOOKDEV_IDS_CACHE_AT
    _AV_INDEX_CACHE = None
    _AV_INDEX_CACHE_AT = 0.0
    _AV_INDEX_CACHE_KEY = ""
    _LOOKDEV_IDS_CACHE = None
    _LOOKDEV_IDS_CACHE_AT = 0.0


def availability_index(
    *,
    engine: str | None = "unreal",
    host_id: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Bulk availability for list UI — one Content scan + one lookdev catalog pass."""
    import time

    global _AV_INDEX_CACHE, _AV_INDEX_CACHE_AT, _AV_INDEX_CACHE_KEY
    reg = register_mod.register_path()
    try:
        reg_mtime = reg.stat().st_mtime if reg.is_file() else 0.0
    except OSError:
        reg_mtime = 0.0
    cache_key = f"{engine or ''}|{host_id or ''}|{reg}|{reg_mtime}"
    now = time.monotonic()
    if (
        not force_refresh
        and _AV_INDEX_CACHE is not None
        and _AV_INDEX_CACHE_KEY == cache_key
        and (now - _AV_INDEX_CACHE_AT) < _AV_INDEX_TTL_SEC
    ):
        return _AV_INDEX_CACHE

    assets = register_mod.list_assets()
    if engine:
        assets = [
            a for a in assets if str(a.get("engine") or "").lower() == engine.lower()
        ]
    folders = ue_hosts_mod.list_content_folders(host_id).get("folders") or []
    folder_by_name = {
        str(f.get("name") or ""): f
        for f in folders
        if isinstance(f, dict) and f.get("name")
    }
    folder_map = folder_to_asset_id_map()
    on_disk_ids: set[str] = set()
    for name in folder_by_name:
        if name in SKIP_FOLDERS:
            continue
        aid = folder_map.get(name)
        if aid:
            on_disk_ids.add(aid)
    lookdev_ids = _lookdev_asset_ids()
    by_id: dict[str, dict[str, str]] = {}
    counts = {s: 0 for s in AVAILABILITY_STATES}
    for a in assets:
        aid = str(a["id"])
        if _is_inactive_asset(a):
            continue
        # Trust register stage pointer for list/ops. Do not Path.exists() across
        # vault NFS on every homepage load — that alone made /api/ops/now ~30s+.
        raw = str(a.get("raw_location") or "").strip()
        staged = bool(raw)
        installable = (
            bool(fab_install_candidates(aid))
            and aid not in on_disk_ids
            and not staged
        )
        acq = None
        if aid not in on_disk_ids and not staged and not installable:
            acq = fab_library_mod.acquisition_for_asset(a)
        row = availability_row(
            on_disk=aid in on_disk_ids,
            staged=staged,
            lookdev=aid in lookdev_ids,
            installable=installable,
            deferred=bool((acq or {}).get("deferred")),
        )
        by_id[aid] = row
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    payload = {
        "schema_version": 1,
        "engine": engine,
        "counts": counts,
        "by_asset_id": by_id,
        "cached": False,
        "cache_ttl_sec": _AV_INDEX_TTL_SEC,
    }
    _AV_INDEX_CACHE = {**payload, "cached": True}
    _AV_INDEX_CACHE_AT = now
    _AV_INDEX_CACHE_KEY = cache_key
    return payload


_PROGRESS_INVENTORY_RE = re.compile(r"Inventory:\s*(\d+)\s+systems", re.I)
_PROGRESS_RENDER_RE = re.compile(r"Vault skip:\s*rendering\s+(\d+)", re.I)
_PROGRESS_AUTHOR_RE = re.compile(r"Authoring\s+(\d+)\s+systems", re.I)
_PROGRESS_SYSTEM_FRACS = (
    re.compile(r"(?:Rendered|Ingest(?:ed)?|Capture(?:d)?)\s+(\d+)\s*/\s*(\d+)", re.I),
    re.compile(r"system\s+(\d+)\s*/\s*(\d+)", re.I),
)


def parse_progress_log(log: str) -> dict[str, Any]:
    """Extract last phase + system counts from a job progress log."""
    messages: list[str] = []
    for line in str(log or "").splitlines():
        if line.startswith("  |") or line.strip() == "---" or not line.strip():
            continue
        bar = line.find(" | ")
        if bar < 0:
            continue
        msg = line[bar + 3 :].strip()
        if msg:
            messages.append(msg)
    phase = messages[-1] if messages else "Waiting for agent…"
    systems_total: int | None = None
    systems_done: int | None = None
    for msg in messages:
        m = _PROGRESS_INVENTORY_RE.search(msg)
        if m:
            systems_total = int(m.group(1))
        m = _PROGRESS_RENDER_RE.search(msg) or _PROGRESS_AUTHOR_RE.search(msg)
        if m:
            systems_total = int(m.group(1))
        for cre in _PROGRESS_SYSTEM_FRACS:
            m = cre.search(msg)
            if m:
                systems_done = int(m.group(1))
                systems_total = int(m.group(2))
    return {
        "phase": phase,
        "systems_total": systems_total,
        "systems_done": systems_done,
        "message_count": len(messages),
    }


def _seconds_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
    except Exception:
        return None


def _capture_job_progress(
    job: dict[str, Any], *, include_lookdev: bool = False
) -> dict[str, Any]:
    """Operator-facing progress for one ue_capture job."""
    from . import jobs as jobs_mod

    job_id = str(job.get("job_id") or "")
    asset_id = str(job.get("asset_id") or "") or None
    status = str(job.get("status") or "")
    try:
        raw = jobs_mod.read_job_progress(job_id) if job_id else {}
    except KeyError:
        raw = {}
    parsed = parse_progress_log(str(raw.get("log") or ""))
    lookdev_count = 0
    if include_lookdev and asset_id:
        lookdev_count = len(
            lookdev_mod.list_outputs(asset_id=asset_id, limit=500)
        )
    systems_total = parsed.get("systems_total")
    systems_done = parsed.get("systems_done")
    # Do NOT infer systems_done from historical lookdev_outputs — packs accumulate
    # old stills across failed/re-run captures and would fake 99% while MRQ is stalled.
    job_percent: int | None = None
    if status == "succeeded":
        job_percent = 100
    elif status in {"failed", "cancelled"}:
        job_percent = None
    elif systems_total and systems_done is not None:
        job_percent = max(
            5, min(99, int(round(100.0 * systems_done / systems_total)))
        )
    elif systems_total:
        # Known inventory but no per-system ticks yet (authoring / MRQ quiet).
        job_percent = 15
    elif status in {"running", "queued"}:
        job_percent = 5 if status == "running" else 0
    silence = _seconds_since(str(raw.get("updated_at") or job.get("updated_at")))
    stalled = bool(
        status == "running" and silence is not None and silence >= 120
    )
    return {
        "asset_id": asset_id,
        "job_id": job_id,
        "status": status,
        "phase": parsed.get("phase"),
        "systems_total": systems_total,
        "systems_done": systems_done,
        "lookdev_outputs": lookdev_count,
        "percent": job_percent,
        "silence_sec": int(silence) if silence is not None else None,
        "stalled": stalled,
        "updated_at": raw.get("updated_at") or job.get("updated_at"),
        "started_at": job.get("started_at"),
    }


def ops_pulse(*, engine: str = "unreal", host_id: str | None = None) -> dict[str, Any]:
    """Cheap homepage/Live-ops poll — counts + capture heartbeats only."""
    from . import jobs as jobs_mod

    av = availability_index(engine=engine, host_id=host_id)
    counts = dict(av.get("counts") or {})
    ready_n = int(counts.get("ready") or 0)
    remaining_n = sum(
        int(counts.get(k) or 0)
        for k in ("on_disk", "vault", "installable", "need_download")
    )
    total_n = ready_n + remaining_n
    inventory_percent = (
        100 if total_n == 0 else int(round(100.0 * ready_n / total_n))
    )
    caps = [
        j
        for j in jobs_mod.list_jobs(limit=40)
        if j.get("kind") == "ue_capture"
    ]
    running = [j for j in caps if j.get("status") == "running"]
    queued = sorted(
        [j for j in caps if j.get("status") == "queued"],
        key=lambda j: str(j.get("created_at") or ""),
    )
    finish_done = remaining_n == 0 and not running and not queued
    assets_by_id = {
        str(a["id"]): a
        for a in register_mod.list_assets()
        if str(a.get("engine") or "").lower() == engine.lower()
    }
    on_disk_rows = []
    for aid, row in (av.get("by_asset_id") or {}).items():
        if not isinstance(row, dict) or row.get("state") != "on_disk":
            continue
        a = assets_by_id.get(aid) or {}
        on_disk_rows.append(
            {
                "asset_id": aid,
                "display_name": str(a.get("display_name") or aid),
                "detail": str(row.get("detail") or ""),
            }
        )
    on_disk_rows.sort(key=lambda r: r["display_name"].lower())
    return {
        "schema_version": 1,
        "generated_at": _now(),
        "engine": engine,
        "operator": {
            "responsibility": "none",
            "redeem": "closed",
            "how_to_watch": "http://192.168.68.93:8770/ — Live ops strip",
        },
        "finish": {
            "done": finish_done,
            "percent_complete": inventory_percent,
            "ready": ready_n,
            "remaining": remaining_n,
            "total": total_n,
        },
        "counts": counts,
        "capture": {
            "running": [
                _capture_job_progress(j, include_lookdev=False) for j in running
            ],
            "queued": [
                {
                    "asset_id": j.get("asset_id"),
                    "job_id": j.get("job_id"),
                    "status": j.get("status"),
                    "percent": 0,
                    "phase": "queued",
                }
                for j in queued
            ],
        },
        "on_disk_need_lookdev": on_disk_rows[:12],
        "host": _host_utilization(host_id),
        "pipeline": {
            "ue_capture_slots": 1,
            "ue_capture_reason": "one UnrealEditor per .uproject (DDC/asset locks)",
            "sidecar_kinds": [
                "host_fab_install",
                "host_scan",
                "ue_stage",
                "host_stage",
            ],
            "auto_drain": True,
        },
    }


def _host_utilization(host_id: str | None = None) -> dict[str, Any]:
    """Last agent-reported Aurora util (nvidia-smi + editor) — cheap for pulse."""
    try:
        host = ue_hosts_mod.get_host(host_id)
        hid = str(host.get("id") or "aurora")
    except Exception:  # noqa: BLE001
        hid = (host_id or "aurora").strip().lower() or "aurora"
    doc = ue_hosts_mod.load_host_specs(hid) or {}
    specs = doc.get("specs") if isinstance(doc, dict) else None
    if not isinstance(specs, dict):
        specs = {}
    util = specs.get("utilization") if isinstance(specs.get("utilization"), dict) else {}
    lw = specs.get("lookdev_worker") if isinstance(specs.get("lookdev_worker"), dict) else {}
    return {
        "host_id": hid,
        "updated_at": util.get("updated_at") or doc.get("updated_at"),
        "gpu_name": util.get("gpu_name") or specs.get("gpu_name"),
        "gpu_util_pct": util.get("gpu_util_pct"),
        "gpu_mem_used_mb": util.get("gpu_mem_used_mb"),
        "gpu_mem_total_mb": util.get("gpu_mem_total_mb"),
        "editor_rss_mb": util.get("editor_rss_mb"),
        "worker_busy": lw.get("busy") if "busy" in lw else util.get("worker_busy"),
        "worker_ok": lw.get("worker_ok"),
        "worker_version": lw.get("worker_version"),
        "idle_tax": util.get("idle_tax"),
    }


def drain_on_disk_lookdev(
    *,
    engine: str = "unreal",
    host_id: str | None = None,
    limit: int = 2,
) -> dict[str, Any]:
    """Keep the warm Lookdev Worker fed — enqueue on-disk packs needing lookdev.

    Does not invent a second UnrealEditor. Saturation = queue depth + sidecar
    Windows jobs (Fab/scan) while the single MRQ slot runs.
    """
    from . import jobs as jobs_mod

    limit = max(1, min(int(limit), 8))
    av = availability_index(engine=engine, host_id=host_id)
    by = av.get("by_asset_id") or {}
    assets = {
        str(a["id"]): a
        for a in register_mod.list_assets()
        if str(a.get("engine") or "").lower() == engine.lower()
    }
    queued_or_running = 0
    for status in ("queued", "running"):
        for job in jobs_mod.list_jobs(status=status, limit=100):
            if job.get("kind") in {"ue_capture", "derive_lookdev"}:
                queued_or_running += 1
    room = max(0, limit - queued_or_running)
    enqueued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if room <= 0:
        return {
            "schema_version": 1,
            "enqueued": [],
            "skipped": [{"reason": "queue_full", "queued_or_running": queued_or_running}],
            "room": 0,
        }
    # Only lookdev-drain assets that have already completed vault staging.
    # Freshly discovered F: folders must run host_stage first so derive has a
    # raw_location to read from.
    on_disk = [
        aid
        for aid, row in by.items()
        if (
            isinstance(row, dict)
            and row.get("state") == "on_disk"
            and str((assets.get(aid) or {}).get("raw_location") or "").strip()
        )
    ]
    on_disk.sort(
        key=lambda aid: str((assets.get(aid) or {}).get("display_name") or aid).lower()
    )
    for aid in on_disk:
        if len(enqueued) >= room:
            break
        try:
            follow = enqueue_post_stage_lookdev(aid)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"asset_id": aid, "reason": f"error:{exc}"})
            continue
        if not follow:
            skipped.append({"asset_id": aid, "reason": "already_captured_or_noop"})
            continue
        if follow.get("skipped"):
            skipped.append(
                {
                    "asset_id": aid,
                    "reason": follow.get("reason"),
                    "lookdev_mode": follow.get("lookdev_mode"),
                }
            )
            continue
        job = follow.get("job")
        if isinstance(job, dict):
            enqueued.append(
                {
                    "asset_id": aid,
                    "job_id": job.get("job_id"),
                    "kind": job.get("kind"),
                    "lookdev_mode": follow.get("lookdev_mode"),
                }
            )
        else:
            skipped.append({"asset_id": aid, "reason": "no_job"})
    return {
        "schema_version": 1,
        "enqueued": enqueued,
        "skipped": skipped[:20],
        "room": room,
        "on_disk_remaining": max(0, len(on_disk) - len(enqueued)),
    }


def ops_now(*, engine: str = "unreal", host_id: str | None = None) -> dict[str, Any]:
    """Full ops snapshot for OPS_NOW / agents — not for 4s UI polling."""
    pulse = ops_pulse(engine=engine, host_id=host_id)
    av = availability_index(engine=engine, host_id=host_id)
    by = av.get("by_asset_id") or {}
    assets = {
        str(a["id"]): a
        for a in register_mod.list_assets()
        if str(a.get("engine") or "").lower() == engine.lower()
    }

    def names(state: str) -> list[dict[str, str]]:
        rows = []
        for aid, row in by.items():
            if row.get("state") != state:
                continue
            a = assets.get(aid) or {}
            rows.append(
                {
                    "asset_id": aid,
                    "display_name": str(a.get("display_name") or aid),
                    "detail": str(row.get("detail") or ""),
                }
            )
        rows.sort(key=lambda r: r["display_name"].lower())
        return rows

    return {
        **pulse,
        "schema_version": 2,
        "mission": [
            "Finish lookdev for every pack already on F: / vault-staged",
            "texture → derive; Niagara/VFX → single-flight ue_capture MRQ",
            "Do not wait on the operator for agent-owned steps",
            "Need download is unfinished inventory — close via agent Fab/VaultCache install, not UI parking",
            "Unity stays parked",
            "CFD A–F already met — this is post-CFD finish-line ops",
        ],
        "operator": {
            "responsibility": "none",
            "redeem": "closed",
            "how_to_watch": "http://192.168.68.93:8770/ — Live ops strip (poll /api/ops/pulse)",
            "do_not": [
                "Fab Add-to-Project hand grind",
                "redeem keys again",
                "ask chat whether MRQ is done — use Live ops",
            ],
        },
        "finish": {
            **pulse["finish"],
            "criteria": (
                "done when Ready covers all Unreal packs, need_download=0, "
                "on_disk lookdev=0, and no capture running/queued"
            ),
        },
        "coverage": {
            "on_disk_count": int((av.get("counts") or {}).get("ready", 0))
            + int((av.get("counts") or {}).get("on_disk", 0)),
            "vault_staged_count": None,
            "need_download_count": int(
                (av.get("counts") or {}).get("need_download") or 0
            ),
            "vault_installable_count": int(
                (av.get("counts") or {}).get("installable") or 0
            ),
            "orphan_count": None,
        },
        "on_disk_need_lookdev": names("on_disk"),
        "need_download": names("need_download"),
        "ready": names("ready"),
    }


def attach_availability(
    assets: list[dict[str, Any]],
    *,
    engine: str | None = None,
    host_id: str | None = None,
    available: str | None = None,
) -> list[dict[str, Any]]:
    """Annotate asset dicts with availability; optional filter by state."""
    eng = engine
    if not eng:
        engines = {
            str(a.get("engine") or "").lower()
            for a in assets
            if str(a.get("engine") or "").strip()
        }
        eng = "unreal" if engines == {"unreal"} else None
    index = availability_index(engine=eng, host_id=host_id)
    by_id = index.get("by_asset_id") or {}
    want = (available or "").strip().lower() or None
    on_machine = want == "on_machine"
    if want and want not in AVAILABILITY_STATES and not on_machine:
        want = None
    out: list[dict[str, Any]] = []
    for a in assets:
        row = dict(a)
        av = by_id.get(str(a.get("id") or ""))
        if av is None:
            # Unity / unscoped — compute lightly without host scan.
            raw = str(a.get("raw_location") or "").strip()
            staged = bool(raw) and Path(raw).exists()
            av = availability_row(
                on_disk=False,
                staged=staged,
                lookdev=lookdev_satisfied(str(a.get("id") or ""), asset=a),
                installable=False,
                deferred=False,
            )
        row["availability"] = av
        state = str(av.get("state") or "")
        if on_machine:
            if state == "need_download":
                continue
        elif want and state != want:
            continue
        out.append(row)
    return out


def import_status(asset_id: str) -> dict[str, Any]:
    asset = register_mod.get_asset(asset_id)
    if not asset:
        raise KeyError(asset_id)
    raw = str(asset.get("raw_location") or "").strip()
    staged = bool(raw) and Path(raw).exists()
    redeemed = str(asset.get("redemption_status") or "").lower() in {
        "redeemed",
        "owned",
        "claimed",
    }
    in_project = str(asset.get("ue_in_project") or "").lower() in {
        "1",
        "true",
        "yes",
        "in_project",
        "done",
    }
    mode = lookdev_mode_for_asset(asset)
    lookdev_done = lookdev_satisfied(asset_id, asset=asset)
    content_root = str(asset.get("content_root") or "").strip() or None
    host_path = str(asset.get("host_content_path") or "").strip() or None
    lookdev_label = (
        "Captured MRQ lookdev"
        if mode == "niagara_mrq"
        else "Lookdev (derive / Fab thumb)"
    )
    steps = [
        {
            "id": "redeemed",
            "label": "Redeemed (Humble → store)",
            "done": redeemed,
            "actor": "operator",
        },
        {
            "id": "in_project",
            "label": "Add to Project (Fab → AuroraVellum)",
            "done": in_project,
            "actor": "operator",
        },
        {
            "id": "staged",
            "label": "Staged into vault",
            "done": staged,
            "actor": "agent",
        },
        {
            "id": "captured",
            "label": lookdev_label,
            "done": lookdev_done,
            "actor": "agent",
        },
    ]
    next_id = next((s["id"] for s in steps if not s["done"]), None)
    engine = str(asset.get("engine") or "unreal").lower()
    offer_derive = (
        staged
        and not lookdev_done
        and mode == "texture"
        and engine == "unreal"
    )
    offer_capture = (
        staged
        and bool(content_root)
        and engine == "unreal"
        and mode == "niagara_mrq"
        and not lookdev_done
    )
    if mode == "niagara_mrq" and staged and not lookdev_done:
        hint = "Required next: Capture Niagara MRQ (Fab thumb is preview only)"
    elif mode == "texture" and staged and not lookdev_done:
        hint = "Required next: Derive texture / Fab thumbnail stills"
    else:
        hint = None
    return {
        "schema_version": 1,
        "asset_id": asset_id,
        "engine": asset.get("engine"),
        "lookdev_mode": mode,
        "steps": steps,
        "next_step": next_id,
        "raw_location": raw or None,
        "content_root": content_root,
        "host_content_path": host_path,
        "stage_dest": str(stage_dest_for_asset(asset)),
        "scratch_project_hint": asset.get("scratch_project_path")
        or "F:\\Games\\AuroraVellum",
        "ready_to_capture": offer_capture,
        "ready_to_stage": in_project and bool(host_path) and not staged,
        "offer_derive": offer_derive,
        "offer_capture": offer_capture,
        "post_stage_hint": hint,
        "path_verified": bool(host_path)
        and bool(ue_hosts_mod.path_known_in_content_scan(host_path)),
    }


def has_active_lookdev_job(asset_id: str, *, kind: str) -> bool:
    from . import jobs as jobs_mod

    for status in ("queued", "running"):
        for job in jobs_mod.list_jobs(status=status, asset_id=asset_id, limit=50):
            if job.get("kind") == kind:
                return True
    return False


def enqueue_post_stage_lookdev(asset_id: str) -> dict[str, Any] | None:
    """After vault stage succeeds, enqueue the required lookdev job (derive XOR capture).

    Structured chain — not optional / racey. Idempotent if a matching job is active.
    """
    from . import jobs as jobs_mod

    asset = register_mod.get_asset(asset_id)
    if not asset:
        raise KeyError(asset_id)
    st = import_status(asset_id)
    if st.get("steps") and any(
        s.get("id") == "captured" and s.get("done") for s in st["steps"]
    ):
        return None
    mode = st.get("lookdev_mode") or lookdev_mode_for_asset(asset)
    if mode == "niagara_mrq":
        if not st.get("content_root"):
            return {
                "skipped": True,
                "reason": "content_root_missing",
                "lookdev_mode": mode,
            }
        if has_active_lookdev_job(asset_id, kind="ue_capture"):
            return {"skipped": True, "reason": "ue_capture_already_active", "lookdev_mode": mode}
        host = ue_hosts_mod.get_host()
        job = jobs_mod.enqueue_job(
            kind="ue_capture",
            asset_id=asset_id,
            step_id="scratch_inspect",
            payload={
                "source": "post_stage_lookdev",
                "lane": "slots",
                "project_path": host.get("project_dir") or r"F:\Games\AuroraVellum",
                "content_root": st["content_root"],
                "engine_version": host.get("engine_version") or "5.8",
                "ue_host": host.get("id") or "aurora",
                "force": False,
                "max_systems": 0,
                "lookdev_mode": mode,
            },
        )
        return {"lookdev_mode": mode, "job": job}
    if has_active_lookdev_job(asset_id, kind="derive_lookdev"):
        return {"skipped": True, "reason": "derive_already_active", "lookdev_mode": mode}
    job = jobs_mod.enqueue_job(
        kind="derive_lookdev",
        asset_id=asset_id,
        step_id="derive_lookdev",
        payload={
            "source": "post_stage_lookdev",
            "lanes": ["slots", "hail-overlay"],
            "lookdev_mode": mode,
        },
    )
    return {"lookdev_mode": mode, "job": job}


def apply_stage_upload(
    asset_id: str,
    *,
    archive_path: Path,
    host_content_path: str,
    content_folder_name: str | None = None,
) -> dict[str, Any]:
    """Extract uploaded Content folder zip into vault and patch register."""
    asset = register_mod.get_asset(asset_id)
    if not asset:
        raise KeyError(asset_id)
    dest = stage_dest_for_asset(asset)
    if dest.exists():
        try:
            shutil.rmtree(dest)
        except OSError:
            # Rebuild into a fresh stamp dir if vault path is sticky/permissions-odd.
            dest = dest.parent / f"{dest.name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    dest.mkdir(parents=True, exist_ok=True)

    folder = (content_folder_name or "").strip()
    if not folder:
        # Infer from host path: .../Content/FireworksV1
        parts = Path(host_content_path.replace("\\", "/")).parts
        folder = parts[-1] if parts else asset_id

    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(dest)

    # If zip contained a single top-level dir, flatten optional — keep as-is for fidelity.
    file_count = sum(1 for p in dest.rglob("*") if p.is_file())
    content_root = content_root_from_folder_name(folder)
    updated = register_mod.patch_asset(
        asset_id,
        raw_location=str(dest),
        content_root=content_root,
        host_content_path=host_content_path,
        ue_in_project="in_project",
        intake_notes=f"Staged from host {host_content_path} ({file_count} files) at {_now()}",
    )
    follow = None
    try:
        follow = enqueue_post_stage_lookdev(asset_id)
    except Exception as exc:  # noqa: BLE001
        follow = {"error": str(exc)}
    return {
        "asset": updated,
        "raw_location": str(dest),
        "content_root": content_root,
        "file_count": file_count,
        "host_content_path": host_content_path,
        "post_stage_lookdev": follow,
    }


def import_queue(*, engine: str | None = "unreal", limit: int = 40) -> dict[str, Any]:
    """Actionable import/lookdev work first — never lead with Epic-wall downloads.

    Disk truth comes from ``availability_index`` (F: + vault stage + lookdev).
    Packs that are only ``need_download`` sit in ``blocked_epic`` and do not
    inflate the primary ``count`` / Start-next queue.
    """
    assets = register_mod.list_assets()
    if engine:
        assets = [a for a in assets if str(a.get("engine") or "").lower() == engine.lower()]
    av = availability_index(engine=engine or "unreal")
    by = av.get("by_asset_id") or {}

    actionable: list[dict[str, Any]] = []
    blocked_epic: list[dict[str, Any]] = []
    deferred_epic: list[dict[str, Any]] = []
    for a in assets:
        aid = str(a["id"])
        if _is_inactive_asset(a):
            continue
        row = by.get(aid) or {}
        state = str(row.get("state") or "need_download")
        detail = str(row.get("detail") or "")
        if state == "ready":
            continue
        if state == "deferred":
            acq = fab_library_mod.acquisition_for_asset(a)
            deferred_epic.append(
                {
                    "asset_id": aid,
                    "display_name": a.get("display_name") or aid,
                    "engine": a.get("engine"),
                    "availability": state,
                    "detail": detail,
                    "next_step": acq["method"],
                    "acquisition": acq,
                    "blocked": False,
                }
            )
            continue
        if state == "need_download":
            acq = fab_library_mod.acquisition_for_asset(a)
            blocked_epic.append(
                {
                    "asset_id": aid,
                    "display_name": a.get("display_name") or aid,
                    "engine": a.get("engine"),
                    "availability": state,
                    "detail": detail,
                    # Fab UE listings have no standalone download; the launcher
                    # metadata tells us the real acquisition path per pack.
                    "next_step": acq["method"],
                    "acquisition": acq,
                    "blocked": True,
                }
            )
            continue
        if state == "installable":
            next_step = "in_project"
        elif state == "on_disk":
            next_step = "staged" if "stage" in detail else "captured"
        elif state == "vault":
            next_step = "captured" if "awaiting conversion" in detail else "in_project"
        else:
            next_step = "captured"
        actionable.append(
            {
                "asset_id": aid,
                "display_name": a.get("display_name") or aid,
                "engine": a.get("engine"),
                "availability": state,
                "detail": detail,
                "next_step": next_step,
                "blocked": False,
            }
        )

    rank = {"on_disk": 0, "installable": 1, "vault": 2}
    step_rank = {"captured": 0, "staged": 1, "in_project": 2}
    actionable.sort(
        key=lambda r: (
            rank.get(str(r.get("availability")), 9),
            step_rank.get(str(r.get("next_step")), 9),
            str(r.get("display_name") or "").lower(),
        )
    )
    blocked_epic.sort(key=lambda r: str(r.get("display_name") or "").lower())
    deferred_epic.sort(key=lambda r: str(r.get("display_name") or "").lower())
    lim = max(1, min(limit, 100))
    return {
        "schema_version": 1,
        "engine": engine,
        "items": actionable[:lim],
        "count": len(actionable),
        "blocked_epic": blocked_epic[:lim],
        "blocked_epic_count": len(blocked_epic),
        "deferred_epic": deferred_epic[:lim],
        "deferred_epic_count": len(deferred_epic),
    }


# Content folder name on Aurora → register asset id (Humble + known frees).
KNOWN_FOLDER_MAP: dict[str, str] = {
    "ContainerCity": "container-city",
    "Dark_Village": "dark-village",
    "ExplosionVFX-2": "explosion-vfx-2",
    "FabricBundle": "fabric-bundle-material",
    "FireworksV1": "fireworks-vol-1-niagara",
    "Garage": "industrial-warehouse-night-environment-garage",
    "GasExplosionVFX": "gas-explosion-vfx",
    "GroundExplosionVFX": "ground-explosion-vfx",
    "Steampunk_Zepline_Station": "steampunk-zeppelin-station-victorian-airship-terminal-modular-environment",
    "ToonAbilitiesVol1": "toon-abilities-vol-1-niagara",
    "Scifi_desert_city": "science-fiction-desert-city-kit",
    "SlashTrail_SoftTofu": "slash-trail-fx-elemental",
    "MetalMaterial3": "metal-material-3",
    "Hangar-X": "hangar-x",
    "HangarX": "hangar-x",
    "JapaneseOldShoppingMall": "japanese-old-shopping-mall-interior-environment",
    "MotelRoomInterior": "motel-room-interior-environment",
    "MagicCastVFX": "magic-cast-vfx",
    "MagicAbilitiesV3": "magic-abilities-vol-3-niagara",
    "MagicProjectilesVol3": "magic-projectiles-vol-3-niagara",
    "PortalVFXEnhanced": "portal-vfx-enhanced",
    "StylizedVFX-Water": "stylized-vfx-water",
    "NiagaraMegaPackVol3": "niagara-mega-pack-vol-3",
    "Match3RPGTemplate": "match-3-rpg-template",
    "Dungeon_Ruins": "dungeon-ruins",
    "DungeonRuins": "dungeon-ruins",
    "Arabic_Dock": "arabic-dock",
    "CappadociaAnatolianCaveEnvironment": "cappadocia-anatolian-cave-hotel-environment",
    "DirtyWall": "master-mega-dirty-wall-pack-material-4k",
    "GlassBundle": "glass-bundle-material",
    "Liope_Tr": "oil-rig-liope",
    "MiddleEastern": "middle-eastern-town",
    "MotelReceptionInterior": "motel-reception-interior-environment",
    "Warehouse": "vertical-warehouse",
    # Epic Fab folder spelling
    "Cyperpunk_Clinic": "cyberpunk-hospital-cyberpunk-clinic-modular-cyberpunk-environment",
    "Cyberpunk_Clinic": "cyberpunk-hospital-cyberpunk-clinic-modular-cyberpunk-environment",
    "CyberpunkHospital": "cyberpunk-hospital-cyberpunk-clinic-modular-cyberpunk-environment",
    "MegaMarbleMaterial": "mega-marble-material-4k",
    "Mansion": "the-lords-mansion",
}

# Tooling / engine noise under Content — not purchasable packs to Register & Stage.
SKIP_FOLDERS = frozenset(
    {
        "Vellum",
        "Collections",
        "Developers",
        "BefourStudios",
        "Fab",
        "Python",
        "Movies",
        "Cinematics",
        "__ExternalActors__",
        "__ExternalObjects__",
        "Developers",
    }
)

ROOT = Path(__file__).resolve().parents[1]
FAB_INSTALL_MAP_PATH = ROOT / "config" / "fab-vault-install-map.json"


def load_fab_install_map() -> dict[str, Any]:
    if not FAB_INSTALL_MAP_PATH.is_file():
        return {"schema_version": 1, "assets": {}}
    import json

    return json.loads(FAB_INSTALL_MAP_PATH.read_text(encoding="utf-8"))


def fab_install_candidates(asset_id: str) -> list[str]:
    """Relative Content paths the agent should look for under VaultCache."""
    assets = load_fab_install_map().get("assets") or {}
    row = assets.get(asset_id) if isinstance(assets, dict) else None
    if not isinstance(row, dict):
        return []
    paths = row.get("content_rel_paths") or []
    return [str(p).strip() for p in paths if str(p).strip()]


def folder_to_asset_id_map() -> dict[str, str]:
    """Content folder name → asset id (static map + live register)."""
    mapping = dict(KNOWN_FOLDER_MAP)
    for a in register_mod.list_assets():
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id") or "").strip()
        if not aid:
            continue
        folder = str(a.get("content_folder_name") or "").strip()
        if folder:
            mapping[folder] = aid
        hcp = str(a.get("host_content_path") or "").strip().replace("/", "\\")
        if hcp:
            leaf = hcp.rstrip("\\").split("\\")[-1]
            if leaf:
                mapping[leaf] = aid
        cr = str(a.get("content_root") or "").strip()
        if cr.startswith("/Game/"):
            top = cr[len("/Game/") :].split("/")[0].strip()
            if top:
                mapping[top] = aid
    return mapping


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def resolve_folder_to_asset_id(
    folder: str, *, folder_map: dict[str, str] | None = None
) -> str | None:
    """Map a Content folder name to a register id, with fuzzy fallback.

    Exact map first. If missing, match against register ids / display names by
    stripping non-alphanumerics so ``MegaMarbleMaterial`` lands on
    ``mega-marble-material-4k`` instead of inventing a duplicate orphan row.
    Prefer the longest / most specific register match so short false positives
    (e.g. ``Mega``) do not win.
    """
    name = (folder or "").strip()
    if not name:
        return None
    fmap = folder_map if folder_map is not None else folder_to_asset_id_map()
    if name in fmap and register_mod.get_asset(fmap[name]):
        return fmap[name]

    needle = _alnum(name)
    if len(needle) < 6:
        return None
    best: tuple[int, str] | None = None
    for a in register_mod.list_assets():
        if not isinstance(a, dict):
            continue
        if str(a.get("engine") or "").lower() not in {"", "unreal"}:
            continue
        aid = str(a.get("id") or "").strip()
        if not aid:
            continue
        candidates = [
            _alnum(aid),
            _alnum(str(a.get("display_name") or "")),
            _alnum(str(a.get("content_folder_name") or "")),
        ]
        for cand in candidates:
            if not cand:
                continue
            score = 0
            if cand == needle:
                score = 1000 + len(cand)
            elif needle.startswith(cand) or cand.startswith(needle):
                # Require shared prefix of meaningful length.
                shared = min(len(needle), len(cand))
                if shared < 8:
                    continue
                score = 700 + shared
            elif needle in cand or cand in needle:
                shared = min(len(needle), len(cand))
                if shared < 10:
                    continue
                score = 500 + shared
            if score > 0 and (best is None or score > best[0]):
                best = (score, aid)
    return best[1] if best else None


def pretty_folder_name(folder: str) -> str:
    """Hangar-X / MagicCastVFX → readable display name."""
    raw = (folder or "").strip()
    if not raw:
        return "Untitled pack"
    spaced = re.sub(r"[-_]+", " ", raw)
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    return " ".join(spaced.split()) or raw


def coverage(*, engine: str = "unreal", host_id: str | None = None) -> dict[str, Any]:
    """Reconcile register vs host Content scan vs vault stage.

    Avoids per-asset lookdev catalog scans (those belong on import_status /
    checklist detail). Coverage is inventory truth: F: folders vs vault stage.
    """
    from . import ue_hosts as ue_hosts_mod

    assets = register_mod.list_assets()
    if engine:
        assets = [a for a in assets if str(a.get("engine") or "").lower() == engine.lower()]
    folders = ue_hosts_mod.list_content_folders(host_id).get("folders") or []
    folder_by_name = {
        str(f.get("name") or ""): f for f in folders if isinstance(f, dict) and f.get("name")
    }
    folder_map = folder_to_asset_id_map()

    staged_by_id: dict[str, str | None] = {}
    for a in assets:
        aid = str(a["id"])
        raw = str(a.get("raw_location") or "").strip()
        if raw and Path(raw).exists():
            staged_by_id[aid] = raw

    on_disk: list[dict[str, Any]] = []
    orphans: list[dict[str, Any]] = []
    for name, f in sorted(folder_by_name.items()):
        if name in SKIP_FOLDERS:
            continue
        aid = resolve_folder_to_asset_id(name, folder_map=folder_map)
        if aid and register_mod.get_asset(aid):
            on_disk.append(
                {
                    "folder": name,
                    "path": f.get("path"),
                    "asset_id": aid,
                    "staged": aid in staged_by_id,
                    "next_step": None if aid in staged_by_id else "staged",
                }
            )
        else:
            orphans.append(
                {
                    "folder": name,
                    "path": f.get("path"),
                    "hint": "Free/extra on F: — Register & Stage from coverage",
                }
            )

    mapped_ids = {row["asset_id"] for row in on_disk}
    need_download: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    vault_installable: list[dict[str, Any]] = []
    staged: list[dict[str, Any]] = []
    for a in assets:
        aid = str(a["id"])
        if _is_inactive_asset(a):
            continue
        if aid in staged_by_id:
            staged.append(
                {
                    "asset_id": aid,
                    "display_name": a.get("display_name"),
                    "raw_location": staged_by_id[aid],
                }
            )
            continue
        if aid in mapped_ids:
            continue
        cands = fab_install_candidates(aid)
        acq = fab_library_mod.acquisition_for_asset(a, installable=bool(cands))
        row = {
            "asset_id": aid,
            "display_name": a.get("display_name"),
            "list_index": a.get("list_index"),
            "source_bundle": a.get("source_bundle"),
            "next_step": acq["method"],
            "fab_install_candidates": cands,
            "acquisition": acq,
        }
        if cands:
            vault_installable.append(row)
        if acq.get("deferred"):
            deferred.append(row)
        else:
            need_download.append(row)

    return {
        "schema_version": 1,
        "engine": engine,
        "on_disk": on_disk,
        "on_disk_count": len(on_disk),
        "orphans": orphans,
        "orphan_count": len(orphans),
        "vault_staged": staged,
        "vault_staged_count": len(staged),
        "need_download": need_download,
        "need_download_count": len(need_download),
        "deferred": deferred,
        "deferred_count": len(deferred),
        "vault_installable": vault_installable,
        "vault_installable_count": len(vault_installable),
        "known_folder_map": folder_map,
    }


def enqueue_fab_install(
    asset_id: str,
    *,
    ue_host: str | None = None,
    auto_stage: bool = True,
) -> dict[str, Any]:
    """Enqueue Aurora host_fab_install (VaultCache → project Content)."""
    from . import jobs as jobs_mod

    asset = register_mod.get_asset(asset_id)
    if asset is None:
        raise KeyError(asset_id)
    cands = fab_install_candidates(asset_id)
    if not cands:
        raise ValueError("no_fab_install_map")
    try:
        host = ue_hosts_mod.get_host(ue_host) if ue_host else ue_hosts_mod.get_host()
        host_id = host.get("id")
        specs = host.get("host_specs") or {}
        project_content = specs.get("content_root_path")
        if not project_content and host.get("project_dir"):
            project_content = str(Path(str(host["project_dir"])) / "Content")
    except Exception:  # noqa: BLE001
        host_id = ue_host or "aurora"
        project_content = r"F:\Games\AuroraVellum\Content"
    job = jobs_mod.enqueue_job(
        kind="host_fab_install",
        asset_id=asset_id,
        step_id="fab_install",
        payload={
            "source": "api_fab_install",
            "ue_host": host_id,
            "content_rel_paths": cands,
            "project_content": project_content,
            "auto_stage": bool(auto_stage),
        },
    )
    return {"job": job, "import": import_status(asset_id), "candidates": cands}


def register_orphan(
    *,
    folder: str,
    path: str,
    ue_host: str | None = None,
    auto_stage: bool = True,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Register one Content orphan (free Fab pack) and optionally enqueue stage."""
    from . import jobs as jobs_mod
    from . import ue_hosts as ue_hosts_mod

    name = (folder or "").strip()
    host_path = (path or "").strip()
    if not name or not host_path:
        raise ValueError("folder_and_path_required")
    if name in SKIP_FOLDERS:
        raise ValueError("skip_folder")

    match = ue_hosts_mod.path_known_in_content_scan(host_path, ue_host)
    if not match:
        raise ValueError("host_path_not_in_scan")

    existing_map = folder_to_asset_id_map()
    aid = resolve_folder_to_asset_id(name, folder_map=existing_map)
    if aid and register_mod.get_asset(aid):
        asset = register_mod.patch_asset(
            aid,
            host_content_path=host_path,
            ue_in_project="in_project",
            content_root=content_root_from_folder_name(name),
            content_folder_name=name,
            redemption_status="owned",
        )
    else:
        asset = register_mod.create_asset(
            display_name=(display_name or pretty_folder_name(name)).strip(),
            content_folder_name=name,
            host_content_path=host_path,
            tags=["epic-free-or-extra", "fab-orphan"],
        )
        aid = str(asset["id"])

    try:
        host = ue_hosts_mod.get_host(ue_host) if ue_host else ue_hosts_mod.get_host()
        host_id = host.get("id")
    except Exception:  # noqa: BLE001
        host_id = ue_host or "aurora"

    stage_job = None
    if auto_stage:
        stage_job = jobs_mod.enqueue_job(
            kind="host_stage",
            asset_id=aid,
            step_id="stage_vault",
            payload={
                "source": "api_register_orphan",
                "host_content_path": host_path,
                "content_folder_name": name,
                "ue_host": host_id,
                "engine": "unreal",
            },
        )
    return {
        "asset": asset,
        "job": stage_job,
        "import": import_status(aid),
    }


def register_orphans_batch(
    *,
    ue_host: str | None = None,
    auto_stage: bool = True,
    folders: list[str] | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Register & stage Content orphans from latest host scan."""
    cov = coverage(engine="unreal", host_id=ue_host)
    want = {f.strip() for f in (folders or []) if f and f.strip()} or None
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for orphan in cov.get("orphans") or []:
        if len(results) >= limit:
            break
        folder = str(orphan.get("folder") or "")
        path = str(orphan.get("path") or "")
        if want is not None and folder not in want:
            continue
        try:
            results.append(
                register_orphan(
                    folder=folder,
                    path=path,
                    ue_host=ue_host,
                    auto_stage=auto_stage,
                )
            )
        except (ValueError, KeyError) as exc:
            errors.append({"folder": folder, "error": str(exc)})
    return {
        "schema_version": 1,
        "registered": len(results),
        "results": results,
        "errors": errors,
        "orphan_count_before": cov.get("orphan_count"),
    }
