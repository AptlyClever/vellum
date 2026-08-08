"""Eidolon renders proxy — flatten batches + file proxy."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from backend import eidolon as eidolon_mod
from backend.main import app


SAMPLE_BATCHES = {
    "schema_version": 1,
    "count": 2,
    "batches": [
        {
            "id": "batch-20260719-063428-2da65e6c",
            "status": "done",
            "brief_version": "zo-zo-zoe-symbols-v1",
            "asset_id": "zo-zo-zoe-symbols",
            "lane": "slots",
            "provider": "openai",
            "created_at": 1784442868.0,
            "updated_at": 1784442996.0,
            "result": {
                "kind": "reel-symbol-set",
                "symbols": {
                    "token_pink": {
                        "filename": "token_pink.png",
                        "width": 256,
                        "height": 256,
                        "provider": "openai",
                        "path": "/app/data/batches/batch-20260719-063428-2da65e6c/texture/token_pink.png",
                    }
                },
            },
        },
        {
            "id": "batch-20260717-073743-d65d13b6",
            "status": "done",
            "asset_id": "hot-keys-bezel",
            "lane": "slots",
            "provider": "derive",
            "created_at": 1784270000.0,
            "result": {
                "kind": "bezel-plate-set",
                "plates": {
                    "reel-frame": {
                        "filename": "reel-frame.png",
                        "role": "reel-frame",
                        "width": 1536,
                        "height": 815,
                        "provider": "derive",
                    }
                },
            },
        },
    ],
}


def test_flatten_batch_symbols_and_plates():
    items = eidolon_mod.flatten_batch(SAMPLE_BATCHES["batches"][0])
    assert len(items) == 1
    row = items[0]
    assert row["asset_name"] == "zo-zo-zoe-symbols"
    assert row["label"] == "token_pink"
    assert row["resolution"] == "256×256"
    assert row["batch_id"] == "batch-20260719-063428-2da65e6c"
    assert row["filename"] == "token_pink.png"
    assert "/api/eidolon/renders/" in row["file_url"]

    plates = eidolon_mod.flatten_batch(SAMPLE_BATCHES["batches"][1])
    assert plates[0]["label"] == "reel-frame"
    assert plates[0]["resolution"] == "1536×815"


def test_flatten_sprite_sheet_dims_from_grid():
    batch = {
        "id": "batch-20260716-231328-1295c30b",
        "status": "preview",
        "asset_id": "hot-keys-win-sprites",
        "created_at": 1784100000.0,
        "result": {
            "kind": "sprite-sheet-set",
            "sheets": {
                "float-numerals": {
                    "filename": "float-numerals.sprite-sheet.png",
                    "role": "float-numerals",
                    "cols": 5,
                    "rows": 2,
                    "cell_px": 128,
                }
            },
        },
    }
    items = eidolon_mod.flatten_batch(batch)
    assert items[0]["width"] == 640
    assert items[0]["height"] == 256
    assert items[0]["resolution"] == "640×256"


def test_list_renders_api(monkeypatch):
    def fake_get(url, **kwargs):
        assert url.endswith("/api/batches")
        return httpx.Response(200, json=SAMPLE_BATCHES)

    monkeypatch.setattr(eidolon_mod.httpx, "get", fake_get)
    monkeypatch.setenv("EIDOLON_BASE_URL", "http://eidolon.test")

    client = TestClient(app)
    res = client.get("/api/eidolon/renders?limit=10")
    assert res.status_code == 200
    body = res.json()
    assert body["collection"] == "Eidolon Renders"
    assert body["total"] == 2
    assert body["count"] == 2
    assert body["items"][0]["asset_name"] == "zo-zo-zoe-symbols"
    assert body["items"][0]["rendered_at"]


def test_list_renders_unreachable(monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(eidolon_mod.httpx, "get", boom)
    client = TestClient(app)
    res = client.get("/api/eidolon/renders")
    assert res.status_code == 502


def test_render_file_proxy(monkeypatch):
    png = b"\x89PNG\r\n\x1a\nfake"

    def fake_get(url, **kwargs):
        assert "batch-20260719-063428-2da65e6c" in url
        assert url.endswith("/artifacts/token_pink.png")
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    monkeypatch.setattr(eidolon_mod.httpx, "get", fake_get)
    monkeypatch.setenv("EIDOLON_BASE_URL", "http://eidolon.test")

    client = TestClient(app)
    res = client.get(
        "/api/eidolon/renders/batch-20260719-063428-2da65e6c/token_pink.png/file"
    )
    assert res.status_code == 200
    assert res.content == png
    assert res.headers["content-type"].startswith("image/png")


def test_render_file_rejects_bad_ids():
    client = TestClient(app)
    assert (
        client.get("/api/eidolon/renders/not-a-batch/token.png/file").status_code == 400
    )
    assert (
        client.get(
            "/api/eidolon/renders/batch-20260719-063428-2da65e6c/bad name.png/file"
        ).status_code
        == 400
    )
