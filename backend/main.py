"""Vellum API — Control Alt Games asset vault register + intake propose."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import zipfile

from . import attach as attach_mod
from . import eidolon as eidolon_mod
from . import fab_library as fab_library_mod
from . import game_ready as game_ready_mod
from . import import_flow as import_flow_mod
from . import intake as intake_mod
from . import jobs as jobs_mod
from . import lookdev as lookdev_mod
from . import mneme as mneme_mod
from . import register as register_mod
from . import research as research_mod
from . import scratch as scratch_mod
from . import ue_hosts as ue_hosts_mod

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    register_mod.ensure_register()
    yield


app = FastAPI(
    title="Vellum",
    description="Control Alt Games asset vault — register, intake, jobs, lookdev derive.",
    version="0.4.0",
    lifespan=lifespan,
)


class IntakeProposeRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(default="operator", max_length=120)
    note: str | None = Field(default=None, max_length=2000)


class IntakeStepPatchRequest(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=4000)


class JobEnqueueRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    asset_id: str | None = Field(default=None, max_length=200)
    intake_run_id: str | None = Field(default=None, max_length=200)
    step_id: str | None = Field(default=None, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)


class AssetPatchRequest(BaseModel):
    redemption_status: str | None = Field(default=None, max_length=64)
    raw_location: str | None = Field(default=None, max_length=1000)
    intake_notes: str | None = Field(default=None, max_length=4000)
    scratch_project_path: str | None = Field(default=None, max_length=1000)
    scratch_project_status: str | None = Field(default=None, max_length=64)
    scratch_engine_version: str | None = Field(default=None, max_length=64)
    scratch_notes: str | None = Field(default=None, max_length=4000)
    content_root: str | None = Field(default=None, max_length=200)
    host_content_path: str | None = Field(default=None, max_length=1000)
    content_folder_name: str | None = Field(default=None, max_length=200)
    ue_in_project: str | None = Field(default=None, max_length=64)


class AssetCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=300)
    asset_id: str | None = Field(default=None, max_length=200)
    engine: str = Field(default="unreal", max_length=32)
    package_type: str = Field(default="Unreal Engine pack", max_length=120)
    store_lane: str = Field(default="epic-games-store", max_length=64)
    store_label: str = Field(default="Epic Games Store (free / extra)", max_length=120)
    source_bundle: str = Field(default="epic-free-or-extra", max_length=120)
    project_fit: str = Field(default="", max_length=4000)
    content_folder_name: str | None = Field(default=None, max_length=200)
    host_content_path: str | None = Field(default=None, max_length=1000)
    tags: list[str] | None = None


class ImportMarkRequest(BaseModel):
    step: str = Field(min_length=1, max_length=32)
    host_content_path: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)


class ImportStageRequest(BaseModel):
    host_content_path: str = Field(min_length=3, max_length=1000)
    content_folder_name: str | None = Field(default=None, max_length=200)
    ue_host: str | None = Field(default=None, max_length=64)


class ImportFabInstallRequest(BaseModel):
    ue_host: str | None = Field(default=None, max_length=64)
    auto_stage: bool = Field(
        default=True,
        description="After VaultCache→Content copy, enqueue host_stage",
    )


class ImportFabInstallBatchRequest(BaseModel):
    ue_host: str | None = Field(default=None, max_length=64)
    auto_stage: bool = Field(default=True)
    limit: int = Field(default=20, ge=1, le=50)


class ImportRegisterOrphansRequest(BaseModel):
    ue_host: str | None = Field(default=None, max_length=64)
    auto_stage: bool = Field(default=True)
    folders: list[str] | None = None
    limit: int = Field(default=40, ge=1, le=80)


class LookdevDeriveRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=200)
    lanes: list[str] | None = None
    intake_run_id: str | None = Field(default=None, max_length=200)


class GameReadyIngestManifestRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=200)
    pack: str | None = Field(default=None, max_length=200)
    manifest_path: str = Field(min_length=1, max_length=2000)


class GameReadyPublishRequest(BaseModel):
    lane: str = Field(min_length=1, max_length=64)
    presentation: dict[str, Any] | None = Field(default=None)


class AttachRequest(BaseModel):
    target: str = Field(min_length=1, max_length=32)
    derived_output_id: str | None = Field(default=None, max_length=200)
    asset_id: str | None = Field(default=None, max_length=200)
    register_glyph: bool = True


class UeCaptureRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=200)
    lane: str = Field(default="slots", max_length=64)
    project_path: str | None = Field(default=None, max_length=1000)
    content_root: str | None = Field(default=None, max_length=200)
    engine_version: str | None = Field(default="5.8", max_length=64)
    intake_run_id: str | None = Field(default=None, max_length=200)
    force: bool = Field(
        default=False,
        description="Re-render even when vault or local MRQ already has lookdev for the system.",
    )
    max_systems: int = Field(
        default=0,
        ge=0,
        le=500,
        description="0 = entire pack (default). Positive N is debug-only: limit picked systems.",
    )


class UeHostSpecsRequest(BaseModel):
    host_id: str = Field(min_length=1, max_length=64)
    specs: dict[str, Any]


class JobClaimRequest(BaseModel):
    kinds: list[str] = Field(default_factory=lambda: ["ue_capture"])


class JobReportRequest(BaseModel):
    result: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=4000)
    scratch_project_path: str | None = Field(default=None, max_length=1000)
    engine_version: str | None = Field(default=None, max_length=64)


class JobProgressRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    log_tail: str | None = Field(default=None, max_length=12000)


class ScratchRecordRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=200)
    scratch_project_path: str = Field(min_length=1, max_length=1000)
    engine_version: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=4000)
    intake_run_id: str | None = Field(default=None, max_length=200)


class VisualResearchPatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    caption: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None
    source_url: str | None = Field(default=None, max_length=2000)
    captured_at: str | None = Field(default=None, max_length=64)
    rights: str | None = Field(default=None, max_length=500)
    attribution: str | None = Field(default=None, max_length=1000)


def _require_research_write(authorization: str | None) -> None:
    try:
        research_mod.require_write_token(authorization)
    except PermissionError:
        raise HTTPException(
            status_code=403, detail="visual_research_read_only"
        ) from None


@app.get("/api/health")
def health() -> dict[str, Any]:
    summary = register_mod.register_summary()
    runs = intake_mod.list_runs(limit=5)
    queued = jobs_mod.list_jobs(status="queued", limit=20)
    derived = lookdev_mod.list_outputs(limit=5)
    return {
        "ok": True,
        "app": "vellum",
        "brand_family": "control-alt-games",
        "register": summary,
        "intake_runs_recent": len(runs),
        "jobs_queued": len(queued),
        "derived_outputs_recent": len(derived),
    }


@app.get("/api/register/summary")
def api_register_summary() -> dict[str, Any]:
    return register_mod.register_summary()


@app.get("/api/assets")
def api_list_assets(
    q: str | None = Query(default=None),
    engine: str | None = Query(default=None),
    lane: str | None = Query(default=None),
    redeem_window: str | None = Query(default=None, alias="redeem"),
    available: str | None = Query(default=None),
    lite: bool = Query(default=False),
) -> dict[str, Any]:
    assets = register_mod.list_assets(q=q, engine=engine, redeem_window_filter=redeem_window)
    if lane:
        l_low = lane.lower()
        assets = [
            a for a in assets
            if l_low in lookdev_mod.infer_lanes(a.get("project_fit"))
            or l_low in [str(x).lower() for x in (a.get("lanes") or [])]
        ]
    assets = import_flow_mod.attach_availability(
        assets, engine=engine, available=available
    )
    if lite:
        thin = []
        for a in assets:
            av = a.get("availability") if isinstance(a.get("availability"), dict) else {}
            thin.append(
                {
                    "id": a.get("id"),
                    "display_name": a.get("display_name"),
                    "engine": a.get("engine"),
                    "package_type": a.get("package_type"),
                    "project_fit": a.get("project_fit"),
                    "availability": {
                        "state": av.get("state"),
                        "label": av.get("label"),
                        "detail": av.get("detail"),
                    },
                }
            )
        assets = thin
    return {
        "schema_version": 1,
        "count": len(assets),
        "assets": assets,
        "lite": lite,
    }


@app.get("/api/import/availability")
def api_import_availability(
    engine: str = Query(default="unreal"),
    host_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Bulk Ready / On disk / Vault / Installable / Need download for list UI."""
    return import_flow_mod.availability_index(engine=engine, host_id=host_id)


