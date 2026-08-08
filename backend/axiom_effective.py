"""Axiom effective-settings client — resolved branding/theme for Vellum.

Vellum has its own vendored ca-theme-standard.css defaults, but Axiom (the
homelab hub) is the source of truth for branding/theme overrides. This module
fetches Axiom's resolved view for this app so the frontend can apply it at
runtime, failing soft whenever Axiom is unreachable or misconfigured.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from . import attach as attach_mod

_CACHE_TTL_SECONDS = 45.0
_cache: dict[str, Any] = {"at": 0.0, "value": None}


def fetch_axiom_effective(timeout: float = 4.0) -> dict[str, Any] | None:
    """Fetch Axiom's resolved effective settings for the vellum app.

    Fails soft: any request error, non-200 response, or unparsable body
    returns None instead of raising. Cached in-memory for a short TTL to
    avoid hammering Axiom on every page load.
    """
    now = time.time()
    if _cache["value"] is not None and (now - _cache["at"]) < _CACHE_TTL_SECONDS:
        return _cache["value"]

    try:
        response = httpx.get(
            f"{attach_mod.axiom_base_url()}/api/effective/vellum",
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
    except httpx.RequestError:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    _cache["at"] = now
    _cache["value"] = payload
    return payload
