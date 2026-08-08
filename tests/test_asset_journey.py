"""Asset Journey read model and HTTP contract."""

from __future__ import annotations

from pathlib import Path
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from backend import journey as journey_mod
from backend.main import app


def _records(tmp_path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    image_bytes = BytesIO()
    Image.new("RGB", (24, 16), (28, 46, 102)).save(image_bytes, format="PNG")
    source = tmp_path / "source.png"
    source.write_bytes(image_bytes.getvalue())
    capture = tmp_path / "capture.png"
    capture.write_bytes(image_bytes.getvalue())
    delivered = tmp_path / "burst.webm"
    delivered.write_bytes(b"webm-data")
    rejected = tmp_path / "rejected.webm"
    rejected.write_bytes(b"bad")

    runs = [
        {
            "run_id": "intake-1",
            "asset_id": "fireworks-vol-1-niagara",
            "created_at": "2026-07-12T23:59:32-04:00",
            "steps": [
                {
                    "step_id": "download_epic",
                    "status": "done",
                    "updated_at": "2026-07-12T23:59:46-04:00",
                },
                {
                    "step_id": "stage_vault",
                    "status": "done",
                    "updated_at": "2026-07-13T00:00:00-04:00",
                },
            ],
        }
    ]
    lookdev = [
        {
            "id": "capture-1",
            "asset_id": "fireworks-vol-1-niagara",
            "lane": "hail-overlay",
            "kind": "niagara-render",
            "path": str(capture),
            "created_at": "2026-07-13T20:51:34-04:00",
            "note": "Niagara MRQ max_luma",
            "system_name": "NS_Burst",
        },
        {
            "id": "source-1",
            "asset_id": "fireworks-vol-1-niagara",
            "lane": "slots",
            "kind": "hero-still",
            "path": str(source),
            "created_at": "2026-07-13T00:07:53-04:00",
            "note": "Fab catalog thumbnail (https://example.test/source.png).",
        },
    ]
    elements = [
        {
            "id": "gr-good",
            "asset_id": "fireworks-vol-1-niagara",
            "pack": "FireworksV1",
            "kind": "vfx-clip",
            "path": str(delivered),
            "lanes": ["slots"],
            "lane_paths": {"slots": str(delivered)},
            "created_at": "2026-07-16T20:11:19-04:00",
            "meta": {
                "system": "NS_Burst",
                "validation": {
                    "ok": True,
                    "width": 1920,
                    "height": 1080,
                    "alpha": True,
                    "duration_seconds": 4.0,
                },
            },
        },
        {
            "id": "gr-bad",
            "asset_id": "fireworks-vol-1-niagara",
            "pack": "FireworksV1",
            "kind": "vfx-clip",
            "path": str(rejected),
            "lanes": ["hail-overlay"],
            "lane_paths": {"hail-overlay": str(rejected)},
            "created_at": "2026-07-16T20:12:00-04:00",
            "meta": {"validation": {"ok": False}},
        },
        {
            "id": "gr-plan",
            "asset_id": "fireworks-vol-1-niagara",
            "pack": "FireworksV1",
            "kind": "bake-plan",
            "path": str(tmp_path / "missing-plan.json"),
            "lanes": [],
            "created_at": "2026-07-15T20:00:00-04:00",
            "meta": {},
        },
    ]
    return runs, lookdev, elements


def test_build_asset_journey_uses_evidence_not_catalog_presence(
    tmp_path: Path, monkeypatch
) -> None:
    runs, lookdev, elements = _records(tmp_path)
    asset = {
        "id": "fireworks-vol-1-niagara",
        "display_name": "Fireworks Vol. 1 - Niagara",
        "engine": "unreal",
        "package_type": "Unreal Engine Niagara VFX",
        "store_label": "Epic Games Store",
        "project_fit": "Slots wins, Hail stingers, Arcade celebrations.",
        "host_content_path": r"D:\Games\VellumLibrary\Content\FireworksV1",
        "ue_in_project": "in_project",
        "raw_location": "/mnt/data/vault/vellum/01-source-bundles/fireworks",
    }
    monkeypatch.setattr(journey_mod.register_mod, "get_asset", lambda _id: asset)
    monkeypatch.setattr(journey_mod.intake_mod, "list_runs", lambda **_kw: runs)
    monkeypatch.setattr(journey_mod.lookdev_mod, "list_outputs", lambda **_kw: lookdev)
    monkeypatch.setattr(journey_mod.game_ready_mod, "list_elements", lambda **_kw: elements)
    monkeypatch.setattr(journey_mod, "_bandit_consumer_receipt", lambda _ids: None)
    monkeypatch.setattr(
        journey_mod.lookdev_mod,
        "resolve_safe_file",
        lambda row: Path(row["path"]),
    )
    monkeypatch.setattr(
        journey_mod.game_ready_mod,
        "resolve_safe_file",
        lambda row: Path(row["path"]),
    )

    result = journey_mod.build_asset_journey("fireworks-vol-1-niagara")

    assert result["schema_version"] == 1
    assert result["status"] == "delivered"
    assert result["counts"] == {
        "lookdev_outputs": 2,
        "catalog_rows": 3,
        "game_ready": 1,
        "published": 1,
        "systems": 1,
        "bandit_ready_clips": 0,
    }
    assert [step["id"] for step in result["milestones"]] == [
        "registered",
        "staged-factory",
        "trusted-capture",
        "game-ready",
        "destinations",
    ]
    assert all(step["state"] == "confirmed" for step in result["milestones"])
    assert result["transformation"]["source"]["file_href"].endswith("source-1/file")
    assert result["transformation"]["capture"]["file_href"].endswith("capture-1/file")
    assert [item["id"] for item in result["outputs"]] == ["gr-good"]
    assert [item["id"] for item in result["featured_outputs"]] == ["gr-good"]
    assert result["outputs"][0]["bytes"] == len(b"webm-data")
    assert result["outputs"][0]["preview"] == "video"

    destinations = {item["id"]: item for item in result["destinations"]}
    assert destinations["bandit"]["state"] == "received"
    assert destinations["bandit"]["output_count"] == 1
    assert destinations["hails"]["state"] == "preview-only"
    assert destinations["hails"]["output_count"] == 0
    assert destinations["proscenium"]["state"] == "no-evidence"


def test_missing_timestamps_are_explicit_not_invented(monkeypatch) -> None:
    monkeypatch.setattr(
        journey_mod.register_mod,
        "get_asset",
        lambda _id: {"id": "asset-1", "display_name": "Asset One"},
    )
    monkeypatch.setattr(journey_mod.intake_mod, "list_runs", lambda **_kw: [])
    monkeypatch.setattr(journey_mod.lookdev_mod, "list_outputs", lambda **_kw: [])
    monkeypatch.setattr(journey_mod.game_ready_mod, "list_elements", lambda **_kw: [])
    monkeypatch.setattr(journey_mod.lookdev_mod, "resolve_fab_thumbnail_url", lambda _name: None)
    monkeypatch.setattr(journey_mod, "_bandit_consumer_receipt", lambda _ids: None)

    result = journey_mod.build_asset_journey("asset-1")

    registered = result["milestones"][0]
    assert registered["state"] == "confirmed"
    assert registered["occurred_at"] is None
    assert registered["time_note"] == "Confirmed; time not recorded"
    assert result["status"] == "registered"


def test_journey_route_returns_404_for_unknown_asset() -> None:
    response = TestClient(app).get("/api/assets/not-a-real-asset/journey")
    assert response.status_code == 404
    assert response.json()["detail"] == "asset_not_found"


def test_broken_images_are_not_presented_as_trusted_evidence(tmp_path: Path, monkeypatch) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"")
    monkeypatch.setattr(
        journey_mod.register_mod,
        "get_asset",
        lambda _id: {"id": "asset-1", "display_name": "Asset One"},
    )
    monkeypatch.setattr(journey_mod.intake_mod, "list_runs", lambda **_kw: [])
    monkeypatch.setattr(
        journey_mod.lookdev_mod,
        "list_outputs",
        lambda **_kw: [{"id": "broken", "kind": "niagara-render", "path": str(broken)}],
    )
    monkeypatch.setattr(journey_mod.game_ready_mod, "list_elements", lambda **_kw: [])
    monkeypatch.setattr(journey_mod.lookdev_mod, "resolve_safe_file", lambda row: Path(row["path"]))
    monkeypatch.setattr(journey_mod.lookdev_mod, "resolve_fab_thumbnail_url", lambda _name: None)
    monkeypatch.setattr(journey_mod, "_bandit_consumer_receipt", lambda _ids: None)

    result = journey_mod.build_asset_journey("asset-1")

    assert result["transformation"] == {"source": None, "capture": None}
    assert result["milestones"][2]["state"] == "pending"


