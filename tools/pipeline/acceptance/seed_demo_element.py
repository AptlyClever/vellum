"""Seed a placeholder game-ready element for fireworks (dev catalog)."""
from __future__ import annotations

import os
from pathlib import Path

from backend import game_ready as gr

ROOT = Path(__file__).resolve().parents[3]
vault = Path(os.environ.get("VELLUM_VAULT_ROOT", "")).expanduser()
if not str(vault):
    vault = ROOT / "data" / "vault-dev"
vault.mkdir(parents=True, exist_ok=True)
os.environ["VELLUM_VAULT_ROOT"] = str(vault)
os.environ["VELLUM_GAME_READY_PATH"] = str(ROOT / "data" / "game-ready.yaml")

src = vault / "05-derived-renders" / "game-ready" / "_seed"
src.mkdir(parents=True, exist_ok=True)
clip = src / "NS_ChrysanthemumShell01_Single.webm"
if not clip.exists():
    clip.write_bytes(b"WEBMSEED")

row = gr.register_element(
    asset_id="fireworks-vol-1-niagara",
    kind="vfx-clip",
    path=clip,
    pack="FireworksV1",
    note="seed placeholder until factory bake lands real alpha WebM",
)
pub = gr.publish_to_lane(row["id"], "slots")
print(f"seeded {row['id']} lane_path={pub.get('lane_paths', {}).get('slots')}")
