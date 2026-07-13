from __future__ import annotations

import io
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


def test_ingest_sequence_zip(tmp_path: Path, monkeypatch) -> None:
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
