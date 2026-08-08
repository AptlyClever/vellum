"""Vellum -> Mneme outbound authentication: client-credentials tokens.

Two things are under test here, and they are different things.

**The ladder** (`backend/mneme.py`): which credential Vellum presents, in which order,
and what it says when it does. These are the tests that would have caught the failure
this fleet actually had - configuring OAuth on a caller and thereby breaking the call.

**The boundary** (`backend/auth/jwt_validator.py`): that a token minted for one service
is refused by another. Vellum does not validate inbound tokens, so nothing in Vellum
exercises the validator in production. That is exactly why it is asserted here: the
whole reason to replace a static bearer with an audience-scoped token is the promise
that a stolen Vellum credential cannot be replayed against Axiom or Daedalus. An
unasserted promise is a comment, and comments in this stack have been wrong before.

Tokens are minted locally with a throwaway RSA key and the validator is pointed at an
in-memory JWKS, so these run offline with no Keycloak. The claim shapes match what the
live realm issues (`azp`, space-delimited `scope`, `typ: at+jwt`).
"""

from __future__ import annotations

import json
import logging
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend import mneme as mneme_mod
from backend.auth import TokenError, TokenValidator

ISSUER = "http://keycloak.test/realms/control-alt"
TOKEN_ENDPOINT = f"{ISSUER}/protocol/openid-connect/token"
MNEME_AUD = "https://mneme.control-alt.lan"
DAEDALUS_AUD = "https://daedalus.control-alt.lan"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-key-1"


def _mint(
    *,
    audience: str = MNEME_AUD,
    scope: str = "mneme:documents.write",
    expires_in: int = 300,
    subject: str = "service-account-vellum",
    azp: str = "vellum",
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": audience,
            "sub": subject,
            "azp": azp,
            "scope": scope,
            "iat": now,
            "exp": now + expires_in,
        },
        _KEY,
        algorithm="RS256",
        headers={"kid": _KID, "typ": "at+jwt"},
    )


def _validator_for(audience: str, monkeypatch) -> TokenValidator:
    """A TokenValidator wired to the local key, standing in for a resource server."""
    validator = TokenValidator(ISSUER, audience)
    monkeypatch.setattr(
        validator._jwks, "signing_key", lambda _token: _KEY.public_key()
    )
    return validator


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Every test starts with no credentials of any kind and no cached provider."""
    for var in (
        "VELLUM_OAUTH_ISSUER",
        "VELLUM_OAUTH_TOKEN_ENDPOINT",
        "VELLUM_OAUTH_CLIENT_ID",
        "VELLUM_OAUTH_CLIENT_SECRET",
        "VELLUM_OAUTH_MNEME_AUDIENCE",
        "VELLUM_OAUTH_ENFORCE",
        "MNEME_WRITE_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    mneme_mod.reset_provider()
    yield
    mneme_mod.reset_provider()


def _configure_oauth(monkeypatch, *, secret: str = "dev-only-vellum-CHANGE-ME") -> None:
    monkeypatch.setenv("VELLUM_OAUTH_ISSUER", ISSUER)
    monkeypatch.setenv("VELLUM_OAUTH_CLIENT_ID", "vellum")
    monkeypatch.setenv("VELLUM_OAUTH_CLIENT_SECRET", secret)
    mneme_mod.reset_provider()


class _FakeTokenEndpoint:
    """Stands in for Keycloak's token endpoint, recording what was asked for."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.requests: list[dict[str, str]] = []

    def __call__(self):  # used as ClientCredentialsProvider's client_factory
        endpoint = self

        class _Client:
            def post(self, url, *, data, headers):
                endpoint.requests.append(dict(data))
                return httpx.Response(
                    200,
                    json={"access_token": endpoint.token, "expires_in": 300},
                    request=httpx.Request("POST", url),
                )

            def close(self):
                pass

        return _Client()


def _install_fake_issuer(monkeypatch, token: str) -> _FakeTokenEndpoint:
    fake = _FakeTokenEndpoint(token)
    _configure_oauth(monkeypatch)
    provider = mneme_mod.provider()
    assert provider is not None
    monkeypatch.setattr(provider, "_client_factory", fake)
    return fake


# ---------------------------------------------------------------------------
# The boundary: a token minted for another service must be refused.
# ---------------------------------------------------------------------------


def test_token_minted_for_another_service_is_refused(monkeypatch) -> None:
    """The single most important assertion in this file.

    A token Vellum holds for Mneme must be worthless against Daedalus. If this ever
    passes-through, the audience-scoped token has bought nothing over the static bearer
    it replaced: a compromise of Vellum becomes a compromise of everything Vellum's
    credential can reach.
    """
    daedalus = _validator_for(DAEDALUS_AUD, monkeypatch)
    vellums_mneme_token = _mint(audience=MNEME_AUD)

    with pytest.raises(TokenError) as excinfo:
        daedalus.validate(vellums_mneme_token)

    assert "minted for a different service" in str(excinfo.value)
    # And the same token is accepted by the service it WAS minted for, so the test
    # above is proving an audience check rather than a token that is simply broken.
    mneme = _validator_for(MNEME_AUD, monkeypatch)
    assert mneme.validate(vellums_mneme_token).client_id == "vellum"