def test_game_ready_display_fallback_does_not_confirm_trusted_capture(
    tmp_path: Path, monkeypatch
) -> None:
    clip = tmp_path / "fallback.webm"
    clip.write_bytes(b"webm")
    monkeypatch.setattr(
        journey_mod.register_mod,
        "get_asset",
        lambda _id: {"id": "asset-1", "display_name": "Asset One"},
    )
    monkeypatch.setattr(journey_mod.intake_mod, "list_runs", lambda **_kw: [])
    monkeypatch.setattr(journey_mod.lookdev_mod, "list_outputs", lambda **_kw: [])
    monkeypatch.setattr(
        journey_mod.game_ready_mod,
        "list_elements",
        lambda **_kw: [{
            "id": "gr-fallback",
            "asset_id": "asset-1",
            "kind": "vfx-clip",
            "path": str(clip),
            "lanes": [],
            "meta": {
                "system": "NS_BunnyHop01_Single",
                "variant": "contained",
                "validation": {"ok": True, "frame_count": 120, "duration_seconds": 4.0},
            },
        }],
    )
    monkeypatch.setattr(journey_mod.game_ready_mod, "resolve_safe_file", lambda row: Path(row["path"]))
    monkeypatch.setattr(journey_mod, "_bandit_consumer_receipt", lambda _ids: None)

    result = journey_mod.build_asset_journey("asset-1")

    assert result["transformation"]["capture"]["label"] == "Validated game-ready capture"
    trusted = result["milestones"][2]
    assert trusted["state"] == "pending"
    assert trusted["occurred_at"] is None
    assert trusted["evidence_href"] is None
    assert trusted["detail"] == "No decodable trusted capture recorded"


