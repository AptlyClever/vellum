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
from . import register as register_mod

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    register_mod.ensure_register()
    yield


app = FastAPI(
    title="Vellum",
    description="Control Alt Games asset vault — register, browse, intake propose.",
    version="0.2.0",
    lifespan=lifespan,
)


class IntakeProposeRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(default="operator", max_length=120)
    note: str | None = Field(default=None, max_length=2000)


class IntakeStepPatchRequest(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=4000)


@app.get("/api/health")
def health() -> dict[str, Any]:
    summary = register_mod.register_summary()
    runs = intake_mod.list_runs(limit=5)
    return {
        "ok": True,
        "app": "vellum",
        "brand_family": "control-alt-games",
        "register": summary,
        "intake_runs_recent": len(runs),
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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


if WEB_ROOT.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
