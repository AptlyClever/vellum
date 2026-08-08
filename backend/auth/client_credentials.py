# ---------------------------------------------------------------------------
# VENDORED - DO NOT EDIT HERE.
#
# Source of truth: C:\dev\ctrl-alt-axiom\backend\auth\client_credentials.py
# (repo `ctrl-alt-axiom`, path `backend/auth/client_credentials.py`)
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

"""OAuth 2.0 client-credentials grant (RFC 6749 §4.4) — the calling half.

Every workload in this fleet that talks to another one uses this: the `mcp` container
calling Axiom, Axiom calling Mneme, Praxis calling Axiom. It replaces reading a static
bearer string out of an env file.

The three properties that matter, none of which the static token had:

* **Audience-scoped.** `resource` (RFC 8707 Resource Indicators) asks the issuer to mint
  a token whose `aud` is the specific service being called. A token Axiom holds for
  Mneme cannot be replayed against Praxis. This is the property that makes a compromised
  service non-transitive, and it is the reason `resource` is a required argument here
  rather than an option.
* **Short-lived.** Tokens expire. `_REFRESH_MARGIN_S` renews early so a call never dies
  on a token that aged out mid-flight, which is the failure that makes people set long
  expiries and lose the benefit.
* **Attributable.** The token carries `azp`/`sub`, so the receiving service records who
  called rather than logging `dispatched_by: null`.

Credentials still come from the environment — that part does not change and should not.
What changes is *what* is in the environment: a client id and secret used only to obtain
short-lived scoped tokens, instead of a permanent all-powers bearer that is itself the
key to everything.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

import httpx

# Renew this long before `exp`. A token that expires in flight produces a 401 that looks
# like a configuration failure, which is how people "fix" it by setting a 30-day expiry.
_REFRESH_MARGIN_S = 30.0


def _default_audience_selector(resource: str) -> str:
    """The client scope that makes Keycloak stamp `aud` on the token.

    This exists because of a concrete gap the Keycloak worker surfaced during rollout:
    **Keycloak does not implement RFC 8707.** It silently discards the `resource` form
    field we send, so a naive client-credentials request comes back with *no `aud` claim
    at all*, and the resource server rejects it — fails closed, which is correct, but
    nothing works until the audience is supplied another way.

    Keycloak's documented substitute is an audience protocol-mapper attached to a
    *requested client scope*. The realm defines one selector scope per service
    (`resource:mneme`, `resource:axiom`, `resource:praxis`, …), each carrying an
    `oidc-audience-mapper`. Asking for that scope is what puts the right `aud` in the token.

    We derive the selector from the resource identifier's first hostname label so callers
    keep passing the one thing they actually know — *who they are calling* — rather than
    memorising a second parallel string. `https://mneme.control-alt.lan` → `resource:mneme`.
    A caller whose target does not follow that convention passes `audience_selector`
    explicitly; that is the escape hatch, not the norm.

    We still send the RFC 8707 `resource` field too. Keycloak ignores it, but a
    spec-compliant issuer would honour it, so the day this fleet moves off Keycloak the
    audience is already correct with no code change.
    """
    host = urlparse(resource).hostname or resource
    label = host.split(".", 1)[0].strip()
    return f"resource:{label}" if label else ""

# Lower bound on cache lifetime, so a pathologically short-lived token does not turn
# every call into a token request.
_MIN_CACHE_S = 5.0


class TokenAcquisitionError(RuntimeError):
    """Could not obtain a token, with the deployment fix named in the message.

    Deliberately verbose. `control_alt_ask` spent its first week returning an
    unexplained 401 that models paraphrased as success, so the Director was never asked
    and never knew it. A credential failure that does not say how to fix itself is how a
    dead mechanism stays dead.
    """


@dataclass(frozen=True)
class _CachedToken:
    value: str
    expires_at: float

    def usable(self) -> bool:
        return time.monotonic() < (self.expires_at - _REFRESH_MARGIN_S)


class ClientCredentialsProvider:
    """Obtains and caches access tokens for one (client, resource) pair.

    Thread-safe and cached per resource: one process may hold a token for Mneme and a
    different token for Praxis at the same time, and must not hand either to the wrong
    service. Keying the cache by resource is what enforces that at the type level rather
    than by remembering.
    """

    def __init__(
        self,
        token_endpoint: str,
        client_id: str,
        client_secret: str,
        *,
        timeout_s: float = 10.0,
        client_factory=None,
    ) -> None:
        self.token_endpoint = token_endpoint
        self.client_id = client_id
        self._client_secret = client_secret
        self._timeout_s = timeout_s
        self._client_factory = client_factory
        self._cache: dict[tuple[str, frozenset[str]], _CachedToken] = {}
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.token_endpoint and self.client_id and self._client_secret)

    def token(
        self, resource: str, scopes: Iterable[str] = (), *, audience_selector: str | None = None
    ) -> str:
        """A valid access token for `resource`, from cache when possible.

        `resource` is required. There is no "default audience" overload on purpose: an
        audience chosen by default is an audience nobody checked.

        `audience_selector` overrides the derived `resource:<label>` scope for the rare
        caller whose target host does not match the convention (see
        `_default_audience_selector`). Leave it unset and the right selector is derived
        from `resource`.
        """
        if not resource:
            raise ValueError("resource is required — a token with no audience is a static bearer again")
        if not self.configured:
            raise TokenAcquisitionError(
                "No OAuth client credentials are configured for this service. Set "
                "OAUTH_TOKEN_ENDPOINT, OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET on this "
                "container (compose already mounts the host-managed env file its sibling "
                "uses). Do not fall back to a static bearer token: that is the credential "
                "this replaced, and it cannot be scoped or attributed."
            )

        selector = audience_selector if audience_selector is not None else _default_audience_selector(resource)
        # The selector is part of what is requested, so it is part of the cache identity:
        # two calls for the same resource that ask for different audiences must not share
        # a token. In practice the selector is a function of the resource, but keying on it
        # keeps that an assumption the cache does not depend on.
        effective_scopes = frozenset(s for s in scopes if s) | ({selector} if selector else set())
        key = (resource, effective_scopes)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached.usable():
                return cached.value

        fetched = self._fetch(resource, effective_scopes)

        with self._lock:
            self._cache[key] = fetched
        return fetched.value

    def _fetch(self, resource: str, scopes: Iterable[str]) -> _CachedToken:
        form = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self._client_secret,
            # RFC 8707. A spec-compliant issuer mints a token whose `aud` is this. Keycloak
            # ignores it and relies on the `resource:<label>` selector scope instead — both
            # are sent so the audience is correct on either issuer. See
            # `_default_audience_selector`.
            "resource": resource,
        }
        scope_list = sorted(s for s in scopes if s)
        if scope_list:
            form["scope"] = " ".join(scope_list)

        client = self._client_factory() if self._client_factory else httpx.Client(timeout=self._timeout_s)
        try:
            resp = client.post(
                self.token_endpoint,
                data=form,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise TokenAcquisitionError(
                f"Authorization server unreachable at {self.token_endpoint}: "
                f"{type(exc).__name__}: {exc}. Nothing was called and no work was done — "
                "report this rather than proceeding as if the write succeeded."
            ) from exc
        finally:
            if self._client_factory is None:
                client.close()

        if resp.status_code >= 400:
            # The issuer's own error body names which piece is wrong (unknown client,
            # bad secret, unrecognised scope). Surfacing it verbatim is the difference
            # between a five-second fix and an afternoon.
            raise TokenAcquisitionError(
                f"{resp.status_code} from the authorization server for client "
                f"{self.client_id!r} requesting {resource!r}"
                + (f" with scope {' '.join(scope_list)!r}" if scope_list else "")
                + f". It said: {resp.text[:400]}"
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            raise TokenAcquisitionError(
                f"Authorization server returned a non-JSON body: {resp.text[:200]}"
            ) from exc

        access_token = payload.get("access_token")
        if not access_token:
            raise TokenAcquisitionError(
                f"Authorization server response carried no access_token: {payload!r}"
            )

        expires_in = float(payload.get("expires_in") or 300)
        return _CachedToken(
            value=str(access_token),
            expires_at=time.monotonic() + max(expires_in, _MIN_CACHE_S),
        )

    def auth_headers(
        self, resource: str, scopes: Iterable[str] = (), *, audience_selector: str | None = None
    ) -> dict[str, str]:
        """`Authorization: Bearer` for `resource`.

        A header rather than a cookie, deliberately: a header is not ambient, so it
        carries no CSRF obligation and nothing this process is tricked into loading can
        attach it.
        """
        return {"Authorization": f"Bearer {self.token(resource, scopes, audience_selector=audience_selector)}"}

    def invalidate(self, resource: str | None = None) -> None:
        """Drop cached tokens — after a 401, so the next call re-obtains rather than
        replaying the token that was just refused."""
        with self._lock:
            if resource is None:
                self._cache.clear()
            else:
                for key in [k for k in self._cache if k[0] == resource]:
                    self._cache.pop(key, None)


__all__ = ["ClientCredentialsProvider", "TokenAcquisitionError"]
