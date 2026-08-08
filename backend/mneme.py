"""Mneme client for paired Visual Research source-text ingestion.

Outbound authentication lives here, and only here. Vellum's single fleet call is
"write a research document into Mneme", so this module is the whole surface that had
to change when the fleet moved off static bearer tokens.

What changed and why
--------------------
`MNEME_WRITE_TOKEN` was a permanent, unscoped, non-expiring string. It could not say
who used it, could not be limited to documents, and could not be rotated without
restarting every consumer at once. It is replaced by an OAuth 2.0 client-credentials
token (RFC 6749 sec 4.4) minted per call for `resource=https://mneme.control-alt.lan`
with `mneme:documents.write` (or `.read`). That token carries an `aud` naming Mneme,
so if Vellum is compromised the stolen credential cannot be replayed against Axiom,
Praxis or Daedalus - the property the static token could never have.

Two-tier ladder, and the ordering rule that cost a live failure
--------------------------------------------------------------
1. OAuth, when an issuer + client id + secret are configured.
2. The static `MNEME_WRITE_TOKEN`, which still works, and **logs a deprecation warning
   every time it fires**.

Tier 2 fires ONLY when OAuth is unconfigured. It is deliberately not deleted: Mneme
still accepts it as its own tier 1, and a fleet that removes the fallback before every
caller is converted is a fleet that is down. It is deliberately noisy: a deprecated
credential that stops announcing itself is still in production two years later.

There is no enforcement flag gating *acceptance* on the outbound side, because there is
nothing to accept - `VELLUM_OAUTH_ENFORCE` (default false) instead controls whether the
static fallback is allowed to fire at all. Enforcement ships OFF: configuring OAuth must
never be the thing that breaks the call. Axiom and Mneme both shipped a version where
turning OAuth on for the caller produced a 401 and then a 403, precisely because
"can use a token" was gated on "must use a token".

Vellum exposes its own API but nothing in the fleet calls it with a token today, so
this module adds no inbound validation. See `backend/auth/` for the vendored validator
that will be used when that changes.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any

import httpx

from .auth import ClientCredentialsProvider, TokenAcquisitionError

logger = logging.getLogger(__name__)

PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Mneme's resource identifier. This is the `aud` Vellum asks Keycloak to stamp on the
# token, and the exact string Mneme's validator requires. It is a constant rather than
# an env var because a caller that can be pointed at a different audience by
# configuration is a caller whose audience nobody checked.
MNEME_RESOURCE = "https://mneme.control-alt.lan"

SCOPE_DOCUMENTS_WRITE = "mneme:documents.write"
SCOPE_DOCUMENTS_READ = "mneme:documents.read"


class MnemeError(RuntimeError):
    """A confirmed Mneme rejection or invalid response."""


class MnemeAmbiguousError(MnemeError):
    """The request may have reached Mneme, but no response was received."""


def base_url() -> str:
    return (os.environ.get("MNEME_BASE_URL") or "http://127.0.0.1:8790").rstrip("/")


def vellum_public_base_url() -> str:
    return (
        os.environ.get("VELLUM_PUBLIC_BASE_URL") or "http://127.0.0.1:8770"
    ).rstrip("/")


# --------------------------------------------------------------------------
# OAuth settings. Plain `os.environ` readers, matching this repo's idiom
# (`base_url`, `research.write_token`, ...) rather than importing a settings
# framework for five values.
# --------------------------------------------------------------------------


def oauth_issuer() -> str:
    """Keycloak realm issuer, e.g. http://127.0.0.1:8794/realms/control-alt."""
    return (os.environ.get("VELLUM_OAUTH_ISSUER") or "").strip().rstrip("/")


def oauth_token_endpoint() -> str:
    """The token endpoint, derived from the issuer unless overridden.

    Derived by default so a deployment sets one URL and cannot end up with an issuer
    and a token endpoint that point at different realms - a mismatch that produces a
    token which is valid, correctly signed, and refused by every service in the fleet.
    """
    explicit = (os.environ.get("VELLUM_OAUTH_TOKEN_ENDPOINT") or "").strip()
    if explicit:
        return explicit
    issuer = oauth_issuer()
    return f"{issuer}/protocol/openid-connect/token" if issuer else ""


def oauth_client_id() -> str:
    return (os.environ.get("VELLUM_OAUTH_CLIENT_ID") or "vellum").strip()


def oauth_client_secret() -> str:
    return (os.environ.get("VELLUM_OAUTH_CLIENT_SECRET") or "").strip()


def oauth_audience() -> str:
    """The resource identifier Vellum requests tokens for (Mneme)."""
    return (os.environ.get("VELLUM_OAUTH_MNEME_AUDIENCE") or MNEME_RESOURCE).strip()


