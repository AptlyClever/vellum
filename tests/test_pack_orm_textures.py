from __future__ import annotations

from pathlib import Path
from PIL import Image

from tools.pipeline.jobs.pack_orm_textures import pack_orm_image, process_texture_dir_for_orm


def test_pack_orm_image(tmp_path: Path) -> None:
    ao_file = tmp_path / "T_Wall_AO.png"
    rough_file = tmp_path / "T_Wall_Roughness.png"
    metal_file = tmp_path / "T_Wall_Metallic.png"
    out_file = tmp_path / "T_Wall_ORM.png"

    # Create 64x64 sample channel images
    Image.new("L", (64, 64), 200).save(ao_file)
    Image.new("L", (64, 64), 100).save(rough_file)
    Image.new("L", (64, 64), 50).save(metal_file)

    res_file = pack_orm_image(ao_file, rough_file, metal_file, out_file)
    assert res_file.is_file()

    with Image.open(res_file) as img:
        assert img.size == (64, 64)
        assert img.mode == "RGB"
        r, g, b = img.getpixel((0, 0))
        assert r == 200  # AO
        assert g == 100  # Roughness
        assert b == 50   # Metallic


def test_process_texture_dir_for_orm(tmp_path: Path) -> None:
    in_dir = tmp_path / "input"
    out_dir = tmp_path / "output"
    in_dir.mkdir()

    Image.new("L", (32, 32), 255).save(in_dir / "Prop_AO.png")
    Image.new("L", (32, 32), 128).save(in_dir / "Prop_Roughness.png")

    res = process_texture_dir_for_orm(in_dir, out_dir)
    assert res["packed_count"] == 1
    assert (out_dir / "Prop_ORM.png").is_file()
