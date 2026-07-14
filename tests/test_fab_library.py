"""Launcher Fab catalog → per-pack acquisition classification."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from backend import fab_library as fab_library_mod
from backend.main import app


def _make_listings_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE local_listing (uid TEXT, title TEXT, listing_type TEXT, category_path TEXT)")
    conn.execute(
        "CREATE TABLE download_meta (listing_uid TEXT, format TEXT, path TEXT, cache_size INTEGER)"
    )
    conn.execute(
        "INSERT INTO local_listing VALUES ('u1', 'Mega Marble Material 4K', 'material', 'materials')"
    )
    conn.execute("INSERT INTO download_meta VALUES ('u1', 'unreal-engine', '', 123456)")
    conn.execute(
        "INSERT INTO local_listing VALUES ('u2', 'Fireworks Vol. 1 - Niagara', 'vfx', 'fire-explosions')"
    )
    conn.execute(
        "INSERT INTO download_meta VALUES "
        "('u2', 'unreal-engine', 'C:/ProgramData/Epic/EpicGamesLauncher/VaultCache/Firework0940f0d85d54V1', 638166358)"
    )
    conn.commit()
    conn.close()


def test_acquisition_seen_vs_unseen(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "listings.db"
    _make_listings_db(db)
    monkeypatch.setenv("VELLUM_FAB_LISTINGS_DB", str(db))
    fab_library_mod.clear_cache()

    seen = fab_library_mod.acquisition_for_asset(
        {"id": "mega-marble-material-4k", "display_name": "Mega Marble Material 4K", "engine": "unreal"}
    )
    assert seen["method"] == fab_library_mod.METHOD_FAB_ADD_TO_PROJECT
    assert seen["seen_by_launcher"] is True
    assert seen["ue_only"] is True
    assert "Add to Project" in seen["operator_hint"]
    assert "no standalone file download" in seen["operator_hint"]

    unseen = fab_library_mod.acquisition_for_asset(
        {"id": "arabic-fortress", "display_name": "Arabic Fortress", "engine": "unreal"}
    )
    assert unseen["method"] == fab_library_mod.METHOD_FAB_ADD_UNSEEN
    assert unseen["seen_by_launcher"] is False
    assert "cannot be downloaded" in unseen["operator_hint"]

    installable = fab_library_mod.acquisition_for_asset(
        {"id": "fireworks-vol-1-niagara", "display_name": "Fireworks Vol. 1 - Niagara", "engine": "unreal"},
        installable=True,
    )
    assert installable["method"] == fab_library_mod.METHOD_VAULT_INSTALL
    assert installable["vault_cache_path"]


def test_non_unreal_asset_is_manual(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VELLUM_FAB_LISTINGS_DB", str(tmp_path / "missing.db"))
    fab_library_mod.clear_cache()
    acq = fab_library_mod.acquisition_for_asset(
        {"id": "some-unity-pack", "display_name": "Some Unity Pack", "engine": "unity"}
    )
    assert acq["method"] == fab_library_mod.METHOD_MANUAL


def test_complete_project_override_uses_migration_workflow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VELLUM_FAB_LISTINGS_DB", str(tmp_path / "missing.db"))
    fab_library_mod.clear_cache()

    acq = fab_library_mod.acquisition_for_asset(
        {"id": "the-count-s-church", "display_name": "The Count's Church", "engine": "unreal"}
    )
    assert acq["method"] == fab_library_mod.METHOD_FAB_CREATE_PROJECT_MIGRATE
    assert acq["distribution_method"] == "Complete Project"
    assert acq["listing_uid"] == "64097225-d031-417b-9919-1d3a1c244d1c"
    assert acq["deferred"] is True
    assert acq["blocking"] is False
    assert "Create Project" in acq["operator_hint"]
    assert "Migrate" in acq["operator_hint"]


def test_asset_package_override_keeps_add_to_project(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "listings.db"
    _make_listings_db(db)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO local_listing VALUES ('u3', 'Arabic Fortress', 'environment', 'environments')"
    )
    conn.execute("INSERT INTO download_meta VALUES ('u3', 'unreal-engine', '', 0)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("VELLUM_FAB_LISTINGS_DB", str(db))
    fab_library_mod.clear_cache()

    acq = fab_library_mod.acquisition_for_asset(
        {"id": "arabic-fortress", "display_name": "Arabic Fortress", "engine": "unreal"}
    )
    assert acq["method"] == fab_library_mod.METHOD_FAB_ADD_TO_PROJECT
    assert acq["distribution_method"] == "Asset Package"
    assert acq["supported_unreal_versions"] == "5.3-5.7"
    assert acq["deferred"] is False
    assert acq["blocking"] is True
    assert "Show all projects" in acq["operator_hint"]


def test_listings_db_upload_endpoint(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src.db"
    _make_listings_db(src)
    dest = tmp_path / "hub-copy.db"
    monkeypatch.setenv("VELLUM_FAB_LISTINGS_DB", str(dest))
    fab_library_mod.clear_cache()

    client = TestClient(app)
    bad = client.post(
        "/api/import/fab-listings-db",
        files={"db": ("listings_v1.db", b"not a database", "application/octet-stream")},
    )
    assert bad.status_code == 400

    with src.open("rb") as fh:
        ok = client.post(
            "/api/import/fab-listings-db",
            files={"db": ("listings_v1.db", fh, "application/octet-stream")},
        )
    assert ok.status_code == 200, ok.text
    assert ok.json()["listing_count"] == 2
    assert dest.is_file()
    assert fab_library_mod.match_listing("Mega Marble Material 4K") is not None
