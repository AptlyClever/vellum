"""Game-ready catalog — portable Conversion Factory outputs (not lookdev photos).

Manifest-driven index under vault 05-derived-renders/game-ready/ plus a YAML catalog.
Kinds: vfx-clip | sprite-sheet | model-gltf | texture | audio
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import lookdev as lookdev_mod
from . import register as register_mod

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "game-ready.yaml"

ELEMENT_KINDS = (
    "vfx-clip",
    "sprite-sheet",
    "model-gltf",
    "texture",
    "audio",
    "bake-plan",
    "manifest",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def catalog_path() -> Path:
    configured = os.environ.get("VELLUM_GAME_READY_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_CATALOG


def vault_game_ready_root() -> Path:
    return lookdev_mod.vault_root() / "05-derived-renders" / "game-ready"


def _vault_catalog_path() -> Path:
    return lookdev_mod.vault_root() / "02-index" / "game-ready.yaml"


def _empty() -> dict[str, Any]:
    return {"schema_version": 1, "elements": []}


# The catalog YAML grows past a megabyte with factory validation evidence;
# pyyaml's pure-Python loader takes seconds on it, so prefer libyaml and
# cache the parsed document keyed by file mtime/size.
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_catalog_cache: dict[str, Any] = {}


def _catalog_cache_key(path: Path) -> tuple[str, float, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_mtime, stat.st_size)


def load_catalog() -> dict[str, Any]:
    path = catalog_path()
    if not path.is_file():
        return _empty()
    key = _catalog_cache_key(path)
    if key is not None and _catalog_cache.get("key") == key:
        return _catalog_cache["doc"]
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_YAML_LOADER)
    if not isinstance(raw, dict):
        return _empty()
    if not isinstance(raw.get("elements"), list):
        raw["elements"] = []
    raw.setdefault("schema_version", 1)
    if key is not None:
        _catalog_cache["key"] = key
        _catalog_cache["doc"] = raw
    return raw


def save_catalog(doc: dict[str, Any]) -> None:
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(doc, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    mirror = _vault_catalog_path()
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(text, encoding="utf-8")
    key = _catalog_cache_key(path)
    if key is not None:
        _catalog_cache["key"] = key
        _catalog_cache["doc"] = doc
    else:
        _catalog_cache.clear()


def list_elements(
    *,
    asset_id: str | None = None,
    kind: str | None = None,
    lane: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = list(load_catalog().get("elements") or [])
    if asset_id:
        rows = [r for r in rows if r.get("asset_id") == asset_id]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if lane:
        rows = [r for r in rows if lane in (r.get("lanes") or [])]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[:limit]


def get_element(element_id: str) -> dict[str, Any] | None:
    for row in load_catalog().get("elements") or []:
        if row.get("id") == element_id:
            return row
    return None


def resolve_safe_file(row: dict[str, Any]) -> Path:
    root = lookdev_mod.vault_root().resolve()
    path = Path(str(row.get("path") or "")).expanduser()
    if not path.is_absolute():
        path = (root / path).resolve()
    else:
        path = path.resolve()
    if root not in path.parents and path != root:
        # also allow under vault game-ready even if symlink
        gr = vault_game_ready_root().resolve()
        if gr not in path.parents and path != gr:
            raise PermissionError("path_outside_vault")
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _build_element(
    *,
    asset_id: str,
    kind: str,
    path: Path,
    pack: str | None = None,
    lanes: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Copy the file into the vault and build a catalog row (no catalog I/O)."""
    if kind not in ELEMENT_KINDS:
        raise ValueError(f"unsupported_kind:{kind}")
    if register_mod.get_asset(asset_id) is None:
        raise KeyError(asset_id)
    dest_root = vault_game_ready_root() / (pack or asset_id) / kind
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = (dest_root / path.name).resolve()
    src = Path(path).resolve()
    if src != dest:
        shutil.copy2(src, dest)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return {
        "id": f"gr-{stamp}-{secrets.token_hex(3)}",
        "asset_id": asset_id,
        "pack": pack or asset_id,
        "kind": kind,
        "path": str(dest),
        "lanes": lanes or [],
        "meta": meta or {},
        "note": note,
        "created_at": _now(),
    }


