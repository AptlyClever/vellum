from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from backend.register import (
    enrich_asset,
    ensure_register,
    list_assets,
    patch_asset,
    redeem_window,
    register_summary,
)


def test_seed_has_37_assets(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    doc = ensure_register(force_reseed=True)
    assert len(doc["assets"]) == 37
    assert reg.is_file()


def test_redeem_window_open_and_expired() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    assert redeem_window("2027-07-06T11:00:00-07:00", now=now) == "open"
    assert redeem_window("2020-01-01T00:00:00-08:00", now=now) == "expired"
    assert redeem_window(None, now=now) == "unknown"


def test_list_filter_engine(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    ensure_register(force_reseed=True)
    unreal = list_assets(engine="unreal")
    unity = list_assets(engine="unity")
    assert len(unreal) == 36
    assert len(unity) == 1
    assert all(a["redeem_window"] == "open" for a in list_assets())


def test_search_portal(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    ensure_register(force_reseed=True)
    hits = list_assets(q="portal")
    assert len(hits) >= 1
    assert any("portal" in a["display_name"].lower() for a in hits)


def test_summary_counts(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "register.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    ensure_register(force_reseed=True)
    summary = register_summary()
    assert summary["count"] == 37
    assert summary["redeem_open"] == 37
    assert "unreal" in summary["engines"]


def test_enrich_preserves_identity() -> None:
    asset = {
        "id": "demo",
        "display_name": "Demo",
        "redemption_deadline": "2027-07-06T11:00:00-07:00",
    }
    out = enrich_asset(asset, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert out["id"] == "demo"
    assert out["redeem_window"] == "open"
    assert "redeem_window" not in asset


def test_health_via_app(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    reg = tmp_path / "register.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["app"] == "vellum"
    assert body["register"]["count"] == 37

    listed = client.get("/api/assets", params={"q": "hangar"})
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1


def test_patch_asset_redemption(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    reg = tmp_path / "register.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    ensure_register(force_reseed=True)

    updated = patch_asset(
        "fireworks-vol-1-niagara",
        redemption_status="redeemed",
        raw_location="/tmp/vault/fireworks",
        intake_notes="pilot",
    )
    assert updated["redemption_status"] == "redeemed"
    assert updated["raw_location"] == "/tmp/vault/fireworks"

    from backend.main import app

    client = TestClient(app)
    r = client.patch(
        "/api/assets/fireworks-vol-1-niagara",
        json={"redemption_status": "redeemed", "intake_notes": "via api"},
    )
    assert r.status_code == 200
    assert r.json()["intake_notes"] == "via api"
