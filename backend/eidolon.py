"""Eidolon rendered-image browser — read-only proxy into Eidolon batches.

Vellum does not author images here; it surfaces Eidolon's batch artifacts
(symbols, bezel plates, sprite sheets) for operator browsing.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

BATCH_ID_RE = re.compile(r"^batch-[A-Za-z0-9-]+$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Image groups nested under a batch result.
_IMAGE_GROUPS = ("symbols", "plates", "sheets")


class EidolonError(RuntimeError):
    """Eidolon is unreachable or returned an unexpected payload."""


def base_url() -> str:
    return (os.environ.get("EIDOLON_BASE_URL") or "http://192.168.68.93:7860").rstrip(
        "/"
    )


def _iso_from_ts(value: Any) -> str | None:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _resolution(width: Any, height: Any) -> str | None:
    try:
        w = int(width)
        h = int(height)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return f"{w}×{h}"


def _dims_from_meta(meta: dict[str, Any]) -> tuple[int | None, int | None]:
    try:
        w = int(meta["width"]) if meta.get("width") is not None else None
        h = int(meta["height"]) if meta.get("height") is not None else None
    except (TypeError, ValueError):
        w, h = None, None
    if w and h:
        return w, h
    try:
        cols = int(meta.get("cols") or 0)
        rows = int(meta.get("rows") or 0)
        cell = int(meta.get("cell_px") or 0)
    except (TypeError, ValueError):
        return None, None
    if cols > 0 and rows > 0 and cell > 0:
        return cols * cell, rows * cell
    return None, None


def _filename_from_meta(name: str, meta: dict[str, Any]) -> str | None:
    raw = str(meta.get("filename") or "").strip()
    if not raw:
        path = str(meta.get("texture_path") or meta.get("path") or "").strip()
        if path:
            raw = path.rsplit("/", 1)[-1]
    if not raw:
        # Symbols often only have a role key; default to PNG.
        raw = f"{name}.png" if "." not in name else name
    if not FILENAME_RE.fullmatch(raw):
        return None
    return raw


def _public_item(
    *,
    batch: dict[str, Any],
    group: str,
    name: str,
    meta: dict[str, Any],
) -> dict[str, Any] | None:
    batch_id = str(batch.get("id") or "").strip()
    if not BATCH_ID_RE.fullmatch(batch_id):
        return None
    filename = _filename_from_meta(name, meta)
    if not filename:
        return None
    width, height = _dims_from_meta(meta)
    asset_name = str(batch.get("asset_id") or batch.get("brief_version") or batch_id)
    role = str(meta.get("role") or name).strip() or name
    render_id = f"{batch_id}/{filename}"
    rendered_at = _iso_from_ts(batch.get("created_at")) or _iso_from_ts(
        batch.get("updated_at")
    )
    return {
        "id": render_id,
        "batch_id": batch_id,
        "filename": filename,
        "asset_name": asset_name,
        "label": role,
        "group": group,
        "kind": str((batch.get("result") or {}).get("kind") or group),
        "status": str(batch.get("status") or ""),
        "lane": str(batch.get("lane") or "") or None,
        "provider": str(meta.get("provider") or batch.get("provider") or "") or None,
        "rendered_at": rendered_at,
        "width": width,
        "height": height,
        "resolution": _resolution(width, height),
        "file_url": (
            f"/api/eidolon/renders/{quote(batch_id, safe='')}"
            f"/{quote(filename, safe='')}/file"
        ),
    }


def flatten_batch(batch: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract browsable image rows from one Eidolon batch payload."""
    if not isinstance(batch, dict):
        return []
    result = batch.get("result")
    if not isinstance(result, dict):
        return []
    items: list[dict[str, Any]] = []
    for group in _IMAGE_GROUPS:
        bucket = result.get(group)
        if not isinstance(bucket, dict):
            continue
        for name, meta in bucket.items():
            if not isinstance(meta, dict):
                continue
            row = _public_item(
                batch=batch, group=group, name=str(name), meta=meta
            )
            if row:
                items.append(row)
    return items


def list_renders(*, limit: int = 200) -> dict[str, Any]:
    """Fetch Eidolon batches and return a flat, newest-first gallery list."""
    limit = max(1, min(int(limit), 1000))
    try:
        response = httpx.get(
            f"{base_url()}/api/batches",
            headers={"Accept": "application/json"},
            timeout=20.0,
        )
    except httpx.RequestError as exc:
        raise EidolonError("eidolon_unreachable") from exc
    if response.status_code != 200:
        raise EidolonError(f"eidolon_http_{response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise EidolonError("eidolon_invalid_response") from exc
    batches = payload.get("batches") if isinstance(payload, dict) else None
    if not isinstance(batches, list):
        raise EidolonError("eidolon_invalid_response")

    items: list[dict[str, Any]] = []
    for batch in batches:
        if isinstance(batch, dict):
            items.extend(flatten_batch(batch))

    items.sort(key=lambda row: row.get("rendered_at") or "", reverse=True)
    total = len(items)
    return {
        "schema_version": 1,
        "collection": "Eidolon Renders",
        "source": "eidolon",
        "eidolon_base_url": base_url(),
        "count": min(total, limit),
        "total": total,
        "limit": limit,
        "items": items[:limit],
    }


def fetch_artifact(
    batch_id: str, filename: str, *, timeout: float = 30.0
) -> tuple[bytes, str]:
    """Proxy one Eidolon artifact; returns (bytes, content_type)."""
    batch_id = (batch_id or "").strip()
    filename = (filename or "").strip()
    if not BATCH_ID_RE.fullmatch(batch_id):
        raise ValueError("batch_id_invalid")
    if not FILENAME_RE.fullmatch(filename):
        raise ValueError("filename_invalid")
    url = f"{base_url()}/api/batches/{batch_id}/artifacts/{filename}"
    try:
        response = httpx.get(url, timeout=timeout)
    except httpx.RequestError as exc:
        raise EidolonError("eidolon_unreachable") from exc
    if response.status_code == 404:
        raise FileNotFoundError(filename)
    if response.status_code != 200:
        raise EidolonError(f"eidolon_http_{response.status_code}")
    content_type = response.headers.get("content-type") or "application/octet-stream"
    return response.content, content_type.split(";")[0].strip()
