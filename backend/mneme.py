"""Mneme client for paired Visual Research source-text ingestion."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class MnemeError(RuntimeError):
    """A confirmed Mneme rejection or invalid response."""


class MnemeAmbiguousError(MnemeError):
    """The request may have reached Mneme, but no response was received."""


def base_url() -> str:
    return (os.environ.get("MNEME_BASE_URL") or "http://192.168.68.93:8790").rstrip("/")


def vellum_public_base_url() -> str:
    return (
        os.environ.get("VELLUM_PUBLIC_BASE_URL") or "http://192.168.68.93:8770"
    ).rstrip("/")


def write_token() -> str:
    return (os.environ.get("MNEME_WRITE_TOKEN") or "").strip()


def default_project_id() -> str:
    return (os.environ.get("MNEME_DEFAULT_PROJECT_ID") or "bandit").strip()


def resolve_project_id(value: str | None) -> str:
    project_id = (value or "").strip() or default_project_id()
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError("project_id_invalid")
    return project_id


def document_url(document_id: str) -> str:
    return f"{base_url()}/api/documents/{document_id}"


def create_document(
    *,
    title: str,
    project_id: str,
    source_url: str,
    captured_at: str,
    tags: list[str],
    body: str,
    author: str | None = None,
    publisher: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    token = write_token()
    if not token:
        raise MnemeError("mneme_write_disabled")
    metadata = {
        "title": title,
        "project_id": resolve_project_id(project_id),
        "source_url": source_url,
        "captured_at": captured_at,
        "author": (author or "").strip() or None,
        "publisher": (publisher or "").strip() or None,
        "tags": tags,
    }
    try:
        response = httpx.post(
            f"{base_url()}/api/documents",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            files={
                "metadata": (None, json.dumps(metadata), "application/json"),
                "body": (None, body, "text/markdown; charset=utf-8"),
            },
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        raise MnemeAmbiguousError("mneme_request_ambiguous") from exc
    if response.status_code != 201:
        detail = response.text[:800]
        raise MnemeError(f"mneme_http_{response.status_code}:{detail}")
    try:
        result = response.json()
    except ValueError as exc:
        raise MnemeError("mneme_invalid_response") from exc
    if not isinstance(result, dict) or not str(result.get("id") or "").strip():
        raise MnemeError("mneme_invalid_response")
    return result


def find_document_by_tag(
    tag: str, *, project_id: str, timeout: float = 10.0
) -> dict[str, Any] | None:
    """Resolve an ambiguous create by its deterministic Vellum tag."""
    try:
        response = httpx.get(
            f"{base_url()}/api/documents",
            params={
                "tag": tag,
                "project_id": resolve_project_id(project_id),
                "limit": 10,
            },
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        raise MnemeAmbiguousError("mneme_reconcile_unavailable") from exc
    if response.status_code != 200:
        raise MnemeError(f"mneme_reconcile_http_{response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise MnemeError("mneme_invalid_response") from exc
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise MnemeError("mneme_invalid_response")
    for item in items:
        if isinstance(item, dict) and tag in (item.get("tags") or []):
            return item
    return None


def delete_document(document_id: str, *, timeout: float = 15.0) -> None:
    """Best-effort compensation for a bundle that cannot be linked locally."""
    token = write_token()
    if not token:
        raise MnemeError("mneme_write_disabled")
    try:
        response = httpx.delete(
            f"{base_url()}/api/documents/{document_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        raise MnemeAmbiguousError("mneme_delete_ambiguous") from exc
    if response.status_code not in (204, 404):
        raise MnemeError(f"mneme_delete_http_{response.status_code}")
