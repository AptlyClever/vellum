"""Vellum API — Control Alt Games asset vault register + intake propose."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import intake as intake_mod
from . import jobs as jobs_mod
from . import lookdev as lookdev_mod
from . import register as register_mod

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


class LookdevDeriveRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=200)
    lanes: list[str] | None = None
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
    if (
        body.redemption_status is None
        and body.raw_location is None
        and body.intake_notes is None
    ):
        raise HTTPException(status_code=400, detail="no_fields")
    try:
        return register_mod.patch_asset(
            asset_id,
            redemption_status=body.redemption_status,
            raw_location=body.raw_location,
            intake_notes=body.intake_notes,
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
    allowed = {"prepare_stage", "record_paths", "confirm_project_fit", "derive_lookdev"}
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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


if WEB_ROOT.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
