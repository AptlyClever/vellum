"""Shared helpers for Conversion Factory UE Python jobs."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def env_path(name: str, default: str | None = None) -> Path:
    raw = os.environ.get(name, default)
    if not raw:
        raise RuntimeError(f"missing env {name}")
    return Path(raw)


def work_dir() -> Path:
    p = env_path("VELLUM_PIPELINE_WORK", r"F:\Games\AuroraVellum\Saved\VellumPipeline")
    p.mkdir(parents=True, exist_ok=True)
    return p


def pack_name() -> str:
    return os.environ.get("VELLUM_PACK", "").strip() or "FireworksV1"


def pack_content_root() -> str:
    """Unreal content path for the pack (Fab installs at Content root)."""
    override = os.environ.get("VELLUM_CONTENT_ROOT", "").strip()
    if override:
        return override.rstrip("/")
    return f"/Game/{pack_name()}"


def vault_game_ready() -> Path:
    """Prefer env; fall back to local Aurora staging mirror."""
    raw = os.environ.get("VELLUM_VAULT_GAME_READY")
    if raw:
        p = Path(raw)
    else:
        p = work_dir() / "game-ready-out"
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("schema_version", 1)
    payload.setdefault("generated_at_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def quit_editor(code: int = 0) -> None:
    try:
        import unreal  # type: ignore

        unreal.SystemLibrary.quit_editor()
    except Exception:
        pass
    raise SystemExit(code)
