"""Visual Research collection — storage, API, Bandit read-only contract."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from backend import mneme as mneme_mod
from backend import research as research_mod

WRITE_TOKEN = "test-research-write-token"


def _png_bytes(width: int = 2, height: int = 2) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _jpg_bytes() -> bytes:
    # Minimal JFIF-ish JPEG that Pillow can open (1x1).
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
        "070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c"
        "1c2837292c30313434341f27393d38323c2e333432ffdb0043010909090c0b0c180d"
        "0d1832211c2132323232323232323232323232323232323232323232323232323232"
        "323232323232323232323232323232323232323232ffc00011080001000103011100"
        "021101031101ffc40014000100000000000000000000000000000000ffc400141001"
        "00000000000000000000000000000000ffda000c0301000210031000003f00bf80ffd9"
    )


def _gif_bytes() -> bytes:
    # 1x1 GIF89a
    return (
        b"GIF89a"
        b"\x01\x00\x01\x00\x00\x00\x00"
        b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00;"
    )


def _webp_bytes() -> bytes:
    # Tiny lossy-ish WebP via VP8L header-free RIFF wrapper: use a known minimal WebP.
    # 1x1 white pixel WebP (VP8L).
    return bytes.fromhex(
        "52494646240a0000574542505650384c170a00002f"
        "c0ffff0f00ffff0f00ffff0f00ffff0f00ffff0f00"
    )


def _svg_bytes(extra: str = "") -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
        f'<rect width="40" height="40" fill="#336699"/>{extra}</svg>'
    ).encode("utf-8")


def _seed(tmp_path: Path, monkeypatch, *, token: str = WRITE_TOKEN) -> Path:
    vault = tmp_path / "vault"
    catalog = tmp_path / "visual-research.yaml"
    mirror = vault / "02-index" / "visual-research.yaml"
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(vault))
    monkeypatch.setenv("VELLUM_RESEARCH_PATH", str(catalog))
    monkeypatch.setenv("VELLUM_VAULT_RESEARCH_PATH", str(mirror))
    monkeypatch.setenv("VELLUM_RESEARCH_WRITE_TOKEN", token)
    monkeypatch.setenv("VELLUM_PUBLIC_BASE_URL", "http://vellum.test")
    monkeypatch.setenv("MNEME_BASE_URL", "http://mneme.test")
    monkeypatch.setenv("MNEME_DEFAULT_PROJECT_ID", "bandit")
    monkeypatch.setenv("MNEME_WRITE_TOKEN", "test-mneme-write-token")
    # Isolate unrelated paths used if main app imports touch them
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(tmp_path / "register.yaml"))
    monkeypatch.setenv("VELLUM_DERIVED_PATH", str(tmp_path / "derived.yaml"))
    monkeypatch.setenv("VELLUM_INTAKE_RUNS_PATH", str(tmp_path / "intake.yaml"))
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("VELLUM_ATTACHMENTS_PATH", str(tmp_path / "attachments.yaml"))
    monkeypatch.setenv("VELLUM_GAME_READY_PATH", str(tmp_path / "game-ready.yaml"))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    monkeypatch.delenv("VELLUM_VAULT_DERIVED_PATH", raising=False)
    monkeypatch.delenv("VELLUM_VAULT_INTAKE_RUNS_PATH", raising=False)
    research_mod.clear_catalog_cache()
    return vault


def _auth_headers(token: str = WRITE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_ingest_all_supported_formats(tmp_path: Path, monkeypatch) -> None:
    vault = _seed(tmp_path, monkeypatch)
    samples = [
        ("shot.png", _png_bytes(), "png"),
        ("shot.jpg", _jpg_bytes(), "jpg"),
        ("shot.gif", _gif_bytes(), "gif"),
        ("shot.webp", _webp_bytes(), "webp"),
        ("shot.svg", _svg_bytes(), "svg"),
    ]
    for name, data, fmt in samples:
        item = research_mod.ingest_image(
            data=data,
            filename=name,
            title=f"Title {fmt}",
            source_url="https://example.com/ref",
            caption="cap",
            tags=["ui", fmt],
            rights="research-reference",
            attribution="Example",
        )
        assert item["asset_type"] == "visual-research"
        assert item["collection"] == "Visual Research"
        assert item["format"] == fmt
        assert item["source_url"] == "https://example.com/ref"
        assert item["captured_at"]
        assert Path(vault / "07-visual-research" / item["id"]).is_dir()
        raw = research_mod.get_raw_item(item["id"])
        assert raw is not None
        assert Path(raw["path"]).is_file()


def test_search_and_distinguish_from_game_assets(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch)
    research_mod.ingest_image(
        data=_png_bytes(),
        filename="hud.png",
        title="Neon HUD",
        tags=["hud", "bandit"],
        source_url="https://example.com/hud",
    )
    research_mod.ingest_image(
        data=_svg_bytes(),
        filename="diagram.svg",
        title="Flow diagram",
        tags=["diagram"],
        source_url="https://example.com/flow",
    )
    listed = research_mod.list_items(q="neon")
    assert listed["total"] == 1
    assert listed["items"][0]["title"] == "Neon HUD"
    assert listed["items"][0]["asset_type"] == "visual-research"
    by_tag = research_mod.list_items(tag="diagram")
    assert by_tag["total"] == 1
    by_fmt = research_mod.list_items(format="svg")
    assert by_fmt["total"] == 1


def test_catalog_survives_cache_clear_and_vault_mirror(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _seed(tmp_path, monkeypatch)
    item = research_mod.ingest_image(
        data=_png_bytes(),
        filename="keep.png",
        title="Persists",
        source_url="https://example.com/p",
    )
    mirror = vault / "02-index" / "visual-research.yaml"
    assert mirror.is_file()
    assert "Persists" in mirror.read_text(encoding="utf-8")

    research_mod.clear_catalog_cache()
    again = research_mod.get_item(item["id"])
    assert again is not None
    assert again["title"] == "Persists"
    path = research_mod.resolve_safe_file(research_mod.get_raw_item(item["id"]))
    assert path.is_file()


def test_rejects_invalid_and_unsafe_content(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch)
    try:
        research_mod.ingest_image(data=b"not-an-image", filename="x.png")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert str(exc) in {"content_mismatch", "unsupported_image"}

    try:
        research_mod.ingest_image(
            data=_svg_bytes('<script>alert(1)</script>'),
            filename="bad.svg",
        )
        assert False, "expected unsafe_svg"
    except ValueError as exc:
        assert str(exc) == "unsafe_svg"


def test_path_jail(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch)
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png_bytes())
    try:
        research_mod.resolve_safe_file({"path": str(outside)})
        assert False, "expected path_outside_vault"
    except PermissionError as exc:
        assert str(exc) == "path_outside_vault"


def test_api_upload_list_file_and_bandit_readonly(
    tmp_path: Path, monkeypatch
) -> None:
    _seed(tmp_path, monkeypatch)
    from backend.main import app

    client = TestClient(app)

    # Bandit-style: no token → cannot upload
    denied = client.post(
        "/api/visual-research",
        files={"file": ("hud.png", _png_bytes(), "image/png")},
        data={"title": "Denied", "source_url": "https://example.com/x"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "visual_research_read_only"

    # Authorized upload
    ok = client.post(
        "/api/visual-research",
        headers=_auth_headers(),
        files={"file": ("hud.png", _png_bytes(), "image/png")},
        data={
            "title": "Bandit HUD ref",
            "source_url": "https://example.com/hud",
            "caption": "scoreboard",
            "tags": "ui,hud",
            "rights": "research-reference",
            "attribution": "Example",
        },
    )
    assert ok.status_code == 200, ok.text
    item = ok.json()["item"]
    rid = item["id"]
    assert item["asset_type"] == "visual-research"
    assert item["format"] == "png"
    assert item["source_url"] == "https://example.com/hud"

    listed = client.get("/api/visual-research", params={"q": "HUD"})
    assert listed.status_code == 200
    body = listed.json()
    assert body["collection"] == "Visual Research"
    assert body["total"] >= 1
    assert any(i["id"] == rid for i in body["items"])

    got = client.get(f"/api/visual-research/{rid}")
    assert got.status_code == 200
    assert got.json()["title"] == "Bandit HUD ref"

    file_res = client.get(f"/api/visual-research/{rid}/file")
    assert file_res.status_code == 200
    assert file_res.content.startswith(b"\x89PNG")
    assert "image/png" in (file_res.headers.get("content-type") or "")

    # Bandit cannot patch/delete
    patch_denied = client.patch(
        f"/api/visual-research/{rid}",
        json={"title": "Hacked"},
    )
    assert patch_denied.status_code == 403
    assert patch_denied.json()["detail"] == "visual_research_read_only"

    del_denied = client.delete(f"/api/visual-research/{rid}")
    assert del_denied.status_code == 403
    assert del_denied.json()["detail"] == "visual_research_read_only"

    # Wrong token also denied
    wrong = client.delete(
        f"/api/visual-research/{rid}",
        headers=_auth_headers("wrong-token"),
    )
    assert wrong.status_code == 403

    # Authorized patch + delete
    patched = client.patch(
        f"/api/visual-research/{rid}",
        headers=_auth_headers(),
        json={"title": "Updated HUD", "tags": ["ui"]},
    )
    assert patched.status_code == 200
    assert patched.json()["item"]["title"] == "Updated HUD"

    deleted = client.delete(
        f"/api/visual-research/{rid}",
        headers=_auth_headers(),
    )
    assert deleted.status_code == 200
    assert client.get(f"/api/visual-research/{rid}").status_code == 404


def test_missing_write_token_blocks_mutations(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch, token="")
    from backend.main import app

    client = TestClient(app)
    res = client.post(
        "/api/visual-research",
        headers=_auth_headers("anything"),
        files={"file": ("a.png", _png_bytes(), "image/png")},
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "visual_research_read_only"


def test_bundle_ingest_links_vellum_and_mneme_by_project(
    tmp_path: Path, monkeypatch
) -> None:
    _seed(tmp_path, monkeypatch)
    captured: dict = {}

    def fake_create_document(**kwargs):
        captured.update(kwargs)
        return {
            "id": "doc-bandit-hud",
            "project_id": kwargs["project_id"],
            "title": kwargs["title"],
            "tags": kwargs["tags"],
        }

    monkeypatch.setattr(mneme_mod, "create_document", fake_create_document)
    from backend.main import app

    client = TestClient(app)
    response = client.post(
        "/api/visual-research/bundles",
        headers=_auth_headers(),
        files={"file": ("hud.png", _png_bytes(), "image/png")},
        data={
            "project_id": "lcard",
            "title": "HUD research",
            "source_url": "https://example.com/hud",
            "body": "# Captured page\n\nUseful source text.",
            "tags": "ui,hud",
            "author": "Example Author",
        },
    )
    assert response.status_code == 200, response.text
    item = response.json()["item"]
    assert item["project_id"] == "lcard"
    assert item["mneme_document_id"] == "doc-bandit-hud"
    assert item["mneme_document_url"] == (
        "http://mneme.test/api/documents/doc-bandit-hud"
    )
    assert captured["project_id"] == "lcard"
    assert "Useful source text." in captured["body"]
    assert f"vellum-{item['id']}" in captured["tags"]
    assert (
        f"http://vellum.test/api/visual-research/{item['id']}/file"
        in captured["body"]
    )

    listed = client.get(
        "/api/visual-research", params={"project_id": "LCARD"}
    ).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == item["id"]
    assert client.get(
        "/api/visual-research", params={"project_id": "bandit"}
    ).json()["total"] == 0


def test_bundle_uses_default_project_and_reconciles_ambiguous_create(
    tmp_path: Path, monkeypatch
) -> None:
    _seed(tmp_path, monkeypatch)
    seen: dict = {}

    def ambiguous(**kwargs):
        seen.update(kwargs)
        raise mneme_mod.MnemeAmbiguousError("timeout")

    def reconcile(tag, *, project_id, timeout=10.0):
        assert tag.startswith("vellum-vr-")
        assert project_id == "bandit"
        return {"id": "doc-reconciled", "tags": [tag], "project_id": project_id}

    monkeypatch.setattr(mneme_mod, "create_document", ambiguous)
    monkeypatch.setattr(mneme_mod, "find_document_by_tag", reconcile)
    from backend.main import app

    client = TestClient(app)
    response = client.post(
        "/api/visual-research/bundles",
        headers=_auth_headers(),
        files={"file": ("diagram.svg", _svg_bytes(), "image/svg+xml")},
        data={
            "source_url": "https://example.com/diagram",
            "body": "Captured diagram explanation.",
        },
    )
    assert response.status_code == 200, response.text
    item = response.json()["item"]
    assert item["project_id"] == "bandit"
    assert item["mneme_document_id"] == "doc-reconciled"
    assert seen["project_id"] == "bandit"


def test_bundle_validation_and_mneme_failure_roll_back_vellum(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _seed(tmp_path, monkeypatch)
    from backend.main import app

    client = TestClient(app)
    denied = client.post(
        "/api/visual-research/bundles",
        files={"file": ("a.png", _png_bytes(), "image/png")},
        data={
            "source_url": "https://example.com/a",
            "body": "captured source",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "visual_research_read_only"

    invalid_project = client.post(
        "/api/visual-research/bundles",
        headers=_auth_headers(),
        files={"file": ("a.png", _png_bytes(), "image/png")},
        data={
            "project_id": "not a project",
            "source_url": "https://example.com/a",
            "body": "text",
        },
    )
    assert invalid_project.status_code == 400
    assert invalid_project.json()["detail"] == "project_id_invalid"

    missing_text = client.post(
        "/api/visual-research/bundles",
        headers=_auth_headers(),
        files={"file": ("a.png", _png_bytes(), "image/png")},
        data={"source_url": "https://example.com/a", "body": "   "},
    )
    assert missing_text.status_code == 400
    assert missing_text.json()["detail"] == "source_text_required"

    missing_source = client.post(
        "/api/visual-research/bundles",
        headers=_auth_headers(),
        files={"file": ("a.png", _png_bytes(), "image/png")},
        data={"source_url": "   ", "body": "captured source"},
    )
    assert missing_source.status_code == 400
    assert missing_source.json()["detail"] == "source_url_required"

    def rejected(**_kwargs):
        raise mneme_mod.MnemeError("mneme_http_403")

    monkeypatch.setattr(mneme_mod, "create_document", rejected)
    failed = client.post(
        "/api/visual-research/bundles",
        headers=_auth_headers(),
        files={"file": ("a.png", _png_bytes(), "image/png")},
        data={
            "source_url": "https://example.com/a",
            "body": "captured source",
        },
    )
    assert failed.status_code == 502
    assert failed.json()["detail"] == "mneme_ingest_failed"
    assert research_mod.list_items()["total"] == 0
    research_root = vault / "07-visual-research"
    assert not research_root.exists() or not any(research_root.iterdir())


def test_mneme_client_sends_supported_multipart_contract(
    tmp_path: Path, monkeypatch
) -> None:
    _seed(tmp_path, monkeypatch)
    captured: dict = {}

    def fake_post(url, *, headers, files, timeout):
        captured.update(
            {"url": url, "headers": headers, "files": files, "timeout": timeout}
        )
        return httpx.Response(
            201,
            json={"id": "doc-client-test"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    result = mneme_mod.create_document(
        title="Research title",
        project_id="proscenium",
        source_url="https://example.com/source",
        captured_at="2026-07-18T20:00:00+00:00",
        tags=["visual-research", "vellum-vr-test"],
        body="# Extracted text",
        author="Author",
        publisher="Publisher",
    )
    assert result["id"] == "doc-client-test"
    assert captured["url"] == "http://mneme.test/api/documents"
    assert captured["headers"]["Authorization"] == "Bearer test-mneme-write-token"
    metadata = json.loads(captured["files"]["metadata"][1])
    assert metadata["project_id"] == "proscenium"
    assert metadata["source_url"] == "https://example.com/source"
    assert captured["files"]["body"][1] == "# Extracted text"
