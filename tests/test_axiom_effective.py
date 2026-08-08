"""Axiom effective-settings proxy — fail-soft fetch + route."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from backend import axiom_effective as axiom_effective_mod
from backend.main import app


SAMPLE_EFFECTIVE = {
    "app_id": "vellum",
    "theme_id": "games",
    "theme": {"tokens": {"--ca-bg": "#0a0a0a", "--ca-brand-500": "#ff6600"}, "mode": "dark"},
    "resolved_token_overrides": {"--ca-bg": "#0a0a0a"},
    "branding": {
        "logo_url": "https://axiom.test/logo.png",
        "favicon_url": "https://axiom.test/favicon.ico",
        "document_title": "Vellum — Control Alt",
    },
    "app_settings": {},
    "registry_display_name": "Vellum",
    "registry_description": "Asset vault",
}


def _reset_cache():
    axiom_effective_mod._cache["at"] = 0.0
    axiom_effective_mod._cache["value"] = None


def test_axiom_effective_route_success(monkeypatch):
    _reset_cache()

    def fake_get(url, **kwargs):
        assert url.endswith("/api/effective/vellum")
        return httpx.Response(200, json=SAMPLE_EFFECTIVE)

    monkeypatch.setattr(axiom_effective_mod.httpx, "get", fake_get)

    client = TestClient(app)
    res = client.get("/api/axiom-effective")
    assert res.status_code == 200
    body = res.json()
    assert body["app_id"] == "vellum"
    assert body["branding"]["document_title"] == "Vellum — Control Alt"


def test_axiom_effective_route_unreachable(monkeypatch):
    _reset_cache()

    def boom(url, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(axiom_effective_mod.httpx, "get", boom)

    client = TestClient(app)
    res = client.get("/api/axiom-effective")
    assert res.status_code == 200
    assert res.json() == {}


def test_axiom_effective_route_non_200(monkeypatch):
    _reset_cache()

    def fake_get(url, **kwargs):
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(axiom_effective_mod.httpx, "get", fake_get)

    client = TestClient(app)
    res = client.get("/api/axiom-effective")
    assert res.status_code == 200
    assert res.json() == {}