def test_valid_token_is_accepted_with_its_scope(monkeypatch) -> None:
    mneme = _validator_for(MNEME_AUD, monkeypatch)
    principal = mneme.validate(_mint())
    assert principal.subject == "service-account-vellum"
    assert principal.has_scope("mneme:documents.write")
    assert principal.issuer == ISSUER


def test_expired_token_is_refused(monkeypatch) -> None:
    mneme = _validator_for(MNEME_AUD, monkeypatch)
    with pytest.raises(TokenError) as excinfo:
        mneme.validate(_mint(expires_in=-3600))
    assert "expired" in str(excinfo.value)


def test_missing_scope_is_403_not_401(monkeypatch) -> None:
    """Authenticated-but-unauthorized must be 403, never 401.

    A 401 tells the caller its credential is bad and invites it to retry with a new
    token, which will fail identically forever. 403 says the credential is fine and the
    grant is not. `ScopeError` is the 403 half and is deliberately not a `TokenError`.
    """
    from backend.auth import ScopeError
    from backend.auth.dependencies import _forbidden, _unauthorized

    mneme = _validator_for(MNEME_AUD, monkeypatch)
    read_only = _mint(scope="mneme:documents.read")

    principal = mneme.validate(read_only)  # authentication succeeds ...
    with pytest.raises(ScopeError) as excinfo:  # ... authorization does not
        principal.require("mneme:documents.write")

    # ScopeError and TokenError are separate types precisely so they cannot collapse
    # into one status. Assert the mapping the fleet actually serves.
    assert not isinstance(excinfo.value, TokenError)
    assert _forbidden(excinfo.value).status_code == 403
    assert _unauthorized(TokenError("token expired")).status_code == 401


# ---------------------------------------------------------------------------
# The ladder: which credential Vellum presents.
# ---------------------------------------------------------------------------


def test_oauth_configured_sends_client_credentials_token(monkeypatch) -> None:
    fake = _install_fake_issuer(monkeypatch, _mint())
    headers = mneme_mod.auth_headers(mneme_mod.SCOPE_DOCUMENTS_WRITE)

    assert headers["Authorization"].startswith("Bearer ")
    assert headers["Authorization"] != "Bearer static-token"
    form = fake.requests[-1]
    assert form["grant_type"] == "client_credentials"
    assert form["client_id"] == "vellum"
    # RFC 8707 `resource` is sent even though Keycloak discards it, and the
    # `resource:mneme` selector scope is what actually puts `aud` on the token.
    assert form["resource"] == MNEME_AUD
    assert set(form["scope"].split()) == {"mneme:documents.write", "resource:mneme"}


def test_read_path_requests_the_read_scope_not_write(monkeypatch) -> None:
    """A reconciliation lookup must not carry a credential that can create documents."""
    fake = _install_fake_issuer(monkeypatch, _mint(scope="mneme:documents.read"))
    mneme_mod.auth_headers(mneme_mod.SCOPE_DOCUMENTS_READ)

    form = fake.requests[-1]
    assert set(form["scope"].split()) == {"mneme:documents.read", "resource:mneme"}


def test_oauth_takes_precedence_over_the_static_token(monkeypatch) -> None:
    monkeypatch.setenv("MNEME_WRITE_TOKEN", "static-token")
    fake = _install_fake_issuer(monkeypatch, _mint())

    headers = mneme_mod.auth_headers(mneme_mod.SCOPE_DOCUMENTS_WRITE)

    assert headers["Authorization"] != "Bearer static-token"
    assert fake.requests, "the token endpoint was never called"


def test_static_token_still_works_and_logs_its_deprecation(monkeypatch, caplog) -> None:
    """Tier 2 must keep working with OAuth unconfigured, and must keep saying so.

    Both halves matter. Removing the fallback before every caller is converted takes
    the fleet down; letting it go quiet is how a credential that was supposed to be
    temporary is still load-bearing two years later.
    """
    monkeypatch.setenv("MNEME_WRITE_TOKEN", "static-token")
    assert mneme_mod.oauth_configured() is False

    with caplog.at_level(logging.WARNING, logger="backend.mneme"):
        headers = mneme_mod.auth_headers(mneme_mod.SCOPE_DOCUMENTS_WRITE)

    assert headers == {"Authorization": "Bearer static-token"}
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "the deprecated static token fired without announcing itself"
    assert "DEPRECATED" in warnings[0].getMessage()
    assert "MNEME_WRITE_TOKEN" in warnings[0].getMessage()


def test_enforcement_defaults_off(monkeypatch) -> None:
    """Shipping with enforcement on is how configuring OAuth becomes an outage."""
    assert mneme_mod.oauth_enforced() is False


