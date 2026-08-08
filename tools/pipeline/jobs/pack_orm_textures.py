"""Conversion Factory job: Pack Occlusion (R), Roughness (G), and Metallic (B) textures into Godot-compliant ORM texture maps.

Accepts individual texture channel files or matching texture sets and merges them using Pillow.
Output follows Godot 4.x ORMMaterial3D standards.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PIL import Image

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def pack_orm_image(
    ao_path: Path | None,
    roughness_path: Path | None,
    metallic_path: Path | None,
    out_path: Path,
    default_size: tuple[int, int] = (1024, 1024),
) -> Path:
    """Combine AO (R), Roughness (G), Metallic (B) channels into a single ORM RGB image."""
    base_size = default_size
    ref_img = None
    for p in (ao_path, roughness_path, metallic_path):
        if p and p.is_file():
            try:
                with Image.open(p) as img:
                    base_size = img.size
                    ref_img = img
                    break
            except Exception:
                pass

    w, h = base_size

    def _get_channel(path: Path | None, default_val: int, channel_idx: int = 0) -> Image.Image:
        if path and path.is_file():
            try:
                img = Image.open(path).convert("RGB")
                if img.size != (w, h):
                    img = img.resize((w, h), Image.Resampling.BILINEAR)
                channels = img.split()
                return channels[channel_idx]
            except Exception:
                pass
        return Image.new("L", (w, h), default_val)

    # Red = Occlusion (default 255 = no occlusion), Green = Roughness (default 128), Blue = Metallic (default 0)
    r_chan = _get_channel(ao_path, 255, 0)
    g_chan = _get_channel(roughness_path, 128, 0)
    b_chan = _get_channel(metallic_path, 0, 0)

    orm = Image.merge("RGB", (r_chan, g_chan, b_chan))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    orm.save(out_path, format="PNG", optimize=True)
    return out_path


def process_texture_dir_for_orm(input_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Scan input_dir for matching texture channels and emit packed ORM textures into output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    files = list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg"))
    by_stem: dict[str, dict[str, Path]] = {}

    for f in files:
        name_lower = f.stem.lower()
        if name_lower.endswith("_ao") or name_lower.endswith("_occlusion") or name_lower.endswith("_ambientocclusion"):
            base = f.stem.rsplit("_", 1)[0]
            by_stem.setdefault(base, {})["ao"] = f
        elif name_lower.endswith("_roughness") or name_lower.endswith("_rough") or name_lower.endswith("_r"):
            base = f.stem.rsplit("_", 1)[0]
            by_stem.setdefault(base, {})["roughness"] = f
        elif name_lower.endswith("_metallic") or name_lower.endswith("_metal") or name_lower.endswith("_m"):
            base = f.stem.rsplit("_", 1)[0]
            by_stem.setdefault(base, {})["metallic"] = f

    packed = []
    for stem, channels in by_stem.items():
        if len(channels) >= 2:  # Requires at least 2 distinct channels to pack
            out_file = output_dir / f"{stem}_ORM.png"
            pack_orm_image(
                channels.get("ao"),
                channels.get("roughness"),
                channels.get("metallic"),
                out_file,
            )
            packed.append(
                {
                    "stem": stem,
                    "output": str(out_file),
                    "channels_found": list(channels.keys()),
                    "bytes": out_file.stat().st_size if out_file.exists() else 0,
                }
            )

    return {
        "job": "pack-orm-textures",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "packed_count": len(packed),
        "packed": packed,
    }
