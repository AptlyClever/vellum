"""Pin the Kanon capability manifest to the shape Kanon will actually accept.

Kanon validates this payload with `AppCapabilityManifest`, which is declared
`extra="forbid"`. A key added here that Kanon does not know about makes observation
fail with a 502 on Kanon's side, not here — so the constraint is asserted locally
where it can fail loudly instead of silently degrading a fleet cutover.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from fastapi.testclient import TestClient

from backend.main import app


CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$")
ALLOWED_KEYS = {
    "schema_version", "app_id", "runtime", "routes",
    "data_sources", "links", "actions", "slots",
}
CAPABILITY_KEYS = ("data_sources", "links", "actions", "slots")
APP_ID = "vellum"
ROOT = Path(__file__).resolve().parents[1]


def _manifest() -> dict:
    response = TestClient(app).get("/api/kanon-capabilities")
    assert response.status_code == 200
    return response.json()


def test_manifest_matches_kanon_schema() -> None:
    manifest = _manifest()
    assert set(manifest) == ALLOWED_KEYS, "Kanon forbids extra keys; unknown keys 502 on observe"
    assert manifest["schema_version"] == 1
    assert manifest["app_id"] == APP_ID
    assert manifest["runtime"] in {"react", "vanilla"}


def test_capability_ids_are_valid_and_namespaced() -> None:
    manifest = _manifest()
    for key in CAPABILITY_KEYS:
        values = manifest[key]
        assert len(values) == len(set(values)), f"{key} must be unique"
        for value in values:
            assert CAPABILITY_RE.fullmatch(value), f"{value} is not a valid capability id"
            assert value.startswith(f"{APP_ID}."), f"{value} must be namespaced to {APP_ID}"


def test_routes_are_hash_routes() -> None:
    routes = _manifest()["routes"]
    assert "#/assets/:asset_id" in routes
    assert "vellum.asset.journey" in _manifest()["data_sources"]
    assert len(routes) == len(set(routes)), "routes must be unique"
    for route in routes:
        assert route.startswith("#/"), f"{route} must be a hash route"


def test_asset_journey_exposes_only_implemented_local_slots() -> None:
    assert _manifest()["slots"] == [
        "vellum.asset.identity",
        "vellum.asset.transformation",
        "vellum.asset.journey",
        "vellum.asset.outputs",
        "vellum.asset.destinations",
        "vellum.asset.evidence-footer",
    ]


def test_checked_in_asset_journey_composition_uses_the_observed_slot_contract() -> None:
    composition = json.loads(
        (ROOT / "docs" / "kanon-asset-journey.composition.json").read_text(encoding="utf-8")
    )
    assert composition["schema_version"] == 1
    assert composition["root"]["type"] == "layout.stack"
    nodes: list[dict] = []

    def walk(node: dict) -> None:
        nodes.append(node)
        for child in node.get("children", []):
            walk(child)

    walk(composition["root"])
    slots = [node["props"]["slot"] for node in nodes if node["type"] == "slot.custom"]
    assert slots == _manifest()["slots"]
    lens = next(node for node in nodes if node["id"] == "kanon_contract_lens")
    assert lens["visible_when"] == [
        {"context": "embed", "operator": "equals", "value": True}
    ]
    assert {node.get("source") for node in nodes} - {None} <= set(_manifest()["data_sources"])
    assert {
        node["props"]["link"] for node in nodes if node["type"] == "action.link"
    } <= set(_manifest()["links"])
