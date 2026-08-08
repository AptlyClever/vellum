# ---------------------------------------------------------------------------
# VENDORED - DO NOT EDIT HERE.
#
# Source of truth: C:\dev\ctrl-alt-axiom\backend\auth\jwt_validator.py
# (repo `ctrl-alt-axiom`, path `backend/auth/jwt_validator.py`)
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

"""OAuth 2.1 resource-server token validation (RFC 9068 JWT access tokens).

Why this exists, stated plainly so the next agent does not "simplify" it back:

Until now every service-to-service call in this fleet presented one of two static,
non-expiring, unscoped bearer strings — `AXIOM_OPERATOR_TOKEN` and `MNEME_WRITE_TOKEN`
— read from a host env file. That has three properties nobody chose:

  1. It cannot say *who* used it. This is the mechanical reason 81 of the last 100
     Repo Ops jobs record no dispatcher: the credential carries no subject, so
     attribution had nowhere to come from.
  2. It cannot say *what the holder may do*. Axiom's own `mcp_context_server`
     docstring flags this — "that credential can mutate anything in Axiom, and this
     process chooses to expose only appends." A choice made in code, not enforced by
     the credential, is not a boundary.
  3. It never expires, so a leak is permanent and rotation means editing files on the
     press and restarting every consumer at once.

The MCP specification (2026-07-28) closes the first two by requiring that an HTTP MCP
server act as an OAuth 2.1 resource server and *validate that access tokens were issued
specifically for it as the intended audience*. This module is that validation, and it is
deliberately the only place in the fleet that decides whether a token is good.

Design notes that are load-bearing:

* **Algorithms are an allowlist, never read from the token.** `alg: none` and
  HS256-signed-with-the-public-key are the two classic JWT forgeries, and both work
  against any verifier that trusts the header. We pass `algorithms=` explicitly and
  never consult `jwt.get_unverified_header()["alg"]` for anything but diagnostics.
* **Audience is required and checked.** A token minted for Mneme must not open Axiom.
  This is RFC 8707 Resource Indicators as the MCP spec applies it, and it is the single
  requirement that makes a compromised downstream service non-transitive.
* **JWKS is cached with a bounded TTL and refetched on unknown `kid`.** Key rotation
  must not require a restart, and an unknown `kid` is the normal signal that the issuer
  rotated. One refetch per unknown kid, rate-limited, so a bogus kid cannot be used to
  hammer the issuer.
* **Clock skew is bounded, not generous.** 60s. Large leeway silently extends the life
  of every revoked token.

`ScopeError` and `TokenError` are distinct because they need different operator
responses: a bad token means authentication is broken (wrong issuer, expired, clock
drift), a missing scope means the client is authenticated and asking for something it
was not granted. Collapsing them into 401 makes the second one undiagnosable.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx
import jwt
from jwt import PyJWKClient

# Asymmetric only. A resource server that accepts an HMAC algorithm can be made to
# verify a forged token using the issuer's *public* key as the shared secret.
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384")

# RFC 9068 says an access token SHOULD carry `typ: at+jwt`. Enforced when present rather
# than required outright, because Keycloak emits `JWT` by default and forcing operators
# to change a realm setting to make auth work is how auth gets turned off.
ACCEPTED_TOKEN_TYPES = ("at+jwt", "application/at+jwt", "jwt")

CLOCK_SKEW_S = 60
JWKS_CACHE_TTL_S = 600
JWKS_MIN_REFETCH_INTERVAL_S = 10


class TokenError(Exception):
    """The token is absent, malformed, expired, or not for us.

    Maps to 401 with `WWW-Authenticate`. Means authentication failed — the caller
    should obtain a new token, not ask for different permissions.
    """

    def __init__(self, message: str, *, error: str = "invalid_token") -> None:
        super().__init__(message)
        self.error = error


class ScopeError(Exception):
    """The token is valid but does not carry the scope this route requires.

    Maps to 403 with `error="insufficient_scope"` and the required scope named, per
    RFC 6750 §3.1. Distinct from TokenError on purpose: retrying with a fresh token
    will not fix it, and an operator reading the log needs to know that.
    """

    def __init__(self, required: str, held: Iterable[str]) -> None:
        self.required = required
        self.held = sorted(held)
        super().__init__(
            f"token lacks required scope {required!r}; it carries {self.held or ['<none>']}"
        )


@dataclass(frozen=True)
class Principal:
    """Who made this call, according to a token we verified.

    `subject` is what finally makes a job attributable. `client_id` is the workload
    (the `mcp` container, the `web` container, Praxis); `subject` equals it for a
    client-credentials grant and differs when a real user is behind the call.
    """

    subject: str
    client_id: str
    scopes: frozenset[str]
    issuer: str
    audience: str
    expires_at: int
    claims: dict[str, Any] = field(default_factory=dict, repr=False)

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise ScopeError(scope, self.scopes)

    @property
    def label(self) -> str:
        """A short human string for `dispatched_by` and activity lines."""
        return self.client_id if self.subject == self.client_id else f"{self.subject}@{self.client_id}"


class _JwksCache:
    """JWKS fetching with TTL, unknown-kid refetch, and a refetch rate limit.

    PyJWKClient has its own cache but refetches unconditionally on a cache miss, which
    turns an attacker-supplied random `kid` into an unbounded request amplifier against
    the issuer. The `_last_fetch` floor is that fix.
    """

    def __init__(self, jwks_uri: str, timeout_s: float = 5.0) -> None:
        self._jwks_uri = jwks_uri
        self._timeout_s = timeout_s
        self._client: PyJWKClient | None = None
        self._fetched_at = 0.0
        self._last_fetch_attempt = 0.0
        self._lock = threading.Lock()

    def _build(self) -> PyJWKClient:
        return PyJWKClient(self._jwks_uri, cache_keys=True, timeout=self._timeout_s)

    def signing_key(self, token: str) -> Any:
        now = time.monotonic()
        with self._lock:
            if self._client is None or (now - self._fetched_at) > JWKS_CACHE_TTL_S:
                self._client = self._build()
                self._fetched_at = now
            client = self._client

        try:
            return client.get_signing_key_from_jwt(token).key
        except Exception as first_error:
            # Unknown kid is the ordinary signal that the issuer rotated keys. Refetch
            # once, but not more often than the floor, so a garbage kid cannot be used
            # to hammer Keycloak.
            with self._lock:
                if (time.monotonic() - self._last_fetch_attempt) < JWKS_MIN_REFETCH_INTERVAL_S:
                    raise TokenError(f"signing key not found: {first_error}") from first_error
                self._last_fetch_attempt = time.monotonic()
                self._client = self._build()
                self._fetched_at = time.monotonic()
                client = self._client
            try:
                return client.get_signing_key_from_jwt(token).key
            except Exception as exc:  # noqa: BLE001 - reported, not raised onward
                raise TokenError(f"signing key not found after refresh: {exc}") from exc


class TokenValidator:
    """Validates RFC 9068 access tokens for one audience.

    One instance per resource server. `audience` is this service's resource identifier
    and is not optional — see the module docstring on why non-transitivity depends on it.
    """

    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_uri: str | None = None,
        *,
        timeout_s: float = 5.0,
        required_scopes: Iterable[str] = (),
    ) -> None:
        if not issuer:
            raise ValueError("issuer is required")
        if not audience:
            raise ValueError("audience is required: a resource server that accepts any audience is not one")
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.jwks_uri = jwks_uri or f"{self.issuer}/protocol/openid-connect/certs"
        self.required_scopes = frozenset(required_scopes)
        self._jwks = _JwksCache(self.jwks_uri, timeout_s=timeout_s)

    def validate(self, token: str) -> Principal:
        """Verify a bearer token and return who it says is calling.

        Raises TokenError for anything that makes the token untrustworthy. Never
        returns a partially-verified principal — there is no "probably fine" path,
        because that is how `verified: null` becomes `verified: true` by accident.
        """
        token = (token or "").strip()
        if not token:
            raise TokenError("no bearer token presented", error="invalid_request")

        key = self._jwks.signing_key(token)

        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self.audience,
                issuer=self.issuer,
                leeway=CLOCK_SKEW_S,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenError("token expired") from exc
        except jwt.InvalidAudienceError as exc:
            # ASCII only, deliberately. `_header_safe` now makes this survivable either
            # way, but this particular message is the one that reaches an operator when
            # the audience boundary does its job, and it should read cleanly rather than
            # arrive carrying an escape sequence.
            raise TokenError(
                f"token audience is not {self.audience!r}: it was minted for a different "
                "service and must not be replayed here"
            ) from exc
        except jwt.InvalidIssuerError as exc:
            raise TokenError(f"token issuer is not {self.issuer!r}") from exc
        except jwt.MissingRequiredClaimError as exc:
            raise TokenError(f"token is missing required claim: {exc}") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenError(f"token rejected: {exc}") from exc

        typ = (jwt.get_unverified_header(token).get("typ") or "").lower()
        if typ and typ not in ACCEPTED_TOKEN_TYPES:
            raise TokenError(f"unexpected token type {typ!r}; expected an access token")

        principal = Principal(
            subject=str(claims.get("sub", "")),
            client_id=str(claims.get("azp") or claims.get("client_id") or claims.get("sub", "")),
            scopes=frozenset(_scopes_from(claims)),
            issuer=str(claims.get("iss", "")),
            audience=self.audience,
            expires_at=int(claims.get("exp", 0)),
            claims=claims,
        )
        for scope in self.required_scopes:
            principal.require(scope)
        return principal

    def protected_resource_metadata(self, resource: str) -> dict[str, Any]:
        """RFC 9728 Protected Resource Metadata.

        Served at `/.well-known/oauth-protected-resource`. This is what lets an MCP
        client discover which authorization server to talk to instead of being told
        out of band — the MCP spec requires it, and it is what makes a 401 actionable
        rather than a dead end.
        """
        return {
            "resource": resource,
            "authorization_servers": [self.issuer],
            "scopes_supported": sorted(KNOWN_SCOPES),
            "bearer_methods_supported": ["header"],
            "resource_documentation": f"{resource}/docs",
        }


def _scopes_from(claims: dict[str, Any]) -> set[str]:
    """Scopes live in `scope` (space-delimited) per RFC 8693; some issuers use `scp`."""
    raw = claims.get("scope") or claims.get("scp") or ""
    if isinstance(raw, str):
        return {s for s in raw.split() if s}
    if isinstance(raw, (list, tuple)):
        return {str(s) for s in raw if s}
    return set()


def bearer_from_header(authorization: str | None) -> str:
    """Extract a bearer token, rejecting other schemes explicitly.

    Case-insensitive on the scheme per RFC 7235; a `Basic` header is refused by name so
    the failure says what was wrong rather than "invalid token".
    """
    if not authorization:
        raise TokenError("no Authorization header", error="invalid_request")
    parts = authorization.split(None, 1)
    if len(parts) != 2:
        raise TokenError("malformed Authorization header", error="invalid_request")
    scheme, value = parts
    if scheme.lower() != "bearer":
        raise TokenError(f"unsupported authorization scheme {scheme!r}; expected Bearer",
                         error="invalid_request")
    return value.strip()


def _header_safe(value: str) -> str:
    """Make an arbitrary string safe to place inside a quoted HTTP header parameter.

    This function exists because of a real, reproduced 500. HTTP response headers are
    encoded latin-1 (RFC 7230 via Starlette), and this module's own audience-mismatch
    message contained a U+2014 EM DASH. `_unauthorized()` copies the message into
    `WWW-Authenticate`, so encoding blew up *inside the exception handler* and the
    caller received `500 Internal Server Error` with no `WWW-Authenticate` at all.

    The consequence was worse than an ugly header. The refusal that broke is the one
    the entire non-transitivity argument exists to produce — a token minted for Mneme
    presented to Axiom. Instead of "this token is for another service, here is where
    to get the right one", the operator sees "Axiom is broken", and the natural next
    move is to widen scopes on a client that already has them. A security control that
    fails as a server error teaches people to disable it.

    Sanitising here rather than at the one bad string is deliberate: the messages that
    reach this function include `f"token rejected: {exc}"`, which interpolates PyJWT's
    text verbatim. Fixing only the em dash would leave the next upstream library
    message one non-ASCII character away from the same 500.

    Three things happen, in order:
      * backslashes and double quotes are escaped, so a message containing `"` cannot
        terminate the quoted-string early and forge extra auth-challenge parameters;
      * CR/LF/NUL are stripped, because a newline in a header value is response
        splitting;
      * anything outside US-ASCII is escaped rather than raising, so a refusal degrades
        to slightly-less-readable instead of to a 500.

    **ASCII, not latin-1**, and that distinction was itself a bug found by a test.
    Starlette will happily *encode* latin-1, so `é` (0xE9) survived the first version of
    this function — and then the client blew up *decoding* the header as UTF-8, where
    0xE9 is an invalid continuation byte. A 500 on the server became a decode error on
    the client: the same dead end, one hop further away and harder to attribute.
    RFC 7230 deprecates non-ASCII in field values for exactly this reason. Restricting
    to ASCII is the only choice that is safe against every client's decoder.
    """
    text = str(value)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("\r", " ").replace("\n", " ").replace("\0", "")
    # `backslashreplace` keeps the information visible (`—`) instead of dropping it
    # silently, which matters when the message is the only thing an operator gets.
    return text.encode("ascii", "backslashreplace").decode("ascii")


def www_authenticate(
    audience: str,
    metadata_url: str,
    *,
    error: str | None = None,
    description: str | None = None,
    scope: str | None = None,
) -> str:
    """The `WWW-Authenticate` value for a 401/403.

    `resource_metadata` is the MCP-spec-mandated pointer that turns a refusal into a
    discovery step: a client that gets this can find the authorization server, obtain a
    correctly-scoped token, and retry without a human editing configuration. The whole
    `control_alt_ask` "401 that models paraphrased as success" failure was a refusal
    that named nothing.

    Every interpolated value goes through `_header_safe`, including the ones that look
    like they cannot need it. `audience` and `metadata_url` come from settings today,
    but a header builder that trusts *some* of its inputs is one refactor away from
    trusting the wrong one.
    """
    parts = [
        f'Bearer realm="{_header_safe(audience)}"',
        f'resource_metadata="{_header_safe(metadata_url)}"',
    ]
    if error:
        parts.append(f'error="{_header_safe(error)}"')
    if description:
        parts.append(f'error_description="{_header_safe(description)}"')
    if scope:
        parts.append(f'scope="{_header_safe(scope)}"')
    return ", ".join(parts)


# The fleet's scope vocabulary. Kept in one place so a new scope is a deliberate edit
# here rather than a string invented at a call site — an unknown scope in a policy is
# indistinguishable from a typo, and both fail open if nobody is enumerating them.
KNOWN_SCOPES = frozenset(
    {
        "mneme:documents.read",
        "mneme:documents.write",
        "praxis:work.read",
        "praxis:work.write",
        "axiom:briefing.read",
        "axiom:decisions.read",
        "axiom:decisions.write",
        "axiom:sessions.write",
        "axiom:repo-ops.dispatch",
        "daedalus:jobs.read",
        "daedalus:jobs.write",
    }
)
# `daedalus:jobs.read` and `.write` are split because Hephaestus renders job state in a
# dashboard and also drives jobs. A surface that only displays must not be able to start
# work: the read scope is what a status page needs, and nothing more.
# `axiom:sessions.write` is deliberately separate from `axiom:decisions.write`. Registering
# a session is the cheapest, most frequent write an agent makes and every agent must be able
# to do it; filing a question into the Director's inbox is rare and consequential. Folding
# them into one grant would mean every agent that can say "I am working" can also queue
# something he has to rule on — which is how a permission set stops meaning anything.


__all__ = [
    "ALLOWED_ALGORITHMS",
    "KNOWN_SCOPES",
    "Principal",
    "ScopeError",
    "TokenError",
    "TokenValidator",
    "bearer_from_header",
    "www_authenticate",
]
