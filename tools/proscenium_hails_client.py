"""Proscenium Hails Client for Control Alt Games.

Emits visual Hails and celebration stingers to Proscenium (:8788) for
Bandit, Threshold Affairs, and Field Ops with per-game target selection
and LCARD control overrides.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_PROSCENIUM_URL = os.environ.get(
    "AXIOM_PROSCENIUM_BASE_URL", "http://192.168.68.93:8788"
)

DEFAULT_TARGETS = {
    "bandit": "arcade",
    "threshold-affairs": "operator_desk",
    "field-ops": "operator_desk",
}


def trigger_game_hail(
    product_id: str,
    event_type: str,
    title: str,
    message: str,
    *,
    delivery_target_id: str | None = None,
    theme: str | None = None,
    glyph_hero: str | None = None,
    duration_sec: int = 5,
    audio_stinger: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    url = (base_url or DEFAULT_PROSCENIUM_URL).rstrip("/")
    target = delivery_target_id or DEFAULT_TARGETS.get(product_id, "operator_desk")

    payload = {
        "delivery_target_id": target,
        "payload": {
            "event_type": event_type,
            "title": title,
            "message": message,
            "theme": theme or ("tactical_amber" if "field" in product_id else "mystery_cyan"),
            "glyph_hero": glyph_hero or ("shield_check" if "field" in product_id else "magnifying_glass"),
            "duration_sec": duration_sec,
            "audio_stinger": audio_stinger,
            "product_id": product_id,
        },
    }

    req = urllib.request.Request(
        f"{url}/api/presentation/products/{product_id}/show",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "product_id": product_id, "target": target, "response": data}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "product_id": product_id,
            "target": target,
            "error": str(exc),
        }