def register_element(
    *,
    asset_id: str,
    kind: str,
    path: Path,
    pack: str | None = None,
    lanes: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    row = _build_element(
        asset_id=asset_id, kind=kind, path=path, pack=pack,
        lanes=lanes, meta=meta, note=note,
    )
    doc = load_catalog()
    doc["elements"].append(row)
    save_catalog(doc)
    return row


_RUN_KIND_BY_SUFFIX = {
    ".glb": "model-gltf",
    ".gltf": "model-gltf",
    ".jpg": "texture",
    ".jpeg": "texture",
    ".webp": "texture",
    ".wav": "audio",
    ".ogg": "audio",
    ".mp3": "audio",
    ".webm": "vfx-clip",
}

MAX_RUN_ELEMENTS = 500


def _path_parts_lower(path: Path) -> list[str]:
    return [p.lower() for p in path.parts]


def _is_vfx_sprite_sheet(path: Path) -> bool:
    name = path.name.lower()
    return (
        path.suffix.lower() == ".png"
        and ("sprite-sheet" in name or "spritesheet" in name)
    )


def _run_kind_for_path(path: Path) -> str | None:
    if _is_vfx_sprite_sheet(path):
        return "sprite-sheet"
    if path.suffix.lower() == ".png":
        return "texture"
    return _RUN_KIND_BY_SUFFIX.get(path.suffix.lower())


def _load_vfx_pack_metadata(extract_dir: Path) -> dict[str, dict[str, Any]]:
    """Read pack_vfx_media manifests so catalog rows carry validation evidence."""
    by_system: dict[str, dict[str, Any]] = {}
    for manifest in extract_dir.rglob("pack-manifest.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            continue
        packed = data.get("packed") or []
        if not isinstance(packed, list):
            continue
        for entry in packed:
            if isinstance(entry, dict) and entry.get("system"):
                by_system[str(entry["system"])] = entry
    return by_system


def _vfx_meta_for_path(path: Path, by_system: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if path.suffix.lower() != ".webm" and not _is_vfx_sprite_sheet(path):
        return None
    entry = by_system.get(path.parent.name)
    if not entry:
        return None
    meta: dict[str, Any] = {
        "system": entry.get("system"),
        "frames": entry.get("frames"),
        "frame_rate": entry.get("frame_rate"),
        "validation": entry.get("validation"),
    }
    name = path.name.lower()
    variant = next(
        (v for v in ("contained", "breakout") if name.endswith(f".{v}.webm")), None
    )
    if variant:
        meta["variant"] = variant
        details = entry.get(variant) or {}
        meta[variant] = {
            k: details.get(k) for k in ("source_crop", "width", "height")
        }
    elif path.suffix.lower() == ".webm":
        meta["webm_probe"] = entry.get("webm_probe")
    elif _is_vfx_sprite_sheet(path):
        meta["sprite_sheet"] = entry.get("sprite_sheet")
    return {k: v for k, v in meta.items() if v is not None}


def ingest_run_archive(extract_dir: Path, *, asset_id: str, pack: str) -> dict[str, Any]:
    """Ingest an extracted Conversion Factory run (all jobs for one pack).

    Aurora zips its local game-ready output tree for a pack and uploads it;
    every recognizable portable file becomes a catalog element. Manifests are
    registered too so a run with zero exports (pure-Niagara bake plan) still
    counts as conversion evidence and the factory does not retry forever.
    """
    if register_mod.get_asset(asset_id) is None:
        raise KeyError(asset_id)
    # Build all rows first, then write the catalog once — per-element
    # register_element() would rewrite the full YAML catalog per file.
    rows: list[dict[str, Any]] = []
    skipped = 0
    vfx_meta_by_system = _load_vfx_pack_metadata(extract_dir)
    for path in sorted(extract_dir.rglob("*")):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.endswith("manifest.json") or name == "bake-plan.json":
            kind = "manifest"
            if "bake" in name or "vfx" in str(path.parent).lower():
                kind = "bake-plan"
            rows.append(
                _build_element(
                    asset_id=asset_id, kind=kind, path=path, pack=pack,
                    note="factory-run manifest",
                )
            )
            continue
        kind = _run_kind_for_path(path)
        if kind is None:
            skipped += 1
            continue
        if len(rows) >= MAX_RUN_ELEMENTS:
            skipped += 1
            continue
        rows.append(
            _build_element(
                asset_id=asset_id,
                kind=kind,
                path=path,
                pack=pack,
                meta=_vfx_meta_for_path(path, vfx_meta_by_system),
            )
        )
    if rows:
        doc = load_catalog()
        # Re-upload of the same pack replaces its previous rows instead of duplicating.
        doc["elements"] = [
            e for e in (doc.get("elements") or [])
            if not (e.get("asset_id") == asset_id and e.get("pack") == pack)
        ]
        doc["elements"].extend(rows)
        save_catalog(doc)
    return {
        "schema_version": 1,
        "ok": True,
        "asset_id": asset_id,
        "pack": pack,
        "registered": len(rows),
        "skipped": skipped,
        # Return IDs so publishers can bind immediately without a catalog race
        # against a concurrent same-pack upload that replaces these rows.
        "elements": [
            {
                "id": r.get("id"),
                "kind": r.get("kind"),
                "path": r.get("path"),
                "pack": r.get("pack") or pack,
            }
            for r in rows
            if r.get("id")
        ],
    }


def ingest_manifest(manifest_path: Path, *, asset_id: str, pack: str | None = None) -> dict[str, Any]:
    """Ingest a Conversion Factory manifest.json into the catalog."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    pack = pack or str(data.get("pack") or asset_id)
    registered: list[dict[str, Any]] = []
    job = str(data.get("job") or "manifest")

    if job == "export-models":
        for item in data.get("exported") or []:
            p = Path(str(item.get("path") or ""))
            if p.is_file():
                registered.append(
                    register_element(
                        asset_id=asset_id,
                        kind="model-gltf",
                        path=p,
                        pack=pack,
                        meta={"class": item.get("class"), "asset": item.get("asset")},
                    )
                )
    elif job == "export-media":
        for item in data.get("exported") or []:
            p = Path(str(item.get("path") or ""))
            if not p.is_file():
                continue
            kind = "texture" if item.get("kind") == "texture" else "audio"
            registered.append(
                register_element(
                    asset_id=asset_id,
                    kind=kind,
                    path=p,
                    pack=pack,
                    meta={"asset": item.get("asset")},
                )
            )
    elif job == "bake-vfx":
        registered.append(
            register_element(
                asset_id=asset_id,
                kind="bake-plan",
                path=manifest_path,
                pack=pack,
                meta={"systems_found": data.get("systems_found")},
                note="bake plan — render + pack_vfx_media produces clips",
            )
        )
    else:
        registered.append(
            register_element(
                asset_id=asset_id,
                kind="manifest",
                path=manifest_path,
                pack=pack,
                meta={"job": job},
            )
        )

    return {
        "schema_version": 1,
        "ok": True,
        "asset_id": asset_id,
        "pack": pack,
        "registered": len(registered),
        "elements": registered,
    }


PRESENTATION_CONTAINMENTS = ("contained", "breakout", "ambient")
PRESENTATION_SPREADS = ("radial", "directional", "ambient-field")
PRESENTATION_MAX_DURATION_SECONDS = 10.0


def _validate_presentation(presentation: dict[str, Any]) -> dict[str, Any]:
    """Validate an authored presentation contract for a lane.

    The contract tells game runtimes how an effect behaves relative to its
    anchor (the game area / glyph frame): whether it stays contained, breaks
    out beyond the anchor, or runs as an ambient field.
    """
    anchor = str(presentation.get("anchor") or "").strip()
    if not anchor:
        raise ValueError("presentation_anchor_required")
    containment = str(presentation.get("containment") or "").strip()
    if containment not in PRESENTATION_CONTAINMENTS:
        raise ValueError(f"presentation_containment_invalid:{containment}")
    tier = str(presentation.get("tier") or "").strip()
    if not tier:
        raise ValueError("presentation_tier_required")

    cleaned: dict[str, Any] = {
        "anchor": anchor,
        "containment": containment,
        "tier": tier,
    }
    spread = presentation.get("spread")
    if spread is not None:
        if str(spread) not in PRESENTATION_SPREADS:
            raise ValueError(f"presentation_spread_invalid:{spread}")
        cleaned["spread"] = str(spread)
    scale = presentation.get("scale")
    if scale is not None:
        scale = float(scale)
        if scale <= 0:
            raise ValueError("presentation_scale_invalid")
        cleaned["scale"] = scale
    duration = presentation.get("max_duration_seconds")
    if duration is not None:
        duration = float(duration)
        if not 0 < duration <= PRESENTATION_MAX_DURATION_SECONDS:
            raise ValueError("presentation_max_duration_invalid")
        cleaned["max_duration_seconds"] = duration
    return cleaned


def publish_to_lane(
    element_id: str,
    lane: str,
    *,
    presentation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if lane not in lookdev_mod.KNOWN_LANES:
        raise ValueError(f"unknown_lane:{lane}")
    cleaned_presentation = (
        _validate_presentation(presentation) if presentation is not None else None
    )
    doc = load_catalog()
    row = None
    for r in doc.get("elements") or []:
        if r.get("id") == element_id:
            row = r
            break
    if row is None:
        raise KeyError(element_id)
    lanes = list(row.get("lanes") or [])
    if lane not in lanes:
        lanes.append(lane)
        row["lanes"] = lanes
        row["updated_at"] = _now()
        save_catalog(doc)
    if cleaned_presentation is not None:
        presentations = dict(row.get("presentation") or {})
        presentations[lane] = cleaned_presentation
        row["presentation"] = presentations
        row["updated_at"] = _now()
        save_catalog(doc)
    # Copy into lane-scoped game-ready bundle folder
    src = resolve_safe_file(row)
    dest_dir = (
        lookdev_mod.vault_root()
        / "05-derived-renders"
        / lane
        / str(row.get("asset_id"))
        / "game-ready"
        / str(row.get("kind"))
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    row["lane_paths"] = dict(row.get("lane_paths") or {})
    row["lane_paths"][lane] = str(dest)
    save_catalog(doc)
    return row


def unpublish_from_lane(element_id: str, lane: str) -> dict[str, Any]:
    if lane not in lookdev_mod.KNOWN_LANES:
        raise ValueError(f"unknown_lane:{lane}")
    doc = load_catalog()
    row = None
    for r in doc.get("elements") or []:
        if r.get("id") == element_id:
            row = r
            break
    if row is None:
        raise KeyError(element_id)

    changed = False
    lanes = list(row.get("lanes") or [])
    if lane in lanes:
        row["lanes"] = [p for p in lanes if p != lane]
        changed = True
    presentations = dict(row.get("presentation") or {})
    if lane in presentations:
        presentations.pop(lane, None)
        row["presentation"] = presentations
        changed = True
    lane_paths = dict(row.get("lane_paths") or {})
    if lane in lane_paths:
        try:
            lane_file = Path(str(lane_paths[lane]))
            if lane_file.is_file():
                lane_file.unlink()
        except OSError:
            pass
        lane_paths.pop(lane, None)
        row["lane_paths"] = lane_paths
        changed = True
    if changed:
        row["updated_at"] = _now()
        save_catalog(doc)
    return row
