# ---------------------------------------------------------------------------
# VENDORED - DO NOT EDIT HERE.
#
# Source of truth: C:\dev\ctrl-alt-axiom\backend\auth\dependencies.py
# (repo `ctrl-alt-axiom`, path `backend/auth/dependencies.py`)
#
# This file is a verbatim copy carried into Vellum so that every service in the
# fleet decides "is this token good?" with identical code. A divergent copy is
# worse than no copy: two validators that disagree about audience or algorithm
# produce a boundary that holds in one service and not the other, and nobody
# finds out until the weaker one is the one that matters.
#
# If this needs to change, change it upstream in ctrl-alt-axiom and re-vendor
# into every consumer. Fixing it only here is how the fleet acquires a security
# control that is true in one repo and false in three.
#
# ONE intentional deviation from upstream, and the only one permitted:
# intra-package imports are RELATIVE (`from .jwt_validator import ...`) instead
# of upstream's absolute `from auth.jwt_validator import ...`. Axiom puts its
# `backend/` directory on `sys.path`, so `auth` is a top-level package there.
# Vellum imports its code as `backend.*` (pyproject `pythonpath = ["."]`,
# Dockerfile `PYTHONPATH=/app`), so the same absolute import would raise
# ModuleNotFoundError at startup. Relative imports resolve correctly under
# either layout, so this deviation cannot drift back into a bug.
#
# Re-vendor with: python tools/vendor_auth.py (see that script's docstring).
# ---------------------------------------------------------------------------

"""FastAPI wiring for scope-gated routes.

Usage on a route that mutates something:

    @router.post("/api/mneme/documents",
                 dependencies=[Depends(require_scope("mneme:documents.write"))])

and, when the handler needs to record *who*:

    async def handler(principal: Principal = Depends(require_scope("mneme:documents.write"))):
        ...  record principal.label as dispatched_by

The distinction this module exists to preserve: **401 means the token is bad, 403 means
the token is fine and the client was not granted this.** Collapsing them is the reason
an operator cannot tell "auth is broken" from "this client is not allowed", and both
end up being fixed by widening permissions.

Both responses carry `WWW-Authenticate` with `resource_metadata`, which is what lets a
client discover the authorization server and retry with a correct token instead of
failing at a dead end.
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .jwt_validator import (
    Principal,
    ScopeError,
    TokenError,
    TokenValidator,
    www_authenticate,
)

logger = logging.getLogger(__name__)

# auto_error=False so a missing header reaches our handler and produces a
# `WWW-Authenticate` with the metadata pointer, rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False)

_validator: TokenValidator | None = None
_metadata_url: str = ""
_enforcing: bool = True


def configure(validator: TokenValidator, metadata_url: str, *, enforcing: bool = True) -> None:
    """Install the process-wide validator.

    `enforcing=False` exists for the studio, where there is no Keycloak and reads are
    LAN-open anyway. It is a deliberate, logged, single-flag decision rather than a
    silent fallback: a service that quietly stops checking tokens when its issuer is
    unreachable has no authentication at all, it just has authentication-shaped logs.
    """
    global _validator, _metadata_url, _enforcing
    _validator = validator
    _metadata_url = metadata_url
    _enforcing = enforcing
    if not enforcing:
        logger.warning(
            "AUTH NOT ENFORCED: scope checks are disabled on this instance. "
            "This is correct for a studio checkout and wrong for the press."
        )


def is_enforcing() -> bool:
    return _enforcing and _validator is not None


def _unauthorized(exc: TokenError) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"error": exc.error, "error_description": str(exc)},
        headers={
            "WWW-Authenticate": www_authenticate(
                _validator.audience if _validator else "axiom",
                _metadata_url,
                error=exc.error,
                description=str(exc),
            )
        },
    )


def _forbidden(exc: ScopeError) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "error": "insufficient_scope",
            "error_description": str(exc),
            "required_scope": exc.required,
            "granted_scopes": exc.held,
        },
        headers={
            "WWW-Authenticate": www_authenticate(
                _validator.audience if _validator else "axiom",
                _metadata_url,
                error="insufficient_scope",
                description=f"requires {exc.required}",
                scope=exc.required,
            )
        },
    )


# The principal used when enforcement is off. Named so it is obvious in any log line
# or `dispatched_by` field that this call was not authenticated — an unenforced call
# must never be indistinguishable from an authenticated one after the fact.
UNENFORCED = Principal(
    subject="unenforced",
    client_id="unenforced",
    scopes=frozenset(),
    issuer="",
    audience="",
    expires_at=0,
)


def require_scope(scope: str) -> Callable[..., Principal]:
    """A dependency that admits only tokens carrying `scope`.

    Returns the `Principal`, so a handler can both gate on the scope and record who
    made the call from one dependency rather than validating twice.
    """

    def dependency(
        request: Request,
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> Principal:
        if not is_enforcing():
            return UNENFORCED

        if creds is None or not creds.credentials:
            raise _unauthorized(
                TokenError("no bearer token presented", error="invalid_request")
            )
        try:
            principal = _validator.validate(creds.credentials)  # type: ignore[union-attr]
        except TokenError as exc:
            logger.info("token rejected for %s %s: %s", request.method, request.url.path, exc)
            raise _unauthorized(exc) from exc

        try:
            principal.require(scope)
        except ScopeError as exc:
            logger.info(
                "scope refused for %s on %s %s: %s",
                principal.label,
                request.method,
                request.url.path,
                exc,
            )
            raise _forbidden(exc) from exc

        return principal

    return dependency


def optional_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal | None:
    """Who is calling, if they presented a valid token — for reads that stay LAN-open.

    Never raises. A read route that is open should not start failing because a client
    sent a stale token, but when a good token *is* present the caller is worth
    recording. This is how attribution improves without a flag day.
    """
    if not is_enforcing() or creds is None or not creds.credentials:
        return None
    try:
        return _validator.validate(creds.credentials)  # type: ignore[union-attr]
    except TokenError:
        return None


__all__ = [
    "UNENFORCED",
    "configure",
    "is_enforcing",
    "optional_principal",
    "require_scope",
]
