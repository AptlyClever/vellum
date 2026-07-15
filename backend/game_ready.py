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


def load_catalog() -> dict[str, Any]:
    path = catalog_path()
    if not path.is_file():
        return _empty()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return _empty()
    if not isinstance(raw.get("elements"), list):
        raw["elements"] = []
    raw.setdefault("schema_version", 1)
    return raw


def save_catalog(doc: dict[str, Any]) -> None:
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(doc, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    mirror = _vault_catalog_path()
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(text, encoding="utf-8")


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
    if path.suffix.lower() == ".webm":
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


def publish_to_lane(element_id: str, lane: str) -> dict[str, Any]:
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
    lanes = list(row.get("lanes") or [])
    if lane not in lanes:
        lanes.append(lane)
        row["lanes"] = lanes
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
