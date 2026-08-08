from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.register import (
    catalog_version,
    create_asset,
    enrich_asset,
    ensure_register,
    get_asset,
    list_assets,
    patch_asset,
    redeem_window,
    register_summary,
)


def test_seed_has_37_assets(pg_register) -> None:
    doc = ensure_register(force_reseed=True)
    assert len(doc["assets"]) == 37
    assert doc["assets"][0]["id"]


def test_redeem_window_open_and_expired() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    assert redeem_window("2027-07-06T11:00:00-07:00", now=now) == "open"
    assert redeem_window("2020-01-01T00:00:00-08:00", now=now) == "expired"
    assert redeem_window(None, now=now) == "unknown"


def test_list_filter_engine(pg_register) -> None:
    ensure_register(force_reseed=True)
    unreal = list_assets(engine="unreal")
    unity = list_assets(engine="unity")
    assert len(unreal) == 36
    assert len(unity) == 1
    assert all(a["redeem_window"] == "open" for a in list_assets())


def test_search_portal(pg_register) -> None:
    ensure_register(force_reseed=True)
    hits = list_assets(q="portal")
    assert len(hits) >= 1
    assert any("portal" in a["display_name"].lower() for a in hits)


def test_summary_counts(pg_register) -> None:
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


def test_health_via_app(pg_register) -> None:
    ensure_register(force_reseed=True)
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


def test_patch_asset_redemption(pg_register) -> None:
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


def test_patch_asset_missing_raises(pg_register) -> None:
    ensure_register(force_reseed=True)
    import pytest

    with pytest.raises(KeyError):
        patch_asset("does-not-exist", redemption_status="redeemed")


def test_catalog_version_changes_on_write(pg_register) -> None:
    ensure_register(force_reseed=True)
    before = catalog_version()
    patch_asset("fireworks-vol-1-niagara", redemption_status="redeemed")
    after = catalog_version()
    assert after != before


def test_create_asset_concurrent_same_id_only_one_wins(pg_register) -> None:
    """The identical whole-file bug this migration fixes let create_asset's
    get_asset(aid) is None / append TOCTOU race silently create two rows (or
    silently overwrite one) for the same asset_id under vellum-app and
    vellum-worker both racing it. INSERT ... ON CONFLICT DO NOTHING replaces
    that check-then-append with a single atomic statement -- prove it here
    with real concurrent threads instead of asserting it from the diff.
    """
    ensure_register(force_reseed=True)
    asset_id = "race-test-create-asset"

    results: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def attempt(n: int) -> None:
        barrier.wait(timeout=5)
        try:
            create_asset(
                display_name="Race Test Create Asset",
                asset_id=asset_id,
                engine="unreal",
            )
            results.append("created")
        except KeyError as exc:
            assert f"asset_exists:{asset_id}" in str(exc)
            results.append("exists")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert results.count("created") == 1
    assert results.count("exists") == 7

    matches = [a for a in list_assets() if a["id"] == asset_id]
    assert len(matches) == 1


def test_patch_asset_concurrent_different_fields_both_land(pg_register) -> None:
    """Simulates the actual cross-container race PX001 fixes: vellum-worker's
    record_paths job patching raw_location while an operator's PATCH
    /api/assets/{id} patches redemption_status for the SAME asset at the same
    time. The old whole-file read/mutate/write could drop one side's write
    entirely; per-row/per-column UPDATEs under a row lock cannot.
    """
    ensure_register(force_reseed=True)
    asset_id = "hangar-x"
    iterations = 25

    def patch_raw_location() -> None:
        for i in range(iterations):
            patch_asset(asset_id, raw_location=f"/vault/stage/{i}")

    def patch_redemption() -> None:
        for i in range(iterations):
            patch_asset(asset_id, redemption_status=f"status-{i}")

    t1 = threading.Thread(target=patch_raw_location)
    t2 = threading.Thread(target=patch_redemption)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    final = get_asset(asset_id)
    assert final is not None
    # Both threads' last writes must be visible -- neither field reverted to
    # a stale value, and the asset row itself was never dropped/duplicated.
    assert final["raw_location"] == f"/vault/stage/{iterations - 1}"
    assert final["redemption_status"] == f"status-{iterations - 1}"
    assert len([a for a in list_assets() if a["id"] == asset_id]) == 1
