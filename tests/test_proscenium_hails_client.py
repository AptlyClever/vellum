from __future__ import annotations

import json
from unittest.mock import MagicMock

from tools.proscenium_hails_client import trigger_game_hail


def test_trigger_game_hail_bandit(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        res = MagicMock()
        res.read.return_value = b'{"status": "shown"}'
        res.__enter__ = lambda self: self
        res.__exit__ = lambda *args: None
        return res

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    res = trigger_game_hail(
        "bandit",
        "BIG_WIN",
        "BIG WIN!",
        "500 Credits Won",
        base_url="http://fake-proscenium:8788",
    )
    assert res["ok"] is True
    assert res["target"] == "arcade"
    assert captured["url"] == "http://fake-proscenium:8788/api/presentation/products/bandit/show"
    assert captured["body"]["delivery_target_id"] == "arcade"


def test_trigger_game_hail_threshold_affairs(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        res = MagicMock()
        res.read.return_value = b'{"status": "shown"}'
        res.__enter__ = lambda self: self
        res.__exit__ = lambda *args: None
        return res

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    res = trigger_game_hail(
        "godot-threshold-affairs",
        "EVIDENCE_COLLECTED",
        "EVIDENCE UNLOCKED",
        "Motel Keycard #204",
        delivery_target_id="operator_desk",
        base_url="http://fake-proscenium:8788",
    )
    assert res["ok"] is True
    assert res["target"] == "operator_desk"
    assert captured["body"]["payload"]["event_type"] == "EVIDENCE_COLLECTED"
