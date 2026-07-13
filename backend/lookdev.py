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


def load_catalog() -> dict[str, Any]:
    path = catalog_path()
    if not path.is_file():
        return _empty_catalog()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return _empty_catalog()
    outputs = raw.get("outputs")
    if not isinstance(outputs, list):
        raw["outputs"] = []
    raw.setdefault("schema_version", 1)
    return raw


def save_catalog(doc: dict[str, Any]) -> None:
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(doc, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    mirror = _vault_catalog_path()
    if mirror is not None:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(text, encoding="utf-8")


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
    return outputs[: max(1, min(limit, 500))]


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


def derive_stills_for_asset(
    asset_id: str,
    *,
    lanes: list[str] | None = None,
    max_stills: int = 4,
) -> dict[str, Any]:
    """Copy preview stills from staged pack into lookdev + derived-renders lanes."""
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
    if not stills:
        raise ValueError("no_preview_stills")

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
                "note": (
                    "Reference still copied from staged pack textures "
                    "(not a Niagara viewport render). Raw .uasset packs stay in 01-source-bundles."
                ),
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
