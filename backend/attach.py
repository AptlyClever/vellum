"""Attach — promote Vellum DerivedOutput stills into product load paths.

Products do not mount the vault. Vellum copies PNGs into each consumer's
existing on-disk location (Hail glyph-hero-images, LCARD media, Bandit web).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import lookdev as lookdev_mod

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATTACHMENTS = ROOT / "data" / "attachments.yaml"

TARGETS = ("hail", "lcard", "bandit")

IMAGE_KINDS = frozenset({"still", "hero-still", "niagara-render"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def attachments_path() -> Path:
    configured = os.environ.get("VELLUM_ATTACHMENTS_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_ATTACHMENTS


def _vault_attachments_path() -> Path | None:
    configured = os.environ.get("VELLUM_VAULT_ATTACHMENTS_PATH", "").strip()
    if configured:
        return Path(configured)
    try:
        return lookdev_mod.vault_root() / "02-index" / "attachments.yaml"
    except Exception:
        return None


def _empty() -> dict[str, Any]:
    return {"schema_version": 1, "attachments": []}


def load_attachments() -> dict[str, Any]:
    path = attachments_path()
    if not path.is_file():
        return _empty()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return _empty()
    if not isinstance(raw.get("attachments"), list):
        raw["attachments"] = []
    raw.setdefault("schema_version", 1)
    return raw


def save_attachments(doc: dict[str, Any]) -> None:
    path = attachments_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    mirror = _vault_attachments_path()
    if mirror is not None:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def list_attachments(*, asset_id: str | None = None, target: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    rows = [r for r in load_attachments().get("attachments") or [] if isinstance(r, dict)]
    if asset_id:
        aid = asset_id.strip()
        rows = [r for r in rows if str(r.get("asset_id") or "") == aid]
    if target:
        t = target.strip().lower()
        rows = [r for r in rows if str(r.get("target") or "") == t]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[: max(1, min(limit, 500))]


def axiom_base_url() -> str:
    return (os.environ.get("AXIOM_BASE_URL") or "http://192.168.68.93:7895").rstrip("/")


def axiom_public_url() -> str:
    return (os.environ.get("AXIOM_PUBLIC_BASE_URL") or axiom_base_url()).rstrip("/")


def hail_glyph_images_dir() -> Path:
    configured = os.environ.get("AXIOM_GLYPH_HERO_IMAGES", "").strip()
    if configured:
        return Path(configured)
    return Path("/mnt/temp/config/ctrl-alt-axiom/config/hails/glyph-hero-images")


def lcard_media_dir() -> Path:
    configured = os.environ.get("LCARD_VELLUM_MEDIA_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path("/mnt/temp/config/control-alt-lcard/app/media/vellum")


def bandit_static_dir() -> Path:
    configured = os.environ.get("BANDIT_VELLUM_STATIC_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path("/mnt/temp/config/bandit/web/vellum")


def bandit_base_url() -> str:
    return (os.environ.get("BANDIT_BASE_URL") or "http://192.168.68.93:8766").rstrip("/")


def lcard_base_url() -> str:
    return (os.environ.get("LCARD_BASE_URL") or "http://192.168.68.93:8184").rstrip("/")


def targets_status() -> dict[str, Any]:
    hail_dir = hail_glyph_images_dir()
    lcard_dir = lcard_media_dir()
    bandit_dir = bandit_static_dir()
    return {
        "schema_version": 1,
        "targets": {
            "hail": {
                "id": "hail",
                "label": "Hail (Paintbox glyph)",
                "ready": hail_dir.parent.is_dir() or hail_dir.is_dir(),
                "land": str(hail_dir),
                "axiom_base": axiom_public_url(),
            },
            "lcard": {
                "id": "lcard",
                "label": "LCARD media library",
                "ready": True,
                "land": str(lcard_dir),
                "lcard_base": lcard_base_url(),
            },
            "bandit": {
                "id": "bandit",
                "label": "Bandit overlay preview",
                "ready": True,
                "land": str(bandit_dir),
                "bandit_base": bandit_base_url(),
            },
        },
    }


def _slug(text: str, *, max_len: int = 48) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (s or "asset")[:max_len]


def resolve_attach_png(output: dict[str, Any]) -> Path:
    """Pick a PNG file from a DerivedOutput (still or sequence directory)."""
    kind = str(output.get("kind") or "")
    raw = str(output.get("path") or "").strip()
    if not raw:
        raise FileNotFoundError("missing_path")
    path = Path(raw)
    root = lookdev_mod.vault_root().resolve()
    resolved = path.resolve()
    if root not in resolved.parents and resolved != root:
        raise PermissionError("path_outside_vault")

    if resolved.is_file() and resolved.suffix.lower() in lookdev_mod.IMAGE_SUFFIXES:
        return resolved

    if resolved.is_dir() or kind == "niagara-sequence":
        directory = resolved if resolved.is_dir() else resolved.parent
        frames = sorted(
            p
            for p in directory.rglob("*")
            if p.is_file() and p.suffix.lower() in lookdev_mod.IMAGE_SUFFIXES
        )
        if not frames:
            raise FileNotFoundError(f"no_frames_in_sequence:{directory}")
        # Prefer mid frame as a representative hero.
        return frames[len(frames) // 2]

    raise FileNotFoundError(f"not_an_image:{resolved}")


def prefer_output_for_asset(asset_id: str) -> dict[str, Any] | None:
    """Best still for attach: hail-overlay renders, then slots, then any still."""
    outputs = lookdev_mod.list_outputs(asset_id=asset_id, limit=200)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for row in outputs:
        kind = str(row.get("kind") or "")
        lane = str(row.get("lane") or "")
        if kind == "niagara-sequence":
            score = 10 if lane == "hail-overlay" else 5
        elif kind in IMAGE_KINDS:
            if lane == "hail-overlay":
                score = 100 if kind == "niagara-render" else 80
            elif lane == "slots":
                score = 60 if kind == "niagara-render" else 40
            else:
                score = 20
        else:
            continue
        ranked.append((score, row))
    if not ranked:
        return None
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1]


def _record_attachment(row: dict[str, Any]) -> dict[str, Any]:
    doc = load_attachments()
    rows = list(doc.get("attachments") or [])
    rows.append(row)
    doc["attachments"] = rows
    save_attachments(doc)
    return row


def _http_json(method: str, url: str, body: dict[str, Any] | None = None, *, timeout: float = 45) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"http_{exc.code}:{detail}") from exc


def attach_hail(derived_output_id: str, *, register_glyph: bool = True) -> dict[str, Any]:
    out = lookdev_mod.get_output(derived_output_id)
    if not out:
        raise KeyError("derived_output_not_found")
    src = resolve_attach_png(out)
    asset_id = str(out.get("asset_id") or "asset")
    short = secrets.token_hex(3)
    fname = f"vellum-{_slug(asset_id)}-{short}.png"
    dest_dir = hail_glyph_images_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / fname
    shutil.copy2(src, dest)

    glyph_id = f"custom-vellum-{_slug(asset_id)}-{short}"
    target_ref: dict[str, Any] = {
        "glyph_id": glyph_id,
        "image_path": fname,
        "dest": str(dest),
    }
    deep_link = f"{axiom_public_url()}/#/axiom/hails/forge?glyph={glyph_id}"

    if register_glyph:
        width = height = 0
        try:
            from PIL import Image

            with Image.open(dest) as im:
                width, height = im.size
        except Exception:
            width = height = 0
        image_asset: dict[str, Any] = {"path": fname}
        if width and height:
            image_asset["width"] = int(width)
            image_asset["height"] = int(height)
        body = {
            "glyph_id": glyph_id,
            "label": f"{asset_id} (Vellum)",
            "source": "vellum_attach",
            "style_base": "ca-badge-medallion-v1",
            "representation_kind": "image",
            "image_asset": image_asset,
            "visual": {
                "effect_id": "transporter",
                "palette_id": "axiom_dark_cyan",
                "scale": "large",
                "placement_id": "upper_center",
                "presentation_template_id": "stage-medallion-v1",
            },
            "fallback_emoji": "✦",
            "animation_enabled": True,
            "speed_tier": "normal",
            "transition_style": "fade",
        }
        registered = _http_json(
            "POST",
            f"{axiom_base_url()}/api/hails/composer/register-glyph",
            body,
        )
        target_ref["registered"] = {
            "glyph_id": registered.get("glyph_id") or glyph_id,
            "label": registered.get("label"),
        }

    return _record_attachment(
        {
            "id": f"attach-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{short}",
            "derived_output_id": derived_output_id,
            "asset_id": asset_id,
            "target": "hail",
            "target_ref": target_ref,
            "status": "attached",
            "deep_link": deep_link,
            "created_at": _now(),
        }
    )


def attach_lcard(derived_output_id: str) -> dict[str, Any]:
    out = lookdev_mod.get_output(derived_output_id)
    if not out:
        raise KeyError("derived_output_not_found")
    src = resolve_attach_png(out)
    asset_id = str(out.get("asset_id") or "asset")
    short = secrets.token_hex(3)
    media_dir = lcard_media_dir()
    media_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{_slug(asset_id)}-{short}.png"
    dest = media_dir / fname
    shutil.copy2(src, dest)

    manifest_path = media_dir / "manifest.json"
    manifest: dict[str, Any]
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {"schema_version": 1, "items": []}
    else:
        manifest = {"schema_version": 1, "items": []}
    items = list(manifest.get("items") or [])
    item = {
        "id": f"lcard-media-{short}",
        "title": asset_id,
        "asset_id": asset_id,
        "derived_output_id": derived_output_id,
        "path": fname,
        "rel_url": f"/media/vellum/{fname}",
        "attached_at": _now(),
    }
    items.insert(0, item)
    manifest["items"] = items[:200]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    deep_link = f"{lcard_base_url()}/vellum-media.html"
    return _record_attachment(
        {
            "id": f"attach-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{short}",
            "derived_output_id": derived_output_id,
            "asset_id": asset_id,
            "target": "lcard",
            "target_ref": {"media_id": item["id"], "path": fname, "dest": str(dest)},
            "status": "attached",
            "deep_link": deep_link,
            "created_at": _now(),
        }
    )


def attach_bandit(derived_output_id: str) -> dict[str, Any]:
    out = lookdev_mod.get_output(derived_output_id)
    if not out:
        raise KeyError("derived_output_not_found")
    src = resolve_attach_png(out)
    asset_id = str(out.get("asset_id") or "asset")
    short = secrets.token_hex(3)
    slug = _slug(asset_id)
    dest_dir = bandit_static_dir() / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "hero.png"
    shutil.copy2(src, dest)

    fixtures_dir = dest_dir.parent.parent / "fixtures" / "presentation-payloads"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    fixture_name = f"vellum-{slug}.json"
    fixture = {
        "schema_version": 1,
        "source": "vellum_attach",
        "asset_id": asset_id,
        "hero_url": f"/static/vellum/{slug}/hero.png",
        "title": f"Vellum · {asset_id}",
    }
    (fixtures_dir / fixture_name).write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    deep_link = f"{bandit_base_url()}/vellum-preview?asset={slug}"
    return _record_attachment(
        {
            "id": f"attach-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{short}",
            "derived_output_id": derived_output_id,
            "asset_id": asset_id,
            "target": "bandit",
            "target_ref": {
                "path": str(dest),
                "hero_url": fixture["hero_url"],
                "fixture": fixture_name,
            },
            "status": "attached",
            "deep_link": deep_link,
            "created_at": _now(),
        }
    )


def attach(
    *,
    derived_output_id: str | None = None,
    asset_id: str | None = None,
    target: str,
    register_glyph: bool = True,
) -> dict[str, Any]:
    t = (target or "").strip().lower()
    if t not in TARGETS:
        raise ValueError(f"invalid_target:{target}")

    oid = (derived_output_id or "").strip()
    if not oid:
        aid = (asset_id or "").strip()
        if not aid:
            raise ValueError("derived_output_id_or_asset_id_required")
        preferred = prefer_output_for_asset(aid)
        if not preferred:
            raise KeyError("no_lookdev_output_for_asset")
        oid = str(preferred["id"])

    if t == "hail":
        return attach_hail(oid, register_glyph=register_glyph)
    if t == "lcard":
        return attach_lcard(oid)
    return attach_bandit(oid)
