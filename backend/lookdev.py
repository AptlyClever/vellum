"""Lookdev derive — DerivedOutput records + project lanes (Slice F).

Copies previewable stills (png/jpg/…) from a staged pack into vault
04-lookdev / 05-derived-renders lanes. Never copies .uasset packs into
product git repos.
"""

from __future__ import annotations

import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import register as register_mod

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "derived-outputs.yaml"

KNOWN_LANES = (
    "slots",
    "hail-overlay",
    "field-command",
    "threshold-affairs",
    "lcard",
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


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


def catalog_path() -> Path:
    configured = os.environ.get("VELLUM_DERIVED_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_CATALOG


def _vault_catalog_path() -> Path | None:
    configured = os.environ.get("VELLUM_VAULT_DERIVED_PATH", "").strip()
    if configured:
        return Path(configured)
    return vault_root() / "02-index" / "derived-outputs.yaml"


def _empty_catalog() -> dict[str, Any]:
    return {"schema_version": 1, "outputs": []}


_CATALOG_CACHE: dict[str, Any] | None = None
_CATALOG_MTIME: float | None = None


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
    outputs = raw.get("outputs")
    if not isinstance(outputs, list):
        raw["outputs"] = []
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


def list_lanes() -> list[dict[str, Any]]:
    root = vault_root()
    lanes: list[dict[str, Any]] = []
    for lane_id in KNOWN_LANES:
        lookdev = root / "04-lookdev" / lane_id
        renders = root / "05-derived-renders" / lane_id
        lookdev.mkdir(parents=True, exist_ok=True)
        renders.mkdir(parents=True, exist_ok=True)
        lanes.append(
            {
                "id": lane_id,
                "lookdev_path": str(lookdev),
                "derived_renders_path": str(renders),
            }
        )
    return lanes


def infer_lanes(project_fit: str | None) -> list[str]:
    text = (project_fit or "").lower()
    found: list[str] = []
    mapping = (
        ("slots", "slots"),
        ("hail", "hail-overlay"),
        ("field command", "field-command"),
        ("threshold", "threshold-affairs"),
        ("lcard", "lcard"),
        ("arcade", "slots"),
    )
    for needle, lane in mapping:
        if needle in text and lane not in found:
            found.append(lane)
    return found or ["slots"]


def list_outputs(
    *,
    asset_id: str | None = None,
    lane: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    outputs = [o for o in load_catalog().get("outputs") or [] if isinstance(o, dict)]
    if asset_id:
        aid = asset_id.strip()
        outputs = [o for o in outputs if o.get("asset_id") == aid]
    if lane:
        outputs = [o for o in outputs if o.get("lane") == lane]
    outputs.sort(key=lambda o: str(o.get("created_at") or ""), reverse=True)
    return outputs[: max(1, min(limit, 1000))]


def get_output(output_id: str) -> dict[str, Any] | None:
    oid = output_id.strip()
    for row in load_catalog().get("outputs") or []:
        if isinstance(row, dict) and row.get("id") == oid:
            return row
    return None


def resolve_safe_file(output: dict[str, Any]) -> Path:
    """Return path only if it stays under the vault root."""
    raw = str(output.get("path") or "").strip()
    if not raw:
        raise FileNotFoundError("missing_path")
    path = Path(raw).resolve()
    root = vault_root().resolve()
    if root not in path.parents and path != root:
        raise PermissionError("path_outside_vault")
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _candidate_stills(stage: Path, *, limit: int = 6) -> list[Path]:
    if not stage.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(stage.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if path.name.endswith("~"):
            continue
        found.append(path)
        if len(found) >= limit:
            break
    return found


def _fab_listings_db() -> Path:
    raw = (os.environ.get("VELLUM_FAB_LISTINGS_DB") or "").strip()
    if raw:
        return Path(raw)
    return ROOT / "data" / "fab-listings.db"


def resolve_fab_thumbnail_url(display_name: str) -> str | None:
    """Match a register display_name to a Fab library catalog thumbnail URL."""
    import re
    import sqlite3

    name = (display_name or "").strip()
    if not name:
        return None
    db = _fab_listings_db()
    if not db.is_file():
        return None

    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

    name_n = _norm(name)
    try:
        conn = sqlite3.connect(str(db))
    except sqlite3.Error:
        return None
    try:
        rows = conn.execute("SELECT title, thumbnail FROM catalog").fetchall()
        best: tuple[int, str] | None = None
        for title, thumb in rows:
            if not thumb:
                continue
            t = str(title or "")
            tn = _norm(t)
            if not tn:
                continue
            score = 0
            if tn == name_n:
                score = 1000
            elif name_n and (name_n in tn or tn in name_n):
                score = 800 - abs(len(tn) - len(name_n))
            else:
                # First significant phrase before parenthetical / em-dash clutter.
                head = _norm(name.split("(")[0].split(" - ")[0])
                if len(head) >= 6 and (head in tn or tn.startswith(head)):
                    score = 600 - abs(len(tn) - len(head))
            if score > 0 and (best is None or score > best[0]):
                best = (score, str(thumb).strip())
        return best[1] if best else None
    finally:
        conn.close()


def _download_fab_thumbnail(url: str, dest: Path) -> Path:
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "vellum-lookdev/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
        ctype = (resp.headers.get("Content-Type") or "").lower()
    if len(data) < 100:
        raise ValueError("fab_thumbnail_too_small")
    suffix = ".jpg"
    if "png" in ctype:
        suffix = ".png"
    elif "webp" in ctype:
        suffix = ".webp"
    out = dest.with_suffix(suffix)
    out.write_bytes(data)
    return out


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    import struct
    import zlib

    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def render_placeholder_still(
    dest: Path,
    *,
    title: str,
    subtitle: str = "Vellum lookdev placeholder",
    width: int = 960,
    height: int = 540,
) -> Path:
    """Solid PNG hero when pack has no loose stills and no Fab catalog thumb.

    Kept dependency-free (no Pillow in the API image). For texture packs this
    unblocks Ready; Niagara packs still require MRQ for real lookdev.
    """
    import struct
    import zlib

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Dark slate background (#1a1f26)
    r, g, b = 26, 31, 38
    row = bytes([0, r, g, b] * width)  # filter None + RGB
    raw = row * height
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )
    out = dest.with_suffix(".png")
    out.write_bytes(png)
    # Title is recorded in DerivedOutput.note — pixel text needs a font stack.
    _ = title, subtitle
    return out


def derive_stills_for_asset(
    asset_id: str,
    *,
    lanes: list[str] | None = None,
    max_stills: int = 4,
) -> dict[str, Any]:
    """Copy preview stills from staged pack into lookdev + derived-renders lanes.

    Fallback order when stage has no loose png/jpg:
    1) Fab library catalog thumbnail
    2) Generated placeholder PNG (so texture packs still get a vault hero)
    """
    asset = register_mod.get_asset(asset_id)
    if not asset:
        raise KeyError(f"asset_not_found:{asset_id}")
    stage_raw = asset.get("raw_location")
    if not stage_raw:
        raise ValueError("raw_location_missing")
    stage = Path(str(stage_raw))
    if not stage.is_dir():
        raise FileNotFoundError(f"stage_missing:{stage}")

    stills = _candidate_stills(stage, limit=max_stills)
    source_note = (
        "Reference still copied from staged pack textures "
        "(not a Niagara viewport render). Raw .uasset packs stay in 01-source-bundles."
    )
    if not stills:
        url = resolve_fab_thumbnail_url(str(asset.get("display_name") or ""))
        thumb_dir = vault_root() / "06-readouts" / "_fab-thumbs"
        if url:
            stills = [_download_fab_thumbnail(url, thumb_dir / f"{asset_id}.img")]
            source_note = (
                f"Fab catalog thumbnail ({url}) — pack stage has no loose png/jpg previews."
            )
        else:
            stills = [
                render_placeholder_still(
                    thumb_dir / f"{asset_id}-placeholder.png",
                    title=str(asset.get("display_name") or asset_id),
                )
            ]
            source_note = (
                "Generated placeholder still — no loose pack previews and no Fab "
                "catalog thumbnail match."
            )

    target_lanes = lanes or infer_lanes(asset.get("project_fit"))
    for lane in target_lanes:
        if lane not in KNOWN_LANES:
            raise ValueError(f"unknown_lane:{lane}")

    root = vault_root()
    catalog = load_catalog()
    outputs: list[dict[str, Any]] = list(catalog.get("outputs") or [])
    created: list[dict[str, Any]] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    for lane in target_lanes:
        lookdev_dir = root / "04-lookdev" / lane / asset_id
        render_dir = root / "05-derived-renders" / lane / asset_id
        lookdev_dir.mkdir(parents=True, exist_ok=True)
        render_dir.mkdir(parents=True, exist_ok=True)

        for idx, src in enumerate(stills):
            dest_name = src.name
            dest = lookdev_dir / dest_name
            shutil.copy2(src, dest)
            kind = "still"
            path_out = dest
            # First still also lands as a derived-render hero for the lane
            if idx == 0:
                hero = render_dir / f"hero-{dest_name}"
                shutil.copy2(src, hero)
                path_out = hero
                kind = "hero-still"

            row = {
                "id": f"derived-{stamp}-{secrets.token_hex(3)}",
                "asset_id": asset_id,
                "lane": lane,
                "kind": kind,
                "path": str(path_out),
                "source_path": str(src),
                "created_at": _now(),
                "note": source_note,
            }
            outputs.append(row)
            created.append(row)

        readout = root / "06-readouts" / f"{asset_id}-{lane}.md"
        readout.parent.mkdir(parents=True, exist_ok=True)
        readout.write_text(
            f"# Lookdev readout — {asset.get('display_name') or asset_id}\n\n"
            f"- **Asset:** `{asset_id}`\n"
            f"- **Lane:** `{lane}`\n"
            f"- **Fit:** {asset.get('project_fit') or '—'}\n"
            f"- **Stills:** {len(stills)} preview files under "
            f"`04-lookdev/{lane}/{asset_id}/`\n"
            f"- **Rule:** do not copy raw marketplace packs into product git repos.\n"
            f"- **Derived at:** {_now()}\n",
            encoding="utf-8",
        )

    catalog["outputs"] = outputs
    save_catalog(catalog)
    return {
        "asset_id": asset_id,
        "lanes": target_lanes,
        "created_count": len(created),
        "outputs": created,
    }


def scratch_hint_path(engine: str = "unreal") -> Path:
    eng = (engine or "unreal").lower()
    path = vault_root() / "03-scratch-projects" / eng / "cag_asset_inspection"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ingest_niagara_render(
    asset_id: str,
    *,
    lane: str,
    source_file: Path,
    note: str | None = None,
    original_name: str | None = None,
    kind: str = "niagara-render",
    system_name: str | None = None,
) -> dict[str, Any]:
    """Register a Niagara lookdev still under 05-derived-renders (not pack textures)."""
    asset = register_mod.get_asset(asset_id)
    if not asset:
        raise KeyError(f"asset_not_found:{asset_id}")
    if lane not in KNOWN_LANES:
        raise ValueError(f"unknown_lane:{lane}")
    if not source_file.is_file():
        raise FileNotFoundError(str(source_file))
    suffix = source_file.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise ValueError(f"unsupported_image:{suffix}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_name = original_name or source_file.name
    safe_name = Path(safe_name).name
    if Path(safe_name).suffix.lower() not in IMAGE_SUFFIXES:
        safe_name = f"{safe_name}{suffix}"

    dest_dir = vault_root() / "05-derived-renders" / lane / asset_id / "niagara"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{stamp}-{safe_name}"
    shutil.copy2(source_file, dest)

    lookdev_dir = vault_root() / "04-lookdev" / lane / asset_id / "niagara"
    lookdev_dir.mkdir(parents=True, exist_ok=True)
    lookdev_copy = lookdev_dir / dest.name
    shutil.copy2(dest, lookdev_copy)

    row = {
        "id": f"derived-{stamp}-{secrets.token_hex(3)}",
        "asset_id": asset_id,
        "lane": lane,
        "kind": kind,
        "path": str(dest),
        "source_path": str(source_file),
        "created_at": _now(),
        "note": note
        or "Niagara MRQ lookdev still from Unreal capture.",
    }
    if system_name:
        row["system_name"] = system_name
    catalog = load_catalog()
    outputs = list(catalog.get("outputs") or [])
    outputs.append(row)
    catalog["outputs"] = outputs
    save_catalog(catalog)
    return row


def _link_or_copy(src: Path, dst: Path) -> None:
    """Prefer hardlink (cheap); fall back to copy when cross-device / unsupported."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def ingest_niagara_sequence(
    asset_id: str,
    *,
    system_name: str,
    source_dir: Path,
    lane: str | None = None,
    lanes: list[str] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Retain an MRQ PNG sequence once; catalog one row per lane sharing the path.

    Writes frames a single time under 05-derived-renders/sequences/… and hardlinks
    (or copies) once into 04-lookdev/sequences/…. Dual-lane Capture used to zip→POST
    twice and copy trees four times; that was the pack ingest bottleneck.
    """
    asset = register_mod.get_asset(asset_id)
    if not asset:
        raise KeyError(f"asset_not_found:{asset_id}")
    if not source_dir.is_dir():
        raise FileNotFoundError(str(source_dir))

    lane_list: list[str] = []
    if lanes:
        lane_list.extend([str(x).strip() for x in lanes if str(x).strip()])
    if lane and str(lane).strip() and str(lane).strip() not in lane_list:
        lane_list.append(str(lane).strip())
    if not lane_list:
        raise ValueError("lanes_required")
    for ln in lane_list:
        if ln not in KNOWN_LANES:
            raise ValueError(f"unknown_lane:{ln}")

    frames = sorted(
        [p for p in source_dir.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    )
    if not frames:
        raise ValueError("empty_sequence")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_sys = "".join(c if c.isalnum() or c in "-_" else "_" for c in system_name) or "system"
    seq_name = f"{stamp}-{safe_sys}"
    # Lane-agnostic path — all catalog rows share this directory.
    dest_dir = (
        vault_root()
        / "05-derived-renders"
        / "sequences"
        / asset_id
        / seq_name
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src in frames:
        shutil.copy2(src, dest_dir / src.name)

    lookdev_dir = vault_root() / "04-lookdev" / "sequences" / asset_id / seq_name
    lookdev_dir.mkdir(parents=True, exist_ok=True)
    for src in dest_dir.iterdir():
        if src.is_file():
            _link_or_copy(src, lookdev_dir / src.name)

    created = _now()
    rows: list[dict[str, Any]] = []
    catalog = load_catalog()
    outputs = list(catalog.get("outputs") or [])
    for ln in lane_list:
        row = {
            "id": f"derived-{stamp}-{secrets.token_hex(3)}",
            "asset_id": asset_id,
            "lane": ln,
            "kind": "niagara-sequence",
            "path": str(dest_dir),
            "lookdev_path": str(lookdev_dir),
            "source_path": str(source_dir),
            "frame_count": len(frames),
            "system_name": system_name,
            "created_at": created,
            "note": note or "Niagara MRQ PNG sequence retained for lookdev.",
            "shared_sequence": True,
        }
        outputs.append(row)
        rows.append(row)
    catalog["outputs"] = outputs
    save_catalog(catalog)
    # Back-compat: single-lane callers still get a lone dict via API wrapper.
    return {"outputs": rows, "path": str(dest_dir), "frame_count": len(frames)}