@app.get("/api/ops/pulse")
def api_ops_pulse(
    engine: str = Query(default="unreal"),
    host_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Cheap Live-ops / homepage poll (counts + capture heartbeats)."""
    return import_flow_mod.ops_pulse(engine=engine, host_id=host_id)


@app.get("/api/ops/now")
def api_ops_now(
    engine: str = Query(default="unreal"),
    host_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Binding live ops snapshot (mission + scoreboard + capture queue)."""
    return import_flow_mod.ops_now(engine=engine, host_id=host_id)


@app.post("/api/ops/drain")
def api_ops_drain(
    engine: str = Query(default="unreal"),
    host_id: str | None = Query(default=None),
    limit: int = Query(default=2, ge=1, le=8),
) -> dict[str, Any]:
    """Auto-enqueue on-disk lookdev so the warm GPU editor is never starved idle."""
    return import_flow_mod.drain_on_disk_lookdev(
        engine=engine, host_id=host_id, limit=limit
    )


@app.post("/api/assets")
def api_create_asset(body: AssetCreateRequest) -> dict[str, Any]:
    """Register a free/extra Epic pack that is not in the Humble seed inventory."""
    try:
        asset = register_mod.create_asset(
            display_name=body.display_name,
            asset_id=body.asset_id,
            engine=body.engine,
            package_type=body.package_type,
            store_lane=body.store_lane,
            store_label=body.store_label,
            source_bundle=body.source_bundle,
            project_fit=body.project_fit,
            content_folder_name=body.content_folder_name,
            host_content_path=body.host_content_path,
            tags=body.tags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"schema_version": 1, "asset": asset}


@app.get("/api/import/coverage")
def api_import_coverage(
    engine: str = Query(default="unreal"),
    host_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """On-disk vs vault-staged vs still need Fab download (+ Content orphans)."""
    return import_flow_mod.coverage(engine=engine, host_id=host_id)


@app.get("/api/import/queue")
def api_import_queue(
    engine: str | None = Query(default="unreal"),
    limit: int = Query(default=40, ge=1, le=100),
) -> dict[str, Any]:
    return import_flow_mod.import_queue(engine=engine, limit=limit)


@app.post("/api/import/fab-listings-db")
async def api_import_fab_listings_db(
    db: UploadFile = File(...),
) -> dict[str, Any]:
    """Aurora pushes the launcher's Fab library catalog (listings_v1.db).

    This is the launcher's own record of what the account owns, whether the
    launcher has seen each pack, and each pack's download format — used to
    give per-pack acquisition instructions instead of a generic "download".
    """
    data = await db.read()
    try:
        dest = fab_library_mod.save_listings_db(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    index = fab_library_mod.library_index(force_refresh=True)
    import_flow_mod.clear_ops_caches()
    return {
        "schema_version": 1,
        "saved_to": str(dest),
        "listing_count": len(index),
    }


@app.get("/api/assets/{asset_id}")
def api_get_asset(asset_id: str) -> dict[str, Any]:
    asset = register_mod.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="asset_not_found")
    return asset


@app.patch("/api/assets/{asset_id}")
def api_patch_asset(asset_id: str, body: AssetPatchRequest) -> dict[str, Any]:
    fields = (
        "redemption_status",
        "raw_location",
        "intake_notes",
        "scratch_project_path",
        "scratch_project_status",
        "scratch_engine_version",
        "scratch_notes",
        "content_root",
        "host_content_path",
        "content_folder_name",
        "ue_in_project",
    )
    if all(getattr(body, field) is None for field in fields):
        raise HTTPException(status_code=400, detail="no_fields")
    try:
        return register_mod.patch_asset(
            asset_id,
            redemption_status=body.redemption_status,
            raw_location=body.raw_location,
            intake_notes=body.intake_notes,
            scratch_project_path=body.scratch_project_path,
            scratch_project_status=body.scratch_project_status,
            scratch_engine_version=body.scratch_engine_version,
            scratch_notes=body.scratch_notes,
            content_root=body.content_root,
            host_content_path=body.host_content_path,
            content_folder_name=body.content_folder_name,
            ue_in_project=body.ue_in_project,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="asset_not_found") from None


@app.get("/api/assets/{asset_id}/import")
def api_asset_import_status(asset_id: str) -> dict[str, Any]:
    try:
        return import_flow_mod.import_status(asset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="asset_not_found") from None


@app.post("/api/assets/{asset_id}/import/mark")
def api_asset_import_mark(asset_id: str, body: ImportMarkRequest) -> dict[str, Any]:
    """Operator buttons: redeemed | in_project (path must appear in latest host_scan)."""
    if register_mod.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    step = body.step.strip().lower()
    kwargs: dict[str, Any] = {}
    if body.notes:
        kwargs["intake_notes"] = body.notes
    if body.host_content_path:
        kwargs["host_content_path"] = body.host_content_path.strip()
    if step == "redeemed":
        kwargs["redemption_status"] = "redeemed"
    elif step == "in_project":
        host_path = (kwargs.get("host_content_path") or "").strip()
        if not host_path:
            existing = register_mod.get_asset(asset_id) or {}
            host_path = str(existing.get("host_content_path") or "").strip()
        if not host_path:
            raise HTTPException(
                status_code=400,
                detail="host_content_path_required",
            )
        match = ue_hosts_mod.path_known_in_content_scan(host_path)
        if not match:
            raise HTTPException(
                status_code=400,
                detail="host_path_not_in_scan",
            )
        kwargs["host_content_path"] = host_path
        kwargs["ue_in_project"] = "in_project"
        if match.get("name"):
            kwargs["content_root"] = import_flow_mod.content_root_from_folder_name(
                str(match.get("name"))
            )
    else:
        raise HTTPException(status_code=400, detail="unknown_step")
    updated = register_mod.patch_asset(asset_id, **kwargs)
    return {"schema_version": 1, "asset": updated, "import": import_flow_mod.import_status(asset_id)}


@app.post("/api/assets/{asset_id}/import/stage")
def api_asset_import_stage(asset_id: str, body: ImportStageRequest) -> dict[str, Any]:
    """Enqueue host_stage for Windows agent: zip host Content/Unity folder → vault upload."""
    if register_mod.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    host_path = body.host_content_path.strip()
    if not host_path:
        raise HTTPException(status_code=400, detail="host_content_path_required")
    try:
        host = ue_hosts_mod.get_host(body.ue_host) if body.ue_host else ue_hosts_mod.get_host()
        host_id = host.get("id")
    except Exception:  # noqa: BLE001
        host_id = body.ue_host or "aurora"
    match = ue_hosts_mod.path_known_in_content_scan(host_path, host_id)
    if not match:
        raise HTTPException(
            status_code=400,
            detail="host_path_not_in_scan",
        )
    folder_name = (body.content_folder_name or "").strip() or str(match.get("name") or "")
    register_mod.patch_asset(
        asset_id,
        host_content_path=host_path,
        ue_in_project="in_project",
        content_root=import_flow_mod.content_root_from_folder_name(folder_name)
        if folder_name
        else None,
    )
    job = jobs_mod.enqueue_job(
        kind="host_stage",
        asset_id=asset_id,
        step_id="stage_vault",
        payload={
            "source": "api_import_stage",
            "host_content_path": host_path,
            "content_folder_name": folder_name or None,
            "ue_host": host_id,
            "engine": str((register_mod.get_asset(asset_id) or {}).get("engine") or "unreal"),
        },
    )
    return {"schema_version": 1, "job": job, "import": import_flow_mod.import_status(asset_id)}


@app.post("/api/assets/{asset_id}/import/fab-install")
def api_asset_fab_install(asset_id: str, body: ImportFabInstallRequest) -> dict[str, Any]:
    """Enqueue host_fab_install: copy Epic VaultCache pack into AuroraVellum Content."""
    if register_mod.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    try:
        result = import_flow_mod.enqueue_fab_install(
            asset_id,
            ue_host=body.ue_host,
            auto_stage=body.auto_stage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema_version": 1, **result}


@app.post("/api/import/fab-install-batch")
def api_fab_install_batch(body: ImportFabInstallBatchRequest) -> dict[str, Any]:
    """Enqueue host_fab_install for vault-installable packs missing from F: Content."""
    cov = import_flow_mod.coverage(engine="unreal", host_id=body.ue_host)
    jobs_out: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for item in (cov.get("vault_installable") or [])[: body.limit]:
        aid = str(item.get("asset_id") or "")
        if not aid:
            continue
        try:
            result = import_flow_mod.enqueue_fab_install(
                aid,
                ue_host=body.ue_host,
                auto_stage=body.auto_stage,
            )
            jobs_out.append({"asset_id": aid, "job": result["job"]})
        except ValueError as exc:
            errors.append({"asset_id": aid, "error": str(exc)})
    return {
        "schema_version": 1,
        "enqueued": len(jobs_out),
        "jobs": jobs_out,
        "errors": errors,
        "vault_installable_count": cov.get("vault_installable_count"),
    }


@app.post("/api/import/register-orphans")
def api_register_orphans(body: ImportRegisterOrphansRequest) -> dict[str, Any]:
    """Register free/extra Content folders (orphans) and enqueue stage."""
    return import_flow_mod.register_orphans_batch(
        ue_host=body.ue_host,
        auto_stage=body.auto_stage,
        folders=body.folders,
        limit=body.limit,
    )

@app.get("/api/ue/hosts/content-folders")
def api_ue_content_folders(host_id: str | None = Query(default=None)) -> dict[str, Any]:
    try:
        return ue_hosts_mod.list_content_folders(host_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/ue/hosts/content-folders/refresh")
def api_ue_content_folders_refresh(host_id: str | None = Query(default=None)) -> dict[str, Any]:
    """Enqueue host_scan so Aurora re-runs report_host_specs (includes Content/*)."""
    try:
        host = ue_hosts_mod.get_host(host_id)
        hid = host.get("id")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    job = jobs_mod.enqueue_job(
        kind="host_scan",
        asset_id=None,
        step_id="host_scan",
        payload={"source": "api_content_refresh", "ue_host": hid},
    )
    return {"schema_version": 1, "job": job}


@app.post("/api/ue/hosts/open-editor")
def api_ue_open_editor(host_id: str | None = Query(default=None)) -> dict[str, Any]:
    """Enqueue host_open_editor — open canonical AuroraVellum in UE for Fab-in-Editor."""
    try:
        host = ue_hosts_mod.get_host(host_id)
        hid = host.get("id")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    job = jobs_mod.enqueue_job(
        kind="host_open_editor",
        asset_id=None,
        step_id="open_editor",
        payload={
            "source": "api_open_editor",
            "ue_host": hid,
            "project": host.get("fab_target_project") or host.get("project"),
        },
    )
    return {"schema_version": 1, "job": job}

@app.post("/api/assets/{asset_id}/import/stage-upload")
async def api_asset_import_stage_upload(
    asset_id: str,
    host_content_path: str = Form(...),
    content_folder_name: str | None = Form(default=None),
    archive: UploadFile = File(...),
) -> dict[str, Any]:
    """Windows agent uploads a store-zip of the pack Content folder."""
    if register_mod.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    name = archive.filename or "pack.zip"
    if not name.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="expected_zip")
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        while True:
            chunk = await archive.read(1024 * 1024)
            if not chunk:
                break
            tmp.write(chunk)
    try:
        result = import_flow_mod.apply_stage_upload(
            asset_id,
            archive_path=tmp_path,
            host_content_path=host_content_path,
            content_folder_name=content_folder_name,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="asset_not_found") from None
    except zipfile.BadZipFile as e:
        raise HTTPException(status_code=400, detail="bad_zip") from e
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
    return {"schema_version": 1, **result, "import": import_flow_mod.import_status(asset_id)}


@app.post("/api/intake/propose")
def api_intake_propose(body: IntakeProposeRequest) -> dict[str, Any]:
    try:
        run = intake_mod.propose_intake(
            body.asset_id,
            requested_by=body.requested_by,
            note=body.note,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail="asset_not_found") from e
    return run


@app.get("/api/intake")
def api_intake_list(
    asset_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    runs = intake_mod.list_runs(asset_id=asset_id, limit=limit)
    return {"schema_version": 1, "count": len(runs), "runs": runs}


@app.get("/api/intake/{run_id}")
def api_intake_get(run_id: str) -> dict[str, Any]:
    run = intake_mod.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="intake_run_not_found")
    return run


@app.patch("/api/intake/{run_id}/steps/{step_id}")
def api_intake_patch_step(run_id: str, step_id: str, body: IntakeStepPatchRequest) -> dict[str, Any]:
    try:
        return intake_mod.patch_step(
            run_id,
            step_id,
            status=body.status,
            notes=body.notes,
        )
    except KeyError as e:
        missing = str(e).strip("'")
        detail = "intake_run_not_found" if missing == run_id else "step_not_found"
        raise HTTPException(status_code=404, detail=detail) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/intake/{run_id}/enqueue-automatable")
def api_intake_enqueue_automatable(run_id: str) -> dict[str, Any]:
    try:
        jobs = jobs_mod.enqueue_automatable_for_run(run_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="intake_run_not_found") from e
    return {"schema_version": 1, "count": len(jobs), "jobs": jobs}


@app.post("/api/jobs")
def api_jobs_enqueue(body: JobEnqueueRequest) -> dict[str, Any]:
    allowed = {
        "prepare_stage",
        "record_paths",
        "confirm_project_fit",
        "derive_lookdev",
        "ue_capture",
    }
    if body.kind not in allowed:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(allowed)}")
    return jobs_mod.enqueue_job(
        kind=body.kind,
        asset_id=body.asset_id,
        intake_run_id=body.intake_run_id,
        step_id=body.step_id,
        payload=body.payload,
    )


@app.get("/api/jobs")
def api_jobs_list(
    status: str | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    jobs = jobs_mod.list_jobs(status=status, asset_id=asset_id, limit=limit)
    return {"schema_version": 1, "count": len(jobs), "jobs": jobs}


@app.get("/api/jobs/{job_id}")
def api_jobs_get(job_id: str) -> dict[str, Any]:
    job = jobs_mod.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job


@app.post("/api/jobs/claim")
def api_jobs_claim(body: JobClaimRequest) -> dict[str, Any]:
    """Claim next queued job for an external agent (Windows UE agent)."""
    kinds = frozenset(body.kinds or ["ue_capture"])
    unknown = kinds - jobs_mod.UE_AGENT_KINDS - jobs_mod.LINUX_WORKER_KINDS
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown kinds: {sorted(unknown)}")
    stale = jobs_mod.fail_stale_running_agent_jobs()
    job = jobs_mod.claim_next_job(kinds=kinds)
    return {
        "schema_version": 1,
        "job": job,
        "stale_failed": [
            {"job_id": j.get("job_id"), "asset_id": j.get("asset_id"), "error": j.get("error")}
            for j in stale
        ],
    }


@app.post("/api/jobs/sweep-stale")
def api_jobs_sweep_stale(
    max_silence_sec: int | None = Query(default=None, ge=30, le=7200),
) -> dict[str, Any]:
    """Fail abandoned UE-agent running jobs (no progress heartbeat)."""
    failed = jobs_mod.fail_stale_running_agent_jobs(max_silence_sec=max_silence_sec)
    return {
        "schema_version": 1,
        "failed_count": len(failed),
        "jobs": failed,
        "max_silence_sec": max_silence_sec
        if max_silence_sec is not None
        else jobs_mod.DEFAULT_STALE_SILENCE_SEC,
    }


class JobCancelRequest(BaseModel):
    reason: str | None = Field(default="operator_cancelled", max_length=4000)


@app.post("/api/jobs/{job_id}/cancel")
def api_jobs_cancel(job_id: str, body: JobCancelRequest | None = None) -> dict[str, Any]:
    """Cancel a queued/running job (UI: orphaned Capture, stop before re-queue)."""
    reason = (body.reason if body else None) or "operator_cancelled"
    try:
        cancelled = jobs_mod.cancel_job(job_id, reason=reason)
    except KeyError:
        raise HTTPException(status_code=404, detail="job_not_found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"schema_version": 1, "job": cancelled}


@app.post("/api/jobs/{job_id}/report")
def api_jobs_report(job_id: str, body: JobReportRequest) -> dict[str, Any]:
    """External agent reports success/failure for a claimed job."""
    job = jobs_mod.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    if job.get("status") not in {"running", "queued"}:
        raise HTTPException(status_code=409, detail=f"job_status_{job.get('status')}")

    result = dict(body.result or {})
    if not body.error and job.get("kind") == "ue_capture" and job.get("asset_id"):
        project = body.scratch_project_path or result.get("project_path") or ""
        if project:
            try:
                scratch_mod.record_scratch_inspect(
                    str(job["asset_id"]),
                    scratch_project_path=str(project),
                    engine_version=body.engine_version or result.get("engine_version"),
                    notes=str(result.get("notes") or "ue_capture agent"),
                    intake_run_id=job.get("intake_run_id"),
                )
            except Exception as exc:  # noqa: BLE001
                result["scratch_record_error"] = str(exc)

    completed = jobs_mod.complete_job(
        job_id,
        result=result if result else None,
        error=body.error,
    )
    # Structured chain: successful vault stage → required lookdev job (derive XOR capture).
    if (
        not body.error
        and completed.get("status") == "succeeded"
        and completed.get("kind") in {"host_stage", "ue_stage"}
        and completed.get("asset_id")
    ):
        try:
            follow = import_flow_mod.enqueue_post_stage_lookdev(str(completed["asset_id"]))
            if follow:
                completed = dict(completed)
                merged = dict(completed.get("result") or {})
                pointer: dict[str, Any] = {
                    "lookdev_mode": follow.get("lookdev_mode"),
                    "skipped": follow.get("skipped"),
                    "reason": follow.get("reason"),
                }
                job = follow.get("job")
                if isinstance(job, dict):
                    pointer["job_id"] = job.get("job_id")
                    pointer["kind"] = job.get("kind")
                merged["post_stage_lookdev"] = {
                    k: v for k, v in pointer.items() if v is not None
                }
                completed["result"] = merged
                jobs_mod.patch_job_result(job_id, merged)
        except Exception as exc:  # noqa: BLE001
            completed = dict(completed)
            merged = dict(completed.get("result") or {})
            merged["post_stage_lookdev_error"] = str(exc)
            completed["result"] = merged
            try:
                jobs_mod.patch_job_result(job_id, merged)
            except Exception:  # noqa: BLE001
                pass
    return {"schema_version": 1, "job": completed}


@app.post("/api/jobs/{job_id}/progress")
def api_jobs_progress(job_id: str, body: JobProgressRequest) -> dict[str, Any]:
    """Heartbeat from Windows runner — live phase + UE log tail while job runs."""
    try:
        meta = jobs_mod.append_job_progress(
            job_id, message=body.message, log_tail=body.log_tail
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="job_not_found") from None
    return {"schema_version": 1, **meta}


@app.get("/api/jobs/{job_id}/progress")
def api_jobs_progress_get(job_id: str) -> dict[str, Any]:
    try:
        payload = jobs_mod.read_job_progress(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="job_not_found") from None
    return {"schema_version": 1, **payload}


@app.post("/api/ue/capture")
def api_ue_capture(body: UeCaptureRequest) -> dict[str, Any]:
    """Enqueue Unreal capture for the Windows UE agent (triggered from Vellum UI)."""
    if register_mod.get_asset(body.asset_id) is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    asset = register_mod.get_asset(body.asset_id)
    assert asset is not None
    project = (
        body.project_path
        or ue_hosts_mod.default_project_dir()
        or asset.get("scratch_project_path")
        or r"F:\Games\AuroraVellum"
    ).strip()
    content_root = (body.content_root or "").strip()
    if not content_root:
        content_root = str(asset.get("content_root") or "").strip()
    if not content_root:
        # Infer /Game/<Folder> from vault stage leaf or host Content folder name.
        host_p = str(asset.get("host_content_path") or "").strip()
        raw_p = str(asset.get("raw_location") or "").strip()
        leaf = ""
        if host_p:
            leaf = Path(host_p.replace("\\", "/")).name
        elif raw_p:
            # Prefer inner Content child if present
            raw_path = Path(raw_p)
            content_kids = [
                p.name
                for p in raw_path.iterdir()
                if raw_path.is_dir() and p.is_dir() and not p.name.startswith(".")
            ] if raw_path.is_dir() else []
            if len(content_kids) == 1:
                leaf = content_kids[0]
            elif "FireworksV1" in content_kids:
                leaf = "FireworksV1"
        if leaf:
            content_root = import_flow_mod.content_root_from_folder_name(leaf)
    try:
        host = ue_hosts_mod.get_host()
        if not content_root and host.get("content_root"):
            content_root = str(host["content_root"]).strip()
        engine = (body.engine_version or host.get("engine_version") or "5.8").strip()
        host_id = host.get("id")
    except Exception:  # noqa: BLE001
        engine = (body.engine_version or "5.8").strip()
        host_id = None
    if not content_root:
        raise HTTPException(
            status_code=400,
            detail="content_root_required — stage pack first or set content_root on asset",
        )
    job = jobs_mod.enqueue_job(
        kind="ue_capture",
        asset_id=body.asset_id,
        intake_run_id=body.intake_run_id,
        step_id="scratch_inspect",
        payload={
            "source": "api_ue_capture",
            "lane": body.lane,
            "project_path": project,
            "content_root": content_root,
            "engine_version": engine,
            "ue_host": host_id,
            "force": bool(body.force),
            "max_systems": int(body.max_systems),
        },
    )
    return {"schema_version": 1, "job": job, "ue_host": host_id}


@app.get("/api/ue/hosts")
def api_ue_hosts() -> dict[str, Any]:
    """Aurora/Borealis UE host profiles (active = asset/factory host)."""
    try:
        return ue_hosts_mod.public_hosts_payload()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/ue/hosts/specs")
def api_ue_hosts_specs(body: UeHostSpecsRequest) -> dict[str, Any]:
    """Persist workstation hardware snapshot from the Windows UE agent."""
    try:
        saved = ue_hosts_mod.save_host_specs(body.host_id, body.specs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"schema_version": 1, **saved}


@app.post("/api/ue/hosts/util")
def api_ue_hosts_util(body: UeHostSpecsRequest) -> dict[str, Any]:
    """Cheap heartbeat merge (gpu util / editor RSS) — does not wipe full specs."""
    try:
        saved = ue_hosts_mod.merge_host_specs(body.host_id, body.specs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"schema_version": 1, **saved}


@app.get("/api/lookdev/lanes")
def api_lookdev_lanes() -> dict[str, Any]:
    lanes = lookdev_mod.list_lanes()
    return {"schema_version": 1, "count": len(lanes), "lanes": lanes}


@app.get("/api/lookdev/outputs")
def api_lookdev_outputs(
    asset_id: str | None = Query(default=None),
    lane: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
) -> dict[str, Any]:
    outputs = lookdev_mod.list_outputs(asset_id=asset_id, lane=lane, limit=limit)
    return {"schema_version": 1, "count": len(outputs), "outputs": outputs}


@app.get("/api/lookdev/outputs/{output_id}")
def api_lookdev_output_get(output_id: str) -> dict[str, Any]:
    out = lookdev_mod.get_output(output_id)
    if not out:
        raise HTTPException(status_code=404, detail="derived_output_not_found")
    return out


@app.get("/api/lookdev/outputs/{output_id}/file")
def api_lookdev_output_file(output_id: str) -> FileResponse:
    out = lookdev_mod.get_output(output_id)
    if not out:
        raise HTTPException(status_code=404, detail="derived_output_not_found")
    try:
        path = lookdev_mod.resolve_safe_file(out)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file_missing") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="path_outside_vault") from None
    return FileResponse(path)


@app.post("/api/lookdev/derive")
def api_lookdev_derive(body: LookdevDeriveRequest) -> dict[str, Any]:
    """Enqueue (preferred) or run derive_lookdev for an asset with raw_location."""
    if register_mod.get_asset(body.asset_id) is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    payload: dict[str, Any] = {"source": "api_lookdev_derive"}
    if body.lanes:
        payload["lanes"] = body.lanes
    job = jobs_mod.enqueue_job(
        kind="derive_lookdev",
        asset_id=body.asset_id,
        intake_run_id=body.intake_run_id,
        step_id="derive_lookdev" if body.intake_run_id else None,
        payload=payload,
    )
    return {"schema_version": 1, "job": job}


@app.post("/api/lookdev/ingest-render")
async def api_lookdev_ingest_render(
    asset_id: str = Form(...),
    lane: str = Form(...),
    note: str | None = Form(default=None),
    system_name: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a Niagara MRQ hero still into vault derived-renders."""
    if register_mod.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    suffix = Path(file.filename or "still.png").suffix.lower() or ".png"
    if suffix not in lookdev_mod.IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail="unsupported_image")
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="empty_file")
        tmp.write(content)
    try:
        row = lookdev_mod.ingest_niagara_render(
            asset_id,
            lane=lane,
            source_file=tmp_path,
            note=note,
            original_name=file.filename,
            system_name=system_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError:
        raise HTTPException(status_code=404, detail="asset_not_found") from None
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"schema_version": 1, "output": row}


@app.post("/api/lookdev/ingest-sequence")
async def api_lookdev_ingest_sequence(
    asset_id: str = Form(...),
    system_name: str = Form(...),
    lane: str | None = Form(default=None),
    lanes: str | None = Form(default=None),
    note: str | None = Form(default=None),
    archive: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a zip of MRQ PNG frames once; fan-out catalog rows per lane.

    Prefer `lanes=slots,hail-overlay` (comma-separated). Legacy `lane=` still works.
    """
    if register_mod.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    name = archive.filename or "sequence.zip"
    if not name.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="expected_zip")
    lane_list = [p.strip() for p in (lanes or "").split(",") if p.strip()]
    if lane and lane.strip() and lane.strip() not in lane_list:
        lane_list.append(lane.strip())
    if not lane_list:
        raise HTTPException(status_code=400, detail="lanes_required")
    import tempfile
    import zipfile

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        zip_path = td_path / "seq.zip"
        zip_path.write_bytes(await archive.read())
        extract_dir = td_path / "frames"
        extract_dir.mkdir()
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile as e:
            raise HTTPException(status_code=400, detail="bad_zip") from e
        try:
            result = lookdev_mod.ingest_niagara_sequence(
                asset_id,
                lanes=lane_list,
                system_name=system_name,
                source_dir=extract_dir,
                note=note,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except KeyError:
            raise HTTPException(status_code=404, detail="asset_not_found") from None
    rows = result["outputs"]
    # Back-compat single-lane shape when only one lane was requested.
    if len(rows) == 1:
        return {"schema_version": 1, "output": rows[0], "outputs": rows}
    return {
        "schema_version": 1,
        "outputs": rows,
        "path": result["path"],
        "frame_count": result["frame_count"],
    }


@app.get("/api/game-ready/elements")
def api_game_ready_list(
    asset_id: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    lane: str | None = Query(default=None),
    q: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    rows = game_ready_mod.list_elements(
        asset_id=asset_id, kind=kind, lane=lane, q=q, tag=tag, limit=limit
    )
    return {
        "schema_version": 1,
        "count": len(rows),
        "kinds": list(game_ready_mod.ELEMENT_KINDS),
        "elements": rows,
    }


@app.get("/api/game-ready/elements/{element_id}")
def api_game_ready_get(element_id: str) -> dict[str, Any]:
    row = game_ready_mod.get_element(element_id)
    if not row:
        raise HTTPException(status_code=404, detail="game_ready_not_found")
    return row


@app.get("/api/game-ready/elements/{element_id}/file")
def api_game_ready_file(element_id: str) -> FileResponse:
    row = game_ready_mod.get_element(element_id)
    if not row:
        raise HTTPException(status_code=404, detail="game_ready_not_found")
    try:
        path = game_ready_mod.resolve_safe_file(row)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file_missing") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="path_outside_vault") from None
    return FileResponse(path)


@app.post("/api/game-ready/ingest-manifest")
def api_game_ready_ingest_manifest(body: GameReadyIngestManifestRequest) -> dict[str, Any]:
    if register_mod.get_asset(body.asset_id) is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    path = Path(body.manifest_path)
    if not path.is_file():
        raise HTTPException(status_code=400, detail="manifest_missing")
    try:
        result = game_ready_mod.ingest_manifest(
            path, asset_id=body.asset_id, pack=body.pack
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="asset_not_found") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.post("/api/assets/{asset_id}/game-ready/upload-run")
async def api_game_ready_upload_run(
    asset_id: str,
    pack: str = Form(...),
    archive: UploadFile = File(...),
) -> dict[str, Any]:
    """Aurora uploads a zip of a Conversion Factory run's output tree for a pack."""
    if register_mod.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    name = archive.filename or "run.zip"
    if not name.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="expected_zip")
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        zip_path = td_path / "run.zip"
        with zip_path.open("wb") as fh:
            while True:
                chunk = await archive.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
        extract_dir = td_path / "run"
        extract_dir.mkdir()
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile as e:
            raise HTTPException(status_code=400, detail="bad_zip") from e
        try:
            result = game_ready_mod.ingest_run_archive(
                extract_dir, asset_id=asset_id, pack=pack
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="asset_not_found") from None
    import_flow_mod.clear_ops_caches()
    return result


@app.post("/api/game-ready/elements/{element_id}/publish")
def api_game_ready_publish(element_id: str, body: GameReadyPublishRequest) -> dict[str, Any]:
    try:
        row = game_ready_mod.publish_to_lane(
            element_id, body.lane, presentation=body.presentation
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="game_ready_not_found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (FileNotFoundError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema_version": 1, "element": row}


@app.post("/api/game-ready/elements/{element_id}/unpublish")
def api_game_ready_unpublish(element_id: str, body: GameReadyPublishRequest) -> dict[str, Any]:
    try:
        row = game_ready_mod.unpublish_from_lane(element_id, body.lane)
    except KeyError:
        raise HTTPException(status_code=404, detail="game_ready_not_found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema_version": 1, "element": row}


@app.get("/api/attach/targets")
def api_attach_targets() -> dict[str, Any]:
    return attach_mod.targets_status()


@app.get("/api/attach")
def api_attach_list(
    asset_id: str | None = Query(default=None),
    target: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    rows = attach_mod.list_attachments(asset_id=asset_id, target=target, limit=limit)
    return {"schema_version": 1, "count": len(rows), "attachments": rows}


@app.post("/api/attach")
def api_attach(body: AttachRequest) -> dict[str, Any]:
    try:
        row = attach_mod.attach(
            derived_output_id=body.derived_output_id,
            asset_id=body.asset_id,
            target=body.target,
            register_glyph=bool(body.register_glyph),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {"schema_version": 1, "attachment": row}


@app.post("/api/scratch/record")
def api_scratch_record(body: ScratchRecordRequest) -> dict[str, Any]:
    try:
        result = scratch_mod.record_scratch_inspect(
            body.asset_id,
            scratch_project_path=body.scratch_project_path,
            engine_version=body.engine_version,
            notes=body.notes,
            intake_run_id=body.intake_run_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="asset_not_found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"schema_version": 1, **result}


@app.get("/api/scratch/hint")
def api_scratch_hint(engine: str = Query(default="unreal")) -> dict[str, Any]:
    path = lookdev_mod.scratch_hint_path(engine)
    readme = path / "README.md"
    if not readme.is_file():
        readme.write_text(
            "# Unreal scratch inspection\n\n"
            "Workstation Unreal projects (e.g. `C:\\\\epic\\\\VellumImport`) are the "
            "live scratch. This vault folder holds notes/readouts only — not the .uproject.\n"
            "Record inspect via `POST /api/scratch/record`.\n"
            "Upload Niagara viewport stills via `POST /api/lookdev/ingest-render`.\n",
            encoding="utf-8",
        )
    return {"schema_version": 1, "engine": engine, "vault_hint": str(path)}


@app.get("/api/eidolon/renders")
def api_eidolon_renders(
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    """Browse Eidolon batch renders (symbols / plates / sprite sheets)."""
    try:
        return eidolon_mod.list_renders(limit=limit)
    except eidolon_mod.EidolonError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/eidolon/renders/{batch_id}/{filename}/file")
def api_eidolon_render_file(batch_id: str, filename: str) -> Response:
    """Proxy one Eidolon artifact image through Vellum (same-origin for the UI)."""
    try:
        body, media = eidolon_mod.fetch_artifact(batch_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="render_not_found") from exc
    except eidolon_mod.EidolonError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=body,
        media_type=media,
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/api/visual-research")
def api_visual_research_list(
    q: str | None = Query(default=None),
    project_id: str | None = Query(default=None, max_length=128),
    tag: str | None = Query(default=None),
    format: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Browse/search Visual Research (project-agent-safe, read-only)."""
    return research_mod.list_items(
        q=q,
        project_id=project_id,
        tag=tag,
        format=format,
        limit=limit,
        offset=offset,
    )


@app.post("/api/visual-research/bundles")
async def api_visual_research_bundle_create(
    file: UploadFile = File(...),
    source_url: str = Form(...),
    body: str = Form(...),
    project_id: str | None = Form(default=None),
    title: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    captured_at: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    rights: str | None = Form(default=None),
    attribution: str | None = Form(default=None),
    author: str | None = Form(default=None),
    publisher: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Store visual evidence in Vellum and its extracted source text in Mneme."""
    _require_research_write(authorization)
    source_body = body.strip()
    if not source_body:
        raise HTTPException(status_code=400, detail="source_text_required")
    if len(source_body) > 2_000_000:
        raise HTTPException(status_code=400, detail="source_text_too_large")
    if not source_url.strip():
        raise HTTPException(status_code=400, detail="source_url_required")
    try:
        resolved_project = mneme_mod.resolve_project_id(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = await file.read()
    try:
        item = research_mod.ingest_image(
            data=content,
            filename=file.filename,
            title=title,
            caption=caption,
            project_id=resolved_project,
            source_url=source_url,
            captured_at=captured_at,
            tags=tags,
            rights=rights,
            attribution=attribution,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    research_id = str(item["id"])
    link_tag = f"vellum-{research_id}"
    mneme_tags = list(
        dict.fromkeys([*(item.get("tags") or []), "visual-research", link_tag])
    )
    image_url = (
        f"{mneme_mod.vellum_public_base_url()}"
        f"/api/visual-research/{research_id}/file"
    )
    mneme_body = (
        f"{source_body}\n\n---\n\n"
        "## Visual evidence\n\n"
        f"- Vellum ID: `{research_id}`\n"
        f"- [View stored image]({image_url})\n"
        f"- Original source: {item['source_url']}\n"
    )

    document: dict[str, Any] | None = None
    try:
        document = mneme_mod.create_document(
            title=str(item["title"]),
            project_id=resolved_project,
            source_url=str(item["source_url"]),
            captured_at=str(item["captured_at"]),
            tags=mneme_tags,
            body=mneme_body,
            author=author,
            publisher=publisher,
        )
    except mneme_mod.MnemeAmbiguousError:
        try:
            document = mneme_mod.find_document_by_tag(
                link_tag, project_id=resolved_project
            )
        except mneme_mod.MnemeError:
            document = None
    except mneme_mod.MnemeError:
        document = None

    if not document:
        research_mod.delete_item(research_id)
        raise HTTPException(status_code=502, detail="mneme_ingest_failed")

    document_id = str(document.get("id") or "").strip()
    if not document_id:
        research_mod.delete_item(research_id)
        raise HTTPException(status_code=502, detail="mneme_invalid_response")
    try:
        linked = research_mod.link_mneme(
            research_id,
            project_id=resolved_project,
            document_id=document_id,
            document_url=mneme_mod.document_url(document_id),
        )
    except Exception:
        try:
            mneme_mod.delete_document(document_id)
        except mneme_mod.MnemeError:
            pass
        research_mod.delete_item(research_id)
        raise HTTPException(status_code=500, detail="bundle_link_failed") from None
    return {
        "schema_version": 1,
        "item": linked,
        "mneme_document": {
            "id": document_id,
            "project_id": resolved_project,
            "url": mneme_mod.document_url(document_id),
        },
    }


@app.get("/api/visual-research/{research_id}")
def api_visual_research_get(research_id: str) -> dict[str, Any]:
    item = research_mod.get_item(research_id)
    if not item:
        raise HTTPException(status_code=404, detail="visual_research_not_found")
    return item


@app.get("/api/visual-research/{research_id}/file")
def api_visual_research_file(research_id: str) -> FileResponse:
    raw = research_mod.get_raw_item(research_id)
    if not raw:
        raise HTTPException(status_code=404, detail="visual_research_not_found")
    try:
        path = research_mod.resolve_safe_file(raw)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file_missing") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="path_outside_vault") from None
    media = str(raw.get("mime_type") or "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)


@app.post("/api/visual-research")
async def api_visual_research_create(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    project_id: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    captured_at: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    rights: str | None = Form(default=None),
    attribution: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Upload a visual research image (manual UI or automated capture). Requires write token."""
    _require_research_write(authorization)
    if project_id:
        try:
            project_id = mneme_mod.resolve_project_id(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    content = await file.read()
    try:
        item = research_mod.ingest_image(
            data=content,
            filename=file.filename,
            title=title,
            caption=caption,
            project_id=project_id,
            source_url=source_url,
            captured_at=captured_at,
            tags=tags,
            rights=rights,
            attribution=attribution,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema_version": 1, "item": item}


@app.patch("/api/visual-research/{research_id}")
def api_visual_research_patch(
    research_id: str,
    body: VisualResearchPatchRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_research_write(authorization)
    fields = body.model_dump(exclude_unset=True)
    try:
        item = research_mod.update_item(research_id, **fields)
    except KeyError:
        raise HTTPException(status_code=404, detail="visual_research_not_found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"schema_version": 1, "item": item}


@app.delete("/api/visual-research/{research_id}")
def api_visual_research_delete(
    research_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_research_write(authorization)
    try:
        result = research_mod.delete_item(research_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="visual_research_not_found") from None
    return {"schema_version": 1, **result}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


if WEB_ROOT.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
