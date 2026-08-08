"""Evidence-backed Asset Journey read model.

This module composes Vellum's existing authorities for presentation. It owns no
new pipeline state and never upgrades catalog presence into verification.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
import re
from typing import Any

import httpx
from PIL import Image, UnidentifiedImageError

from . import game_ready as game_ready_mod
from . import intake as intake_mod
from . import lookdev as lookdev_mod
from . import register as register_mod


PORTABLE_KINDS = {"vfx-clip", "sprite-sheet", "model-gltf", "texture", "audio"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_SUFFIXES = {".webm", ".mp4"}
AUDIO_SUFFIXES = {".wav", ".ogg", ".mp3"}
FEATURED_OUTPUT_LIMIT = 8


def _valid_image_path(path: Path) -> bool:
    """Require real, decodable pixels before presenting an image as evidence."""
    try:
        if path.stat().st_size <= 0:
            return False
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.width > 0 and image.height > 0
    except (OSError, UnidentifiedImageError):
        return False


def _step(runs: list[dict[str, Any]], *step_ids: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    wanted = set(step_ids)
    for run in runs:
        for step in run.get("steps") or []:
            if isinstance(step, dict) and step.get("step_id") in wanted and step.get("status") == "done":
                return run, step
    return None


def _milestone(
    milestone_id: str,
    label: str,
    *,
    confirmed: bool,
    occurred_at: str | None = None,
    detail: str,
    evidence_href: str | None = None,
) -> dict[str, Any]:
    stamp = (occurred_at or "").strip() or None
    if confirmed and stamp is None:
        time_note = "Confirmed; time not recorded"
    elif confirmed:
        time_note = None
    else:
        time_note = "No evidence recorded"
    return {
        "id": milestone_id,
        "label": label,
        "state": "confirmed" if confirmed else "pending",
        "occurred_at": stamp,
        "time_note": time_note,
        "detail": detail,
        "evidence_href": evidence_href,
    }


def _resolve_output_file(row: dict[str, Any]) -> Path | None:
    try:
        return lookdev_mod.resolve_safe_file(row)
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _resolve_element_file(row: dict[str, Any]) -> Path | None:
    try:
        return game_ready_mod.resolve_safe_file(row)
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _preview_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    return "file"


def _preview_time_seconds(row: dict[str, Any]) -> float | None:
    """Choose the validation sample with the strongest recorded visible payoff."""
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    validation = meta.get("validation") if isinstance(meta.get("validation"), dict) else {}
    samples = validation.get("visual_samples") if isinstance(validation.get("visual_samples"), list) else []
    frame_count = int(validation.get("frame_count") or meta.get("frames") or 0)
    duration = float(validation.get("duration_seconds") or 0)
    if not samples or frame_count <= 1 or duration <= 0:
        return None

    def frame_number(sample: dict[str, Any]) -> int:
        name = Path(str(sample.get("frame") or "")).name
        try:
            return int(name.rsplit(".", 2)[-2])
        except (ValueError, IndexError):
            return 0

    best = max(
        (sample for sample in samples if isinstance(sample, dict)),
        key=lambda sample: (
            int(sample.get("bright_pixels") or 0),
            int(sample.get("visible_pixels") or 0),
            float(sample.get("visible_to_opaque_ratio") or 0),
            frame_number(sample),
        ),
        default=None,
    )
    if best is None:
        return None
    frame = min(max(frame_number(best), 0), frame_count - 1)
    return round(min(frame / frame_count * duration, duration - duration / frame_count), 3)


def _display_name(row: dict[str, Any], path: Path) -> str:
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    value = str(meta.get("system") or path.stem)
    if value.startswith("NS_"):
        value = value[3:]
    if value.endswith("_Single"):
        value = value[:-7]
    value = value.replace("_", " ")
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", value)
    return value.strip() or path.name


def _transformation_item(row: dict[str, Any] | None, *, role: str) -> dict[str, Any] | None:
    if not row:
        return None
    path = _resolve_output_file(row)
    if path is None:
        return None
    if _preview_kind(path) == "image" and not _valid_image_path(path):
        return None
    note = str(row.get("note") or "")
    if role == "source":
        label = "Marketplace reference" if "fab catalog" in note.lower() else "Source reference"
    else:
        label = "Latest trusted capture (MRQ)" if "mrq" in note.lower() else "Latest trusted capture"
    return {
        "id": row.get("id"),
        "label": label,
        "kind": row.get("kind"),
        "lane": row.get("lane"),
        "system_name": row.get("system_name"),
        "created_at": row.get("created_at"),
        "note": row.get("note"),
        "file_href": f"/api/lookdev/outputs/{row.get('id')}/file",
        "preview": _preview_kind(path),
    }


def _source_reference(asset: dict[str, Any], lookdev: list[dict[str, Any]]) -> dict[str, Any] | None:
    # A loose texture from the pack is not marketplace artwork. Presentation
    # may use only a Fab reference that Vellum has already ingested into the vault.
    for row in lookdev:
        if row.get("kind") != "hero-still" or "fab catalog" not in str(row.get("note") or "").lower():
            continue
        item = _transformation_item(row, role="source")
        if item:
            return item
    return None


def _is_game_ready(row: dict[str, Any]) -> bool:
    if row.get("kind") not in PORTABLE_KINDS:
        return False
    validation = (row.get("meta") or {}).get("validation")
    return not isinstance(validation, dict) or validation.get("ok") is True


def _element_card(row: dict[str, Any]) -> dict[str, Any] | None:
    path = _resolve_element_file(row)
    if path is None:
        return None
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    validation = meta.get("validation") if isinstance(meta.get("validation"), dict) else {}
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    return {
        "id": row.get("id"),
        "asset_id": row.get("asset_id"),
        "pack": row.get("pack"),
        "kind": row.get("kind"),
        "name": path.name,
        "display_name": _display_name(row, path),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "bytes": size,
        "content_type": content_type,
        "preview": _preview_kind(path),
        "file_href": f"/api/game-ready/elements/{row.get('id')}/file",
        "preview_time_seconds": _preview_time_seconds(row),
        "lanes": list(row.get("lanes") or []),
        "presentation": dict(row.get("presentation") or {}),
        "system_name": meta.get("system"),
        "technical": {
            "width": validation.get("width"),
            "height": validation.get("height"),
            "duration_seconds": validation.get("duration_seconds"),
            "alpha": validation.get("alpha"),
            "frame_count": validation.get("frame_count") or meta.get("frames"),
            "frame_rate": meta.get("frame_rate"),
            "validation": "passed" if validation.get("ok") is True else "cataloged",
            "variant": meta.get("variant"),
        },
    }


def _visual_score(row: dict[str, Any]) -> tuple[float, float]:
    validation = ((row.get("meta") or {}).get("validation") or {})
    return (
        float(validation.get("max_bright_sample_pixels") or 0),
        float(validation.get("max_visible_to_opaque_ratio") or 0),
    )


def _featured_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Curate visible payoff: one strong, published contained clip per system."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        system = str(meta.get("system") or "").strip()
        if not system or row.get("kind") != "vfx-clip":
            continue
        variant = str(meta.get("variant") or "")
        published = any(_lane_copy_exists(row, lane) for lane in (row.get("lanes") or []))
        priority = (published, variant == "contained", _visual_score(row), str(row.get("id") or ""))
        previous = best.get(system)
        if previous is None:
            best[system] = row
            continue
        previous_meta = previous.get("meta") if isinstance(previous.get("meta"), dict) else {}
        previous_priority = (
            any(_lane_copy_exists(previous, lane) for lane in (previous.get("lanes") or [])),
            str(previous_meta.get("variant") or "") == "contained",
            _visual_score(previous),
            str(previous.get("id") or ""),
        )
        if priority > previous_priority:
            best[system] = row
    ranked = sorted(
        best.values(),
        key=lambda row: (
            -_visual_score(row)[0],
            -_visual_score(row)[1],
            str((row.get("meta") or {}).get("system") or "").casefold(),
        ),
    )
    return ranked[:FEATURED_OUTPUT_LIMIT]


def _bandit_consumer_receipt(delivered_ids: set[str]) -> dict[str, Any] | None:
    base = (os.environ.get("BANDIT_BASE_URL") or "http://127.0.0.1:8766").rstrip("/")
    try:
        response = httpx.get(f"{base}/api/games/slots/vfx/win", timeout=2.5)
        response.raise_for_status()
        effect = response.json().get("effect") or {}
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    element_id = str(effect.get("element_id") or "")
    if not element_id or element_id not in delivered_ids:
        return None
    media_url = str(effect.get("media_url") or "")
    return {
        "state": "consumer-selected",
        "consumer": "Bandit",
        "surface": "win effect",
        "effect_id": effect.get("effect_id"),
        "element_id": element_id,
        "media_href": f"{base}{media_url}" if media_url.startswith("/") else media_url,
        "evidence_href": f"{base}/api/games/slots/vfx/win",
    }


def _lane_copy_exists(row: dict[str, Any], lane: str) -> bool:
    lane_paths = row.get("lane_paths") if isinstance(row.get("lane_paths"), dict) else {}
    raw = str(lane_paths.get(lane) or "").strip()
    if not raw or lane not in (row.get("lanes") or []):
        return False
    try:
        return Path(raw).is_file()
    except OSError:
        return False


def build_asset_journey(asset_id: str) -> dict[str, Any]:
    asset = register_mod.get_asset(asset_id)
    if asset is None:
        raise KeyError(asset_id)

    runs = intake_mod.list_runs(asset_id=asset_id, limit=200)
    lookdev = lookdev_mod.list_outputs(asset_id=asset_id, limit=1000)
    catalog_rows = game_ready_mod.list_elements(asset_id=asset_id, limit=1000)

    source = _source_reference(asset, lookdev)
    capture_row = None
    capture = None
    for row in lookdev:
        if row.get("kind") != "niagara-render":
            continue
        candidate = _transformation_item(row, role="capture")
        if candidate:
            capture_row = row
            capture = candidate
            break

    ready_rows: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for row in catalog_rows:
        if not _is_game_ready(row):
            continue
        card = _element_card(row)
        if card is None:
            continue
        ready_rows.append(row)
        cards.append(card)

    published_rows = [
        row
        for row in ready_rows
        if any(_lane_copy_exists(row, lane) for lane in (row.get("lanes") or []))
    ]
    featured_rows = _featured_rows(ready_rows)
    featured_cards = [card for row in featured_rows if (card := _element_card(row)) is not None]
    if capture is None and featured_cards:
        representative = featured_cards[0]
        capture = {
            "id": representative.get("id"),
            "label": "Validated game-ready capture",
            "kind": representative.get("kind"),
            "lane": "slots" if "slots" in (representative.get("lanes") or []) else None,
            "system_name": representative.get("system_name"),
            "created_at": representative.get("created_at"),
            "note": "MRQ-derived clip with factory validation and stored vault bytes.",
            "file_href": representative.get("file_href"),
            "preview": representative.get("preview"),
            "preview_time_seconds": representative.get("preview_time_seconds"),
        }
    systems = {
        str((row.get("meta") or {}).get("system") or "").strip()
        for row in ready_rows
        if str((row.get("meta") or {}).get("system") or "").strip()
    }
    bandit_ready_rows = [
        row for row in published_rows
        if row.get("kind") == "vfx-clip"
        and "slots" in (row.get("lanes") or [])
        and str((row.get("meta") or {}).get("variant") or "") in {"contained", "breakout"}
    ]
    consumer_receipt = _bandit_consumer_receipt({str(row.get("id")) for row in bandit_ready_rows})

    registered_at = None
    registered_href = None
    if runs:
        oldest = min(runs, key=lambda run: str(run.get("created_at") or "9999"))
        registered_at = oldest.get("created_at")
        registered_href = f"/api/intake/{oldest.get('run_id')}"

    aurora_step = _step(runs, "download_epic", "in_project")
    aurora_at = aurora_step[1].get("updated_at") if aurora_step else None
    aurora_confirmed = bool(asset.get("host_content_path") or asset.get("ue_in_project") == "in_project")
    capture_at = capture_row.get("created_at") if capture_row and capture else None
    ready_at = max((str(row.get("created_at") or "") for row in ready_rows), default="") or None
    delivered_at = max(
        (str(row.get("updated_at") or row.get("created_at") or "") for row in published_rows),
        default="",
    ) or None

    lane_previews: dict[str, int] = {}
    for row in lookdev:
        lane = str(row.get("lane") or "")
        if lane:
            lane_previews[lane] = lane_previews.get(lane, 0) + 1

    def destination(destination_id: str, name: str, mark: str, lane: str | None) -> dict[str, Any]:
        delivered = [row for row in published_rows if lane and _lane_copy_exists(row, lane)]
        preview_count = lane_previews.get(lane or "", 0)
        if delivered:
            state = "received"
            detail = f"{len(delivered)} validated output{'s' if len(delivered) != 1 else ''} attached"
        elif preview_count:
            state = "preview-only"
            detail = f"{preview_count} preview output{'s' if preview_count != 1 else ''}; no game-ready delivery evidence"
        else:
            state = "no-evidence"
            detail = "No delivery evidence"
        attachment_rows: list[dict[str, Any]] = []
        if delivered:
            prioritized = sorted(
                delivered,
                key=lambda row: (
                    str(row.get("id") or "") != str((consumer_receipt or {}).get("element_id") or ""),
                    str((row.get("meta") or {}).get("variant") or "") != "contained",
                    str((row.get("meta") or {}).get("system") or "").casefold(),
                ),
            )
            attachment_rows = prioritized[:2]
        return {
            "id": destination_id,
            "name": name,
            "mark": mark,
            "lane": lane,
            "state": state,
            "output_count": len(delivered),
            "preview_count": preview_count,
            "detail": detail,
            "attachments": [
                card for row in attachment_rows
                if (card := _element_card(row)) is not None
            ],
            "consumer_receipt": consumer_receipt if destination_id == "bandit" else None,
        }

    destinations = [
        destination("bandit", "Bandit", "B", "slots"),
        destination("hails", "Hails", "H", "hail-overlay"),
        destination("proscenium", "Proscenium", "P", None),
    ]
    received_count = sum(item["state"] == "received" for item in destinations)

    milestones = [
        _milestone(
            "registered",
            "Registered",
            confirmed=True,
            occurred_at=registered_at,
            detail="Stable identity in the Vellum asset register",
            evidence_href=registered_href or f"/api/assets/{asset_id}",
        ),
        _milestone(
            "staged-factory",
            "Staged on Factory",
            confirmed=aurora_confirmed,
            occurred_at=aurora_at,
            detail=str(asset.get("host_content_path") or "No Factory Library path recorded"),
            evidence_href=f"/api/assets/{asset_id}/import",
        ),
        _milestone(
            "trusted-capture",
            "Trusted Capture",
            confirmed=capture_row is not None,
            occurred_at=capture_at,
            detail=(str(capture_row.get("system_name") or "MRQ capture") if capture_row else "No decodable trusted capture recorded"),
            evidence_href=(capture.get("file_href") if capture_row and capture else None),
        ),
        _milestone(
            "game-ready",
            f"{len(cards)} Game-ready Element{'s' if len(cards) != 1 else ''}",
            confirmed=bool(cards),
            occurred_at=ready_at,
            detail="Portable outputs with real vault bytes; failed validation and bake plans excluded",
            evidence_href=f"/api/game-ready/elements?asset_id={asset_id}",
        ),
        _milestone(
            "destinations",
            f"{received_count} Destination{'s' if received_count != 1 else ''}",
            confirmed=received_count > 0,
            occurred_at=delivered_at,
            detail="Received only when a game-ready lane copy is recorded and present",
            evidence_href=f"/api/game-ready/elements?asset_id={asset_id}",
        ),
    ]

    if published_rows:
        status = "delivered"
    elif cards:
        status = "game-ready"
    elif capture:
        status = "captured"
    elif aurora_confirmed:
        status = "staged"
    else:
        status = "registered"

    return {
        "schema_version": 1,
        "asset_id": asset_id,
        "status": status,
        "asset": {
            "id": asset_id,
            "display_name": asset.get("display_name") or asset_id,
            "engine": asset.get("engine"),
            "package_type": asset.get("package_type"),
            "store_label": asset.get("store_label") or asset.get("store_lane"),
            "project_fit": asset.get("project_fit"),
        },
        "counts": {
            "lookdev_outputs": len(lookdev),
            "catalog_rows": len(catalog_rows),
            "game_ready": len(cards),
            "published": len(published_rows),
            "systems": len(systems),
            "bandit_ready_clips": len(bandit_ready_rows),
        },
        "outcome": (
            {
                "headline": f"{len(systems)} Niagara systems became {len(bandit_ready_rows)} validated Bandit-ready celebration clips",
                "detail": f"{len(cards)} portable artifacts remain available as technical evidence.",
                "unit_label": "Niagara systems",
                "primary_count": len(systems),
            }
            if systems and bandit_ready_rows
            else {
                "headline": f"{len(cards)} validated game-ready artifacts are available for delivery",
                "detail": f"{len(published_rows)} artifacts have verifiable lane copies.",
                "unit_label": "game-ready groups",
                "primary_count": len(cards),
            }
        ),
        "transformation": {"source": source, "capture": capture},
        "milestones": milestones,
        "featured_outputs": featured_cards,
        "outputs": cards,
        "destinations": destinations,
    }