def test_preview_time_uses_brightest_validation_sample() -> None:
    row = {
        "meta": {
            "frames": 120,
            "validation": {
                "duration_seconds": 4.0,
                "visual_samples": [
                    {"frame": "capture.0000.png", "bright_pixels": 0, "visible_pixels": 0},
                    {"frame": "capture.0060.png", "bright_pixels": 12, "visible_pixels": 23},
                    {"frame": "capture.0119.png", "bright_pixels": 491, "visible_pixels": 782},
                ],
            },
        }
    }

    assert journey_mod._preview_time_seconds(row) == 3.967


def test_featured_outputs_are_eight_distinct_published_systems(tmp_path: Path, monkeypatch) -> None:
    rows = []
    for index in range(10):
        system = f"NS_System_{index:02d}"
        for variant in ("breakout", "contained"):
            path = tmp_path / f"{system}.{variant}.webm"
            path.write_bytes(b"webm")
            rows.append(
                {
                    "id": f"gr-{index}-{variant}",
                    "asset_id": "asset-1",
                    "kind": "vfx-clip",
                    "path": str(path),
                    "lanes": ["slots"],
                    "lane_paths": {"slots": str(path)},
                    "meta": {
                        "system": system,
                        "variant": variant,
                        "validation": {"ok": True, "max_bright_sample_pixels": index + 1},
                    },
                }
            )
    monkeypatch.setattr(journey_mod.game_ready_mod, "resolve_safe_file", lambda row: Path(row["path"]))

    selected = journey_mod._featured_rows(rows)

    assert len(selected) == 8
    assert len({row["meta"]["system"] for row in selected}) == 8
    assert all(row["meta"]["variant"] == "contained" for row in selected)


def test_bandit_receipt_requires_the_exact_delivered_element(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "effect": {
                    "effect_id": "vellum-fireworks-win",
                    "element_id": "gr-selected",
                    "media_url": "/api/games/slots/vfx/gr-selected/file",
                }
            }

    monkeypatch.setattr(journey_mod.httpx, "get", lambda *_args, **_kwargs: Response())

    assert journey_mod._bandit_consumer_receipt({"gr-other"}) is None
    receipt = journey_mod._bandit_consumer_receipt({"gr-selected"})
    assert receipt is not None
    assert receipt["state"] == "consumer-selected"
    assert receipt["element_id"] == "gr-selected"
