"""Visual Research catalog — reference/inspiration images (not game-ready assets).

Persists metadata in data/visual-research.yaml (mirrored to vault 02-index)
and image bytes under vault 07-visual-research/<id>/. Bandit and other
consumers get read APIs; mutations require VELLUM_RESEARCH_WRITE_TOKEN.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "visual-research.yaml"

ASSET_TYPE = "visual-research"
COLLECTION = "Visual Research"

# Suffix → canonical format label
SUPPORTED_FORMATS = {
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".gif": "gif",
    ".webp": "webp",
    ".svg": "svg",
}

MIME_BY_FORMAT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
}

# Dangerous SVG patterns (scripts, handlers, external refs).
_SVG_SCRIPT_RE = re.compile(
    r"<script\b|</script\s*>|javascript:|data:text/html|<\s*foreignObject\b",
    re.IGNORECASE,
)
_SVG_EVENT_RE = re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE)
_SVG_XLINK_EXTERNAL_RE = re.compile(
    r"(?:xlink:)?href\s*=\s*[\"']\s*https?://",
    re.IGNORECASE,
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def vault_root() -> Path:
    configured = os.environ.get("VELLUM_VAULT_ROOT", "").strip()
    if configured:
        return Path(configured)
    return Path("/mnt/data/vault/vellum")


def catalog_path() -> Path:
    configured = os.environ.get("VELLUM_RESEARCH_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_CATALOG


def _vault_catalog_path() -> Path | None:
    configured = os.environ.get("VELLUM_VAULT_RESEARCH_PATH", "").strip()
    if configured:
        return Path(configured)
    return vault_root() / "02-index" / "visual-research.yaml"


def write_token() -> str:
    return (os.environ.get("VELLUM_RESEARCH_WRITE_TOKEN") or "").strip()


def require_write_token(authorization: str | None) -> None:
    """Raise PermissionError with visual_research_read_only when not authorized."""
    expected = write_token()
    if not expected:
        raise PermissionError("visual_research_read_only")
    header = (authorization or "").strip()
    if not header.lower().startswith("bearer "):
        raise PermissionError("visual_research_read_only")
    provided = header[7:].strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise PermissionError("visual_research_read_only")


def _empty_catalog() -> dict[str, Any]:
    return {"schema_version": 1, "items": []}


_CATALOG_CACHE: dict[str, Any] | None = None
_CATALOG_MTIME: float | None = None


def clear_catalog_cache() -> None:
    global _CATALOG_CACHE, _CATALOG_MTIME
    _CATALOG_CACHE = None
    _CATALOG_MTIME = None


def load_catalog() -> dict[str, Any]:
    global _CATALOG_CACHE, _CATALOG_MTIME
    path = catalog_path()
    try:
        mtime = path.stat().st_mtime if path.is_file() else None
    except OSError:
        mtime = None
    if (
        _CATALOG_CACHE is not None
        and mtime is not None
        and _CATALOG_MTIME == mtime
    ):
        return _CATALOG_CACHE
    if not path.is_file():
        _CATALOG_CACHE = _empty_catalog()
        _CATALOG_MTIME = mtime
        return _CATALOG_CACHE
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raw = _empty_catalog()
    items = raw.get("items")
    if not isinstance(items, list):
        raw["items"] = []
    raw.setdefault("schema_version", 1)
    _CATALOG_CACHE = raw
    _CATALOG_MTIME = mtime
    return raw


def save_catalog(doc: dict[str, Any]) -> None:
    global _CATALOG_CACHE, _CATALOG_MTIME
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(doc, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    mirror = _vault_catalog_path()
    if mirror is not None:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(text, encoding="utf-8")
    _CATALOG_CACHE = doc
    try:
        _CATALOG_MTIME = path.stat().st_mtime
    except OSError:
        _CATALOG_MTIME = None


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:60] or "image"


def _detect_format(data: bytes, filename: str | None = None) -> str:
    """Detect image format from magic bytes (and SVG content). Raise ValueError."""
    if not data:
        raise ValueError("empty_file")

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"

    # SVG: text starting with optional BOM/whitespace/XML decl, then <svg
    head = data[:4096]
    try:
        text = head.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("unsupported_image") from exc
    stripped = text.lstrip()
    if stripped.lower().startswith("<?xml"):
        # Skip XML declaration
        end = stripped.find("?>")
        if end >= 0:
            stripped = stripped[end + 2 :].lstrip()
    if stripped.lower().startswith("<!doctype"):
        nl = stripped.find(">")
        if nl >= 0:
            stripped = stripped[nl + 1 :].lstrip()
    if not stripped.lower().startswith("<svg"):
        # Fall back to extension only when content is ambiguous — still reject.
        suffix = Path(filename or "").suffix.lower()
        if suffix in SUPPORTED_FORMATS:
            raise ValueError("content_mismatch")
        raise ValueError("unsupported_image")
    return "svg"


def _sanitize_svg(data: bytes) -> bytes:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid_svg") from exc
    if _SVG_SCRIPT_RE.search(text) or _SVG_EVENT_RE.search(text):
        raise ValueError("unsafe_svg")
    if _SVG_XLINK_EXTERNAL_RE.search(text):
        raise ValueError("unsafe_svg")
    # Drop XML external-entity declarations.
    if re.search(r"<!ENTITY\b", text, re.IGNORECASE):
        raise ValueError("unsafe_svg")
    return text.encode("utf-8")


def _image_dimensions(data: bytes, fmt: str) -> tuple[int | None, int | None]:
    if fmt == "svg":
        return None, None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
            return int(w), int(h)
    except Exception:
        return None, None


def _validate_source_url(url: str | None) -> str | None:
    if url is None:
        return None
    text = str(url).strip()
    if not text:
        return None
    if len(text) > 2000:
        raise ValueError("source_url_too_long")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("source_url_must_be_http")
    if not parsed.netloc:
        raise ValueError("source_url_invalid")
    return text


def _parse_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,;\n]+", raw)
    elif isinstance(raw, list):
        parts = [str(x) for x in raw]
    else:
        raise ValueError("tags_invalid")
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        tag = part.strip().lower()[:64]
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= 32:
            break
    return out


def _public_item(row: dict[str, Any]) -> dict[str, Any]:
    """Return a catalog row with a stable public shape for Bandit/UI."""
    rid = str(row.get("id") or "")
    fmt = str(row.get("format") or "")
    return {
        "id": rid,
        "asset_type": ASSET_TYPE,
        "collection": COLLECTION,
        "title": row.get("title") or rid,
        "caption": row.get("caption") or None,
        "tags": list(row.get("tags") or []),
        "source_url": row.get("source_url") or None,
        "captured_at": row.get("captured_at") or row.get("created_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at") or row.get("created_at"),
        "format": fmt,
        "mime_type": row.get("mime_type") or MIME_BY_FORMAT.get(fmt),
        "original_filename": row.get("original_filename"),
        "byte_size": row.get("byte_size"),
        "width": row.get("width"),
        "height": row.get("height"),
        "checksum_sha256": row.get("checksum_sha256"),
        "rights": row.get("rights") or None,
        "attribution": row.get("attribution") or None,
        "file_url": f"/api/visual-research/{rid}/file" if rid else None,
    }


def list_items(
    *,
    q: str | None = None,
    tag: str | None = None,
    format: str | None = None,  # noqa: A002 — API filter name
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    items = [i for i in load_catalog().get("items") or [] if isinstance(i, dict)]
    if q:
        needle = q.strip().lower()
        if needle:

            def matches(row: dict[str, Any]) -> bool:
                blob = " ".join(
                    [
                        str(row.get("title") or ""),
                        str(row.get("caption") or ""),
                        str(row.get("source_url") or ""),
                        str(row.get("attribution") or ""),
                        str(row.get("rights") or ""),
                        " ".join(str(t) for t in (row.get("tags") or [])),
                        str(row.get("original_filename") or ""),
                        str(row.get("format") or ""),
                    ]
                ).lower()
                return needle in blob

            items = [i for i in items if matches(i)]
    if tag:
        t = tag.strip().lower()
        items = [
            i
            for i in items
            if t in [str(x).lower() for x in (i.get("tags") or [])]
        ]
    if format:
        fmt = format.strip().lower()
        if fmt == "jpeg":
            fmt = "jpg"
        items = [i for i in items if str(i.get("format") or "").lower() == fmt]

    items.sort(key=lambda o: str(o.get("captured_at") or o.get("created_at") or ""), reverse=True)
    total = len(items)
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    page = items[offset : offset + limit]
    return {
        "schema_version": 1,
        "asset_type": ASSET_TYPE,
        "collection": COLLECTION,
        "count": len(page),
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_public_item(i) for i in page],
    }


def get_item(research_id: str) -> dict[str, Any] | None:
    rid = research_id.strip()
    for row in load_catalog().get("items") or []:
        if isinstance(row, dict) and row.get("id") == rid:
            return _public_item(row)
    return None


def get_raw_item(research_id: str) -> dict[str, Any] | None:
    rid = research_id.strip()
    for row in load_catalog().get("items") or []:
        if isinstance(row, dict) and row.get("id") == rid:
            return row
    return None


def resolve_safe_file(item: dict[str, Any]) -> Path:
    raw = str(item.get("path") or "").strip()
    if not raw:
        raise FileNotFoundError("missing_path")
    path = Path(raw).resolve()
    root = vault_root().resolve()
    if root not in path.parents and path != root:
        raise PermissionError("path_outside_vault")
    if "07-visual-research" not in path.parts:
        raise PermissionError("path_outside_vault")
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def ingest_image(
    *,
    data: bytes,
    filename: str | None = None,
    title: str | None = None,
    caption: str | None = None,
    source_url: str | None = None,
    captured_at: str | None = None,
    tags: Any = None,
    rights: str | None = None,
    attribution: str | None = None,
) -> dict[str, Any]:
    """Validate bytes, persist under vault, append catalog row. Returns public item."""
    fmt = _detect_format(data, filename)
    if fmt == "svg":
        data = _sanitize_svg(data)

    # Extension hint vs detected format
    suffix = Path(filename or "").suffix.lower()
    if suffix and suffix in SUPPORTED_FORMATS and SUPPORTED_FORMATS[suffix] != fmt:
        raise ValueError("content_mismatch")

    source = _validate_source_url(source_url)
    tag_list = _parse_tags(tags)
    width, height = _image_dimensions(data, fmt)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    rid = f"vr-{stamp}-{secrets.token_hex(3)}"
    base_name = Path(filename or f"image.{fmt}").name
    safe_stem = _slugify(Path(base_name).stem) or "image"
    stored_name = f"{safe_stem}.{fmt if fmt != 'jpg' else 'jpg'}"
    if fmt == "jpg" and stored_name.endswith(".jpeg"):
        stored_name = stored_name[:-5] + ".jpg"

    dest_dir = vault_root() / "07-visual-research" / rid
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / stored_name
    dest.write_bytes(data)

    created = _now()
    captured = (captured_at or "").strip() or created
    display_title = (title or "").strip() or Path(base_name).stem or rid

    row = {
        "id": rid,
        "asset_type": ASSET_TYPE,
        "collection": COLLECTION,
        "title": display_title[:300],
        "caption": (caption or "").strip()[:2000] or None,
        "tags": tag_list,
        "source_url": source,
        "captured_at": captured,
        "created_at": created,
        "updated_at": created,
        "format": fmt,
        "mime_type": MIME_BY_FORMAT[fmt],
        "original_filename": base_name[:300],
        "byte_size": len(data),
        "width": width,
        "height": height,
        "checksum_sha256": hashlib.sha256(data).hexdigest(),
        "rights": (rights or "").strip()[:500] or None,
        "attribution": (attribution or "").strip()[:1000] or None,
        "path": str(dest),
    }

    catalog = load_catalog()
    items = list(catalog.get("items") or [])
    items.append(row)
    catalog["items"] = items
    save_catalog(catalog)
    return _public_item(row)


def update_item(
    research_id: str,
    *,
    title: str | None = None,
    caption: str | None = None,
    tags: Any = None,
    source_url: str | None = ...,  # type: ignore[assignment]
    captured_at: str | None = None,
    rights: str | None = ...,  # type: ignore[assignment]
    attribution: str | None = ...,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Patch mutable metadata fields. Raises KeyError if missing."""
    catalog = load_catalog()
    items = list(catalog.get("items") or [])
    idx = next(
        (i for i, row in enumerate(items) if isinstance(row, dict) and row.get("id") == research_id.strip()),
        None,
    )
    if idx is None:
        raise KeyError("visual_research_not_found")
    row = dict(items[idx])

    if title is not None:
        text = title.strip()
        if not text:
            raise ValueError("title_required")
        row["title"] = text[:300]
    if caption is not None:
        row["caption"] = caption.strip()[:2000] or None
    if tags is not None:
        row["tags"] = _parse_tags(tags)
    if source_url is not ...:
        row["source_url"] = _validate_source_url(source_url)  # type: ignore[arg-type]
    if captured_at is not None:
        row["captured_at"] = captured_at.strip() or row.get("captured_at")
    if rights is not ...:
        row["rights"] = ((rights or "").strip()[:500] or None)  # type: ignore[union-attr]
    if attribution is not ...:
        row["attribution"] = ((attribution or "").strip()[:1000] or None)  # type: ignore[union-attr]

    row["updated_at"] = _now()
    items[idx] = row
    catalog["items"] = items
    save_catalog(catalog)
    return _public_item(row)


def delete_item(research_id: str) -> dict[str, Any]:
    """Remove catalog row and on-disk files. Raises KeyError if missing."""
    catalog = load_catalog()
    items = list(catalog.get("items") or [])
    rid = research_id.strip()
    idx = next(
        (i for i, row in enumerate(items) if isinstance(row, dict) and row.get("id") == rid),
        None,
    )
    if idx is None:
        raise KeyError("visual_research_not_found")
    row = items.pop(idx)
    catalog["items"] = items
    save_catalog(catalog)

    # Best-effort remove storage directory
    dest_dir = vault_root() / "07-visual-research" / rid
    if dest_dir.is_dir():
        shutil.rmtree(dest_dir, ignore_errors=True)
    else:
        # Legacy: delete single path if present
        try:
            path = Path(str(row.get("path") or ""))
            if path.is_file():
                path.unlink(missing_ok=True)
        except OSError:
            pass
    return {"deleted": True, "id": rid}