def test_enforcement_on_refuses_the_static_token(monkeypatch) -> None:
    monkeypatch.setenv("MNEME_WRITE_TOKEN", "static-token")
    monkeypatch.setenv("VELLUM_OAUTH_ENFORCE", "true")

    with pytest.raises(mneme_mod.MnemeError) as excinfo:
        mneme_mod.auth_headers(mneme_mod.SCOPE_DOCUMENTS_WRITE)

    assert "mneme_oauth_required" in str(excinfo.value)
    # The refusal must name the fix, or it is an unexplained 401 in a log somewhere.
    assert "VELLUM_OAUTH_CLIENT_SECRET" in str(excinfo.value)


def test_no_credential_at_all_reports_write_disabled(monkeypatch) -> None:
    """Unchanged error string: callers and their tests keep working."""
    with pytest.raises(mneme_mod.MnemeError) as excinfo:
        mneme_mod.auth_headers(mneme_mod.SCOPE_DOCUMENTS_WRITE)
    assert "mneme_write_disabled" in str(excinfo.value)


def test_token_endpoint_failure_does_not_fall_back_to_static(monkeypatch) -> None:
    """A broken issuer must be loud, not silently papered over by the old credential.

    Falling back here would mean a misconfigured OAuth deployment looks like a working
    one, and the static token stays in production because nothing ever complains.
    """
    monkeypatch.setenv("MNEME_WRITE_TOKEN", "static-token")
    _configure_oauth(monkeypatch)
    provider = mneme_mod.provider()
    assert provider is not None

    class _DeadClient:
        def post(self, url, *, data, headers):
            raise httpx.ConnectError("connection refused")

        def close(self):
            pass

    monkeypatch.setattr(provider, "_client_factory", lambda: _DeadClient())

    with pytest.raises(mneme_mod.MnemeError) as excinfo:
        mneme_mod.auth_headers(mneme_mod.SCOPE_DOCUMENTS_WRITE)
    assert "mneme_token_unavailable" in str(excinfo.value)
    assert "static-token" not in str(excinfo.value)


def test_token_endpoint_is_derived_from_the_issuer(monkeypatch) -> None:
    monkeypatch.setenv("VELLUM_OAUTH_ISSUER", ISSUER + "/")
    assert mneme_mod.oauth_token_endpoint() == TOKEN_ENDPOINT


def test_provider_is_rebuilt_when_the_secret_rotates(monkeypatch) -> None:
    _configure_oauth(monkeypatch, secret="old")
    first = mneme_mod.provider()
    _configure_oauth(monkeypatch, secret="new")
    second = mneme_mod.provider()
    assert first is not second, "a rotated secret must not keep serving old tokens"


# ---------------------------------------------------------------------------
# End to end through the real request paths.
# ---------------------------------------------------------------------------


def test_create_document_presents_the_oauth_token(monkeypatch) -> None:
    monkeypatch.setenv("MNEME_BASE_URL", "http://mneme.test")
    minted = _mint()
    _install_fake_issuer(monkeypatch, minted)
    captured: dict = {}

    def fake_post(url, *, headers, files, timeout):
        captured.update({"url": url, "headers": headers, "files": files})
        return httpx.Response(
            201, json={"id": "doc-oauth"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    result = mneme_mod.create_document(
        title="t",
        project_id="bandit",
        source_url="https://example.com/s",
        captured_at="2026-07-31T00:00:00+00:00",
        tags=["visual-research"],
        body="# body",
    )

    assert result["id"] == "doc-oauth"
    assert captured["headers"]["Authorization"] == f"Bearer {minted}"
    assert captured["headers"]["Accept"] == "application/json"
    # The multipart contract Mneme requires must survive the auth change.
    assert json.loads(captured["files"]["metadata"][1])["project_id"] == "bandit"


def test_delete_document_presents_the_oauth_token(monkeypatch) -> None:
    monkeypatch.setenv("MNEME_BASE_URL", "http://mneme.test")
    minted = _mint()
    _install_fake_issuer(monkeypatch, minted)
    captured: dict = {}

    def fake_delete(url, *, headers, timeout):
        captured.update({"url": url, "headers": headers})
        return httpx.Response(204, request=httpx.Request("DELETE", url))

    monkeypatch.setattr(httpx, "delete", fake_delete)
    mneme_mod.delete_document("doc-1")

    assert captured["headers"]["Authorization"] == f"Bearer {minted}"


def test_reconcile_read_is_unauthenticated_when_no_credential_exists(
    monkeypatch,
) -> None:
    """The compensation path must not fail closed on a missing credential.

    `find_document_by_tag` runs after a POST that may already have succeeded. Refusing
    to look because there is no token turns a recoverable ambiguity into a document
    nobody can find - so this read attaches a token when one is available and proceeds
    without one when it is not, exactly as it behaved before OAuth existed.
    """
    monkeypatch.setenv("MNEME_BASE_URL", "http://mneme.test")
    captured: dict = {}

    def fake_get(url, *, params, headers, timeout):
        captured.update({"headers": headers})
        return httpx.Response(
            200,
            json={"items": [{"id": "doc-9", "tags": ["vellum-vr-x"]}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    found = mneme_mod.find_document_by_tag("vellum-vr-x", project_id="bandit")

    assert found is not None and found["id"] == "doc-9"
    assert "Authorization" not in captured["headers"]
