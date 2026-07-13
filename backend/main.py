"""Vellum API — Control Alt Games asset vault register + browse."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import register as register_mod

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    register_mod.ensure_register()
    yield


app = FastAPI(
    title="Vellum",
    description="Control Alt Games asset vault — register, browse, intake (slice A: register + browse).",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/api/health")
def health() -> dict:
    summary = register_mod.register_summary()
    return {
        "ok": True,
        "app": "vellum",
        "brand_family": "control-alt-games",
        "register": summary,
    }


@app.get("/api/register/summary")
def api_register_summary() -> dict:
    return register_mod.register_summary()


@app.get("/api/assets")
def api_list_assets(
    q: str | None = Query(default=None),
    engine: str | None = Query(default=None),
    redeem_window: str | None = Query(default=None, alias="redeem"),
) -> dict:
    assets = register_mod.list_assets(q=q, engine=engine, redeem_window_filter=redeem_window)
    return {
        "schema_version": 1,
        "count": len(assets),
        "assets": assets,
    }


@app.get("/api/assets/{asset_id}")
def api_get_asset(asset_id: str) -> dict:
    asset = register_mod.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="asset_not_found")
    return asset


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


if WEB_ROOT.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
