# ---------------------------------------------------------------------------
# VENDORED - DO NOT EDIT HERE.
#
# Source of truth: C:\dev\ctrl-alt-axiom\backend\auth\__init__.py
# (repo `ctrl-alt-axiom`, path `backend/auth/__init__.py`)
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

"""OAuth 2.1 authentication for the Control Alt fleet.

Two halves, deliberately separate:

* `jwt_validator` — the *receiving* side. Every service that accepts a call validates
  the token here and nowhere else.
* `client_credentials` — the *calling* side. Every service that makes a call obtains a
  short-lived, audience-scoped token here and nowhere else.

`dependencies` is the FastAPI glue that turns the first into a route decorator.

This replaces two static, non-expiring, unscoped bearer strings read from a host env
file (`AXIOM_OPERATOR_TOKEN`, `MNEME_WRITE_TOKEN`). Those could not say who used them,
could not limit what the holder could do, and could not be rotated without restarting
every consumer at once. See `jwt_validator`'s module docstring for the full argument.
"""

from .client_credentials import ClientCredentialsProvider, TokenAcquisitionError
from .jwt_validator import (
    ALLOWED_ALGORITHMS,
    KNOWN_SCOPES,
    Principal,
    ScopeError,
    TokenError,
    TokenValidator,
    bearer_from_header,
    www_authenticate,
)

__all__ = [
    "ALLOWED_ALGORITHMS",
    "KNOWN_SCOPES",
    "ClientCredentialsProvider",
    "Principal",
    "ScopeError",
    "TokenAcquisitionError",
    "TokenError",
    "TokenValidator",
    "bearer_from_header",
    "www_authenticate",
]