def oauth_enforced() -> bool:
    """Whether the deprecated static token is forbidden. Defaults to FALSE.

    Separate from "is OAuth configured" on purpose. Configuring an issuer switches the
    caller to tokens; this flag is what finally removes the fallback, and it is a
    distinct, later, deliberate decision. Fusing the two is the exact mistake that took
    Axiom and Mneme down: the moment OAuth was configured the static path vanished, and
    anything not yet converted got a 401.
    """
    return (os.environ.get("VELLUM_OAUTH_ENFORCE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def oauth_configured() -> bool:
    return bool(oauth_token_endpoint() and oauth_client_id() and oauth_client_secret())


_provider: ClientCredentialsProvider | None = None
_provider_key: tuple[str, str, str] | None = None
_provider_lock = threading.Lock()


def provider() -> ClientCredentialsProvider | None:
    """The process-wide token provider, or None when OAuth is unconfigured.

    Cached because the provider caches tokens; rebuilding it per call would mint a new
    token per request and turn Keycloak into a hot path. Keyed on the credentials so a
    test (or a rotation) that changes the environment gets a fresh provider instead of
    silently reusing a token obtained with the old secret.
    """
    global _provider, _provider_key
    if not oauth_configured():
        return None
    key = (oauth_token_endpoint(), oauth_client_id(), oauth_client_secret())
    with _provider_lock:
        if _provider is None or _provider_key != key:
            _provider = ClientCredentialsProvider(*key)
            _provider_key = key
        return _provider


def reset_provider() -> None:
    """Drop the cached provider. For tests and for credential rotation."""
    global _provider, _provider_key
    with _provider_lock:
        _provider = None
        _provider_key = None


def write_token() -> str:
    """The deprecated static bearer. Kept as tier 2 - see the module docstring."""
    return (os.environ.get("MNEME_WRITE_TOKEN") or "").strip()


def auth_headers(scope: str) -> dict[str, str]:
    """`Authorization` for one Mneme call, by the two-tier ladder.

    Raises MnemeError("mneme_write_disabled") when neither tier is available, which is
    the same error string the static-only version raised - callers and their tests do
    not have to learn a new failure mode to gain a better credential.
    """
    prov = provider()
    if prov is not None:
        try:
            return prov.auth_headers(oauth_audience(), [scope])
        except TokenAcquisitionError as exc:
            # Do NOT silently fall back to the static token here. Falling back on a
            # token-endpoint failure means a misconfigured OAuth deployment looks like a
            # working one, and the static credential quietly stays load-bearing forever.
            # Fail loudly with the issuer's own explanation attached.
            raise MnemeError(f"mneme_token_unavailable:{exc}") from exc

    if oauth_enforced():
        raise MnemeError(
            "mneme_oauth_required: VELLUM_OAUTH_ENFORCE is set but no OAuth client "
            "credentials are configured. Set VELLUM_OAUTH_ISSUER and "
            "VELLUM_OAUTH_CLIENT_SECRET (compose mounts ./secrets/vellum.env), or "
            "unset VELLUM_OAUTH_ENFORCE to re-allow the deprecated static token."
        )

    token = write_token()
    if not token:
        raise MnemeError("mneme_write_disabled")
    logger.warning(
        "DEPRECATED: authenticating to Mneme with the static MNEME_WRITE_TOKEN "
        "(scope %s would have been requested). This credential is unscoped, does not "
        "expire, and cannot say who used it. Configure VELLUM_OAUTH_ISSUER and "
        "VELLUM_OAUTH_CLIENT_SECRET to use audience-scoped client-credentials tokens.",
        scope,
    )
    return {"Authorization": f"Bearer {token}"}


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
    headers = auth_headers(SCOPE_DOCUMENTS_WRITE)
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
            headers={**headers, "Accept": "application/json"},
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
    """Resolve an ambiguous create by its deterministic Vellum tag.

    Reads carry `mneme:documents.read` rather than the write scope: this call runs on
    the recovery path after an ambiguous POST, and a reconciliation lookup has no
    business holding a credential that could create another document.

    Authentication is best-effort here, unlike the writes. Mneme's document listing is
    readable without a token today, and this call is the compensation path for a write
    that may already have succeeded - failing it because a credential is missing would
    turn a recoverable ambiguity into an orphaned document nobody can find.
    """
    try:
        read_headers = auth_headers(SCOPE_DOCUMENTS_READ)
    except MnemeError:
        read_headers = {}
    try:
        response = httpx.get(
            f"{base_url()}/api/documents",
            params={
                "tag": tag,
                "project_id": resolve_project_id(project_id),
                "limit": 10,
            },
            headers={**read_headers, "Accept": "application/json"},
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
    headers = auth_headers(SCOPE_DOCUMENTS_WRITE)
    try:
        response = httpx.delete(
            f"{base_url()}/api/documents/{document_id}",
            headers=headers,
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        raise MnemeAmbiguousError("mneme_delete_ambiguous") from exc
    if response.status_code not in (204, 404):
        raise MnemeError(f"mneme_delete_http_{response.status_code}")
