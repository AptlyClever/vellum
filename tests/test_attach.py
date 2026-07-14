"""Tests for Vellum Attach (vault lookdev → product surfaces)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from backend import attach as attach_mod
from backend import lookdev as lookdev_mod


def _seed_output(tmp_path: Path, monkeypatch, *, lane: str = "hail-overlay", kind: str = "niagara-render") -> dict:
    vault = tmp_path / "vault"
    png_dir = vault / "05-derived-renders" / lane / "portal-vfx-enhanced" / "niagara"
    png_dir.mkdir(parents=True)
    src = png_dir / "hero.png"
    # Minimal valid PNG (1x1)
    src.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        )
    )
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(vault))
    catalog = tmp_path / "derived.yaml"
    monkeypatch.setenv("VELLUM_DERIVED_PATH", str(catalog))
    row = {
        "id": "derived-test-portal-1",
        "asset_id": "portal-vfx-enhanced",
        "lane": lane,
        "kind": kind,
        "path": str(src),
        "created_at": "2026-07-14T00:00:00+00:00",
        "note": "test",
    }
    catalog.write_text(
        yaml.dump({"schema_version": 1, "outputs": [row]}, sort_keys=False),
        encoding="utf-8",
    )
    lookdev_mod._CATALOG_CACHE = None
    lookdev_mod._CATALOG_MTIME = None
    return row


def test_attach_lcard_and_bandit(tmp_path, monkeypatch):
    _seed_output(tmp_path, monkeypatch)
    attachments = tmp_path / "attachments.yaml"
    monkeypatch.setenv("VELLUM_ATTACHMENTS_PATH", str(attachments))
    monkeypatch.delenv("VELLUM_VAULT_ATTACHMENTS_PATH", raising=False)

    lcard_dir = tmp_path / "lcard-media"
    bandit_dir = tmp_path / "bandit-web" / "vellum"
    monkeypatch.setenv("LCARD_VELLUM_MEDIA_DIR", str(lcard_dir))
    monkeypatch.setenv("BANDIT_VELLUM_STATIC_DIR", str(bandit_dir))
    monkeypatch.setenv("LCARD_BASE_URL", "http://lcard.test")
    monkeypatch.setenv("BANDIT_BASE_URL", "http://bandit.test")

    lcard = attach_mod.attach(derived_output_id="derived-test-portal-1", target="lcard")
    assert lcard["target"] == "lcard"
    assert lcard["status"] == "attached"
    assert (lcard_dir / "manifest.json").is_file()
    assert any(lcard_dir.glob("*.png"))

    bandit = attach_mod.attach(derived_output_id="derived-test-portal-1", target="bandit")
    assert bandit["target"] == "bandit"
    hero = bandit_dir / "portal-vfx-enhanced" / "hero.png"
    assert hero.is_file()
    assert "vellum-preview" in bandit["deep_link"]

    listed = attach_mod.list_attachments(asset_id="portal-vfx-enhanced")
    assert len(listed) == 2


def test_attach_hail_copies_without_register(tmp_path, monkeypatch):
    _seed_output(tmp_path, monkeypatch)
    attachments = tmp_path / "attachments.yaml"
    monkeypatch.setenv("VELLUM_ATTACHMENTS_PATH", str(attachments))
    monkeypatch.delenv("VELLUM_VAULT_ATTACHMENTS_PATH", raising=False)
    glyph_dir = tmp_path / "glyph-hero-images"
    monkeypatch.setenv("AXIOM_GLYPH_HERO_IMAGES", str(glyph_dir))
    monkeypatch.setenv("AXIOM_BASE_URL", "http://axiom.test")
    monkeypatch.setenv("AXIOM_PUBLIC_BASE_URL", "http://axiom.test")

    row = attach_mod.attach(
        derived_output_id="derived-test-portal-1",
        target="hail",
        register_glyph=False,
    )
    assert row["target"] == "hail"
    dest = Path(row["target_ref"]["dest"])
    assert dest.is_file()
    assert dest.parent == glyph_dir
    assert "forge?glyph=" in row["deep_link"]


def test_prefer_hail_overlay(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(vault))
    catalog = tmp_path / "derived.yaml"
    monkeypatch.setenv("VELLUM_DERIVED_PATH", str(catalog))
    rows = []
    for lane, kind, name in (
        ("slots", "still", "a.png"),
        ("hail-overlay", "niagara-render", "b.png"),
    ):
        d = vault / "05-derived-renders" / lane / "pack" / "x"
        d.mkdir(parents=True)
        p = d / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        rows.append(
            {
                "id": f"derived-{lane}-{kind}",
                "asset_id": "pack",
                "lane": lane,
                "kind": kind,
                "path": str(p),
                "created_at": "2026-07-14T00:00:00+00:00",
            }
        )
    catalog.write_text(yaml.dump({"schema_version": 1, "outputs": rows}), encoding="utf-8")
    lookdev_mod._CATALOG_CACHE = None
    lookdev_mod._CATALOG_MTIME = None
    preferred = attach_mod.prefer_output_for_asset("pack")
    assert preferred is not None
    assert preferred["lane"] == "hail-overlay"
