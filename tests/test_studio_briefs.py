from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_api_studio_briefs_bandit() -> None:
    client = TestClient(app)
    res = client.get("/api/studio/briefs", params={"lane": "bandit"})
    assert res.status_code == 200
    data = res.json()
    assert data["schema_version"] == 1
    assert data["lane"] == "bandit"
    assert "1st" in data["priority"]
    assert "elements" in data


def test_api_studio_briefs_threshold_affairs() -> None:
    client = TestClient(app)
    res = client.get("/api/studio/briefs", params={"lane": "godot-threshold-affairs"})
    assert res.status_code == 200
    data = res.json()
    assert data["lane"] == "godot-threshold-affairs"
    assert "2nd" in data["priority"]
