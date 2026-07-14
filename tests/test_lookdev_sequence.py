from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.register import ensure_register


def _png_bytes(color=(40, 80, 200)) -> bytes:
    img = Image.new("RGB", (32, 32), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _seed(tmp_path: Path, monkeypatch) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    reg = tmp_path / "register.yaml"
    derived = tmp_path / "derived.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(vault))
    monkeypatch.setenv("VELLUM_DERIVED_PATH", str(derived))
    monkeypatch.delenv("VELLUM_VAULT_REGISTER_PATH", raising=False)
    monkeypatch.delenv("VELLUM_VAULT_DERIVED_PATH", raising=False)
    ensure_register(force_reseed=True)
    return vault


def test_ingest_sequence_zip(tmp_path: Path, monkeypatch) -> None:
    vault = _seed(tmp_path, monkeypatch)
    from backend.main import app

    client = TestClient(app)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("frame_0001.png", _png_bytes())
        zf.writestr("frame_0002.png", _png_bytes((200, 40, 40)))
    buf.seek(0)
    res = client.post(
        "/api/lookdev/ingest-sequence",
        data={
            "asset_id": "fireworks-vol-1-niagara",
            "lane": "slots",
            "system_name": "NS_Test",
            "note": "unit",
        },
        files={"archive": ("seq.zip", buf.getvalue(), "application/zip")},
    )
    assert res.status_code == 200, res.text
    body = res.json()["output"]
    assert body["kind"] == "niagara-sequence"
    assert body["frame_count"] == 2
    assert Path(body["path"]).is_dir()
    assert "sequences" in body["path"]
    assert (vault / "05-derived-renders" / "sequences").exists()


def test_ingest_sequence_multi_lane_one_write(tmp_path: Path, monkeypatch) -> None:
    vault = _seed(tmp_path, monkeypatch)
    from backend.main import app

    client = TestClient(app)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("frame_0001.png", _png_bytes())
        zf.writestr("frame_0002.png", _png_bytes((10, 220, 40)))
    buf.seek(0)
    res = client.post(
        "/api/lookdev/ingest-sequence",
        data={
            "asset_id": "fireworks-vol-1-niagara",
            "lanes": "slots,hail-overlay",
            "system_name": "NS_Multi",
            "note": "multi",
        },
        files={"archive": ("seq.zip", buf.getvalue(), "application/zip")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["outputs"]) == 2
    paths = {o["path"] for o in body["outputs"]}
    assert len(paths) == 1  # shared on-disk tree
    shared = Path(next(iter(paths)))
    assert shared.is_dir()
    assert len(list(shared.glob("*.png"))) == 2
    lanes = {o["lane"] for o in body["outputs"]}
    assert lanes == {"slots", "hail-overlay"}
    lookdev = Path(body["outputs"][0]["lookdev_path"])
    assert lookdev.is_dir()
    # Prefer hardlink when same filesystem (dev/inode match).
    derived_frame = next(shared.glob("*.png"))
    look_frame = lookdev / derived_frame.name
    assert look_frame.is_file()
    try:
        assert os.stat(derived_frame).st_ino == os.stat(look_frame).st_ino
    except (AttributeError, OSError):
        pass  # platforms without meaningful hardlink identity
