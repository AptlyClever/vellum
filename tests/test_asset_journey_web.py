"""Static browser contract for the Asset Journey surface."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_index_loads_journey_surface_before_legacy_app() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="journey-root"' in html
    assert 'id="legacy-app"' in html
    assert '/static/journey.css' in html
    assert '/static/journey.js' in html
    assert html.index('/static/journey.js') < html.index('/static/app.js')


def test_journey_script_exposes_route_and_accessible_navigation() -> None:
    script = (ROOT / "web" / "journey.js").read_text(encoding="utf-8")
    assert "#/assets/" in script
    assert "/journey`" in script
    assert "aria-expanded" in script
    assert "aria-controls" in script
    assert "America/New_York" in script
    assert "vellum.journey.navigation.hidden" in script
    assert "data-kanon-release-id" in script
    assert "featured_outputs" in script
    assert "Inspect all ${outputs.length} outputs and technical evidence" in script
    assert "consumer_receipt" in script
    assert "data-featured-video" in script
    assert "data-rest-frame" in script
    assert "video.dataset.previewTime" in script
    assert "data-media-fallback" in script
    assert "wireAssetPalette" in script
    assert 'data-asset-palette' in script
    assert "applyKanonDirection" in script
    assert "applyKanonComposition" in script
    assert "validateKanonNode(documentValue.root" in script
    assert "data-kanon-fallback-reason" in script
    assert 'data-kanon-slot="vellum.asset.transformation"' in script


def test_journey_css_has_wide_hidden_and_narrow_drawer_states() -> None:
    css = (ROOT / "web" / "journey.css").read_text(encoding="utf-8")
    assert ".journey-shell.nav-hidden" in css
    assert ".journey-show-navigation" in css
    assert ".journey-poster-link" in css
    assert ".journey-technical-inventory" in css
    assert "@media (max-width: 860px)" in css
    assert "overflow-x: clip" in css
    assert "--journey-asset-5" in css
    assert ".journey-kanon-composition" in css


def test_hidden_legacy_surface_does_not_poll_behind_journey() -> None:
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'if ($("legacy-app")?.hidden) return;' in script
    assert 'window.addEventListener("hashchange", syncLegacySurface);' in script
