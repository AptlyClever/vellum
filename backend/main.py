"""Vellum API — Control Alt Games asset vault register + intake propose."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import intake as intake_mod
from . import jobs as jobs_mod
from . import lookdev as lookdev_mod
from . import register as register_mod
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


class LookdevDeriveRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=200)
    lanes: list[str] | None = None
    intake_run_id: str | None = Field(default=None, max_length=200)


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
    redeem_window: str | None = Query(default=None, alias="redeem"),
) -> dict[str, Any]:
    assets = register_mod.list_assets(q=q, engine=engine, redeem_window_filter=redeem_window)
    return {
        "schema_version": 1,
        "count": len(assets),
        "assets": assets,
    }


@app.get("/api/assets/{asset_id}")
def api_get_asset(asset_id: str) -> dict[str, Any]:
    asset = register_mod.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="asset_not_found")
    return asset


@app.patch("/api/assets/{asset_id}")
def api_patch_asset(asset_id: str, body: AssetPatchRequest) -> dict[str, Any]:
    if all(
        getattr(body, field) is None
        for field in (
            "redemption_status",
            "raw_location",
            "intake_notes",
            "scratch_project_path",
            "scratch_project_status",
            "scratch_engine_version",
            "scratch_notes",
        )
    ):
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
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="asset_not_found") from None


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
    job = jobs_mod.claim_next_job(kinds=kinds)
    return {"schema_version": 1, "job": job}


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
    content_root = (body.content_root or "/Game/FireworksV1").strip()
    try:
        host = ue_hosts_mod.get_host()
        if not body.content_root and host.get("content_root"):
            content_root = str(host["content_root"]).strip()
        engine = (body.engine_version or host.get("engine_version") or "5.8").strip()
        host_id = host.get("id")
    except Exception:  # noqa: BLE001
        engine = (body.engine_version or "5.8").strip()
        host_id = None
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
    """Aurora / Borealis capture host profiles (active = preferred workstation)."""
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


@app.get("/api/lookdev/lanes")
def api_lookdev_lanes() -> dict[str, Any]:
    lanes = lookdev_mod.list_lanes()
    return {"schema_version": 1, "count": len(lanes), "lanes": lanes}


@app.get("/api/lookdev/outputs")
def api_lookdev_outputs(
    asset_id: str | None = Query(default=None),
    lane: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
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
    lane: str = Form(...),
    system_name: str = Form(...),
    note: str | None = Form(default=None),
    archive: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a zip of MRQ PNG frames; retained under niagara/sequences/."""
    if register_mod.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    name = archive.filename or "sequence.zip"
    if not name.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="expected_zip")
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
            row = lookdev_mod.ingest_niagara_sequence(
                asset_id,
                lane=lane,
                system_name=system_name,
                source_dir=extract_dir,
                note=note,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except KeyError:
            raise HTTPException(status_code=404, detail="asset_not_found") from None
    return {"schema_version": 1, "output": row}


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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


if WEB_ROOT.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
