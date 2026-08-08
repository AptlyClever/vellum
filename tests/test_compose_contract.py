from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_vault_catalog_permission_init_is_narrow_and_required() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    init = services["vault-permissions"]
    command = " ".join(init["command"])

    assert init["user"] == "0:0"
    assert "02-index/derived-outputs.yaml" in command
    assert "chown 1000:1000" in command
    assert "-R" not in command, "Never recursively change factory-owned vault permissions"
    assert services["app"]["depends_on"]["vault-permissions"]["condition"] == "service_completed_successfully"
    assert services["worker"]["depends_on"]["vault-permissions"]["condition"] == "service_completed_successfully"
