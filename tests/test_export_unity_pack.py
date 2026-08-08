from __future__ import annotations

import io
import tarfile
from pathlib import Path

from tools.pipeline.jobs.export_unity_pack import unpack_unitypackage


def test_unpack_unitypackage(tmp_path: Path) -> None:
    pkg_file = tmp_path / "sample.unitypackage"
    out_dir = tmp_path / "extracted"

    # Build a dummy .unitypackage tar.gz archive
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        # Add pathname info
        pathname_data = b"Assets/Props/Chair.fbx\n"
        ti_path = tarfile.TarInfo(name="guid123/pathname")
        ti_path.size = len(pathname_data)
        tar.addfile(ti_path, io.BytesIO(pathname_data))

        # Add asset binary info
        asset_data = b"FBX_HEADER_DATA"
        ti_asset = tarfile.TarInfo(name="guid123/asset")
        ti_asset.size = len(asset_data)
        tar.addfile(ti_asset, io.BytesIO(asset_data))

    pkg_file.write_bytes(buf.getvalue())

    res = unpack_unitypackage(pkg_file, out_dir)
    assert res["extracted_count"] == 1
    extracted_chair = out_dir / "Props" / "Chair.fbx"
    assert extracted_chair.is_file()
    assert extracted_chair.read_bytes() == b"FBX_HEADER_DATA"
