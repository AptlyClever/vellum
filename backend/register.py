"""Vellum asset register — load seed, compute redeem window, query."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = ROOT / "config" / "humble-seed.yaml"
DEFAULT_REGISTER = ROOT / "data" / "asset-register.yaml"


def register_path() -> Path:
    configured = os.environ.get("VELLUM_REGISTER_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_REGISTER


def seed_path() -> Path:
    configured = os.environ.get("VELLUM_SEED_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_SEED


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def redeem_window(deadline: str | None, *, now: datetime | None = None) -> str:
    """Return open | expired | unknown. Indicator only — does not invalidate owned assets."""
    dt = parse_deadline(deadline)
    if dt is None:
        return "unknown"
    current = now or _now()
    return "expired" if current >= dt else "open"


def enrich_asset(asset: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    out = deepcopy(asset)
    out["redeem_window"] = redeem_window(out.get("redemption_deadline"), now=now)
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Register at {path} must be a mapping")
    return raw


def ensure_register(*, force_reseed: bool = False) -> dict[str, Any]:
    """Ensure data/asset-register.yaml exists; seed from humble inventory if empty/missing."""
    path = register_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and not force_reseed:
        doc = _load_yaml(path)
        assets = doc.get("assets")
        if isinstance(assets, list) and len(assets) > 0:
            return doc
    seed = _load_yaml(seed_path())
    doc = {
        "version": int(seed.get("version") or 1),
        "project": seed.get("project") or "vellum",
        "brand_family": seed.get("brand_family") or "control-alt-games",
        "vault_root": seed.get("vault_root") or "/mnt/data/vault/vellum",
        "source": seed.get("source") or str(seed_path()),
        "seeded_at": _now().isoformat(),
        "assets": list(seed.get("assets") or []),
    }
    path.write_text(yaml.dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    # Optional mirror into vault index (private data plane)
    vault_mirror = os.environ.get("VELLUM_VAULT_REGISTER_PATH", "").strip()
    if vault_mirror:
        mirror = Path(vault_mirror)
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return doc


def list_assets(
    *,
    q: str | None = None,
    engine: str | None = None,
    redeem_window_filter: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    doc = ensure_register()
    assets = [enrich_asset(a, now=now) for a in (doc.get("assets") or []) if isinstance(a, dict)]
    if engine:
        eng = engine.strip().lower()
        assets = [a for a in assets if str(a.get("engine") or "").lower() == eng]
    if redeem_window_filter:
        rw = redeem_window_filter.strip().lower()
        assets = [a for a in assets if a.get("redeem_window") == rw]
    if q:
        needle = q.strip().lower()
        if needle:
            def matches(a: dict[str, Any]) -> bool:
                blob = " ".join(
                    str(a.get(k) or "")
                    for k in ("display_name", "package_type", "project_fit", "store_label", "id", "engine")
                ).lower()
                tags = " ".join(str(t) for t in (a.get("tags") or [])).lower()
                return needle in blob or needle in tags

            assets = [a for a in assets if matches(a)]
    assets.sort(key=lambda a: int(a.get("list_index") or 0))
    return assets


def get_asset(asset_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    aid = asset_id.strip()
    for asset in list_assets(now=now):
        if asset.get("id") == aid:
            return asset
    return None


def _persist_register(doc: dict[str, Any]) -> None:
    path = register_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    vault_mirror = os.environ.get("VELLUM_VAULT_REGISTER_PATH", "").strip()
    if vault_mirror:
        mirror = Path(vault_mirror)
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def patch_asset(
    asset_id: str,
    *,
    redemption_status: str | None = None,
    raw_location: str | None = None,
    intake_notes: str | None = None,
) -> dict[str, Any]:
    """Update mutable register fields for an owned asset (Slice E human checkpoints)."""
    aid = asset_id.strip()
    doc = ensure_register()
    target: dict[str, Any] | None = None
    for row in doc.get("assets") or []:
        if isinstance(row, dict) and row.get("id") == aid:
            target = row
            break
    if target is None:
        raise KeyError(aid)
    if redemption_status is not None:
        target["redemption_status"] = redemption_status.strip()
    if raw_location is not None:
        target["raw_location"] = raw_location.strip() or None
    if intake_notes is not None:
        target["intake_notes"] = intake_notes
    _persist_register(doc)
    updated = get_asset(aid)
    assert updated is not None
    return updated


def register_summary(*, now: datetime | None = None) -> dict[str, Any]:
    assets = list_assets(now=now)
    open_n = sum(1 for a in assets if a.get("redeem_window") == "open")
    expired_n = sum(1 for a in assets if a.get("redeem_window") == "expired")
    return {
        "count": len(assets),
        "redeem_open": open_n,
        "redeem_expired": expired_n,
        "engines": sorted({str(a.get("engine")) for a in assets if a.get("engine")}),
    }


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:80]
