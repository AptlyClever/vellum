from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_inventory_helpers():
    path = Path(__file__).resolve().parents[1] / "tools" / "unreal" / "vellum_capture.py"
    spec = importlib.util.spec_from_file_location("vellum_capture_inventory", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pick_systems_zero_means_entire_pack_dropping_loop_siblings() -> None:
    mod = _load_inventory_helpers()
    assets = [
        SimpleNamespace(asset_name="NS_PeonyShell01_Loop"),
        SimpleNamespace(asset_name="NS_PeonyShell01_Single"),
        SimpleNamespace(asset_name="NS_Fountain01_Single"),
        SimpleNamespace(asset_name="NS_OnlyLoop_Loop"),
    ]
    picked = mod._pick_systems(assets, 0)
    names = [a.asset_name for a in picked]
    assert "NS_PeonyShell01_Single" in names
    assert "NS_Fountain01_Single" in names
    assert "NS_OnlyLoop_Loop" in names
    assert "NS_PeonyShell01_Loop" not in names
    assert len(names) == 3


def test_pick_systems_positive_still_limits() -> None:
    mod = _load_inventory_helpers()
    assets = [
        SimpleNamespace(asset_name=f"NS_Shell{i:02d}_Single") for i in range(10)
    ]
    picked = mod._pick_systems(assets, 2)
    assert len(picked) == 2
