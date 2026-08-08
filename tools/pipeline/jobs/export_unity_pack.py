"""Conversion Factory job: Unpark Unity tier intake and extract .unitypackage files.

Unity packages (.unitypackage) are tar.gz archives containing GUID folders with `asset` binaries
and `pathname` text files specifying the original project relative path.
"""

from __future__ import annotations

import tarfile
from pathlib import Path
from typing import Any


def unpack_unitypackage(unitypackage_path: Path, output_dir: Path) -> dict[str, Any]:
    """Unpack a .unitypackage tar.gz archive into its original file hierarchy."""
    output_dir.mkdir(parents=True, exist_ok=True)
    if not unitypackage_path.is_file():
        raise FileNotFoundError(str(unitypackage_path))

    extracted = []
    errors = []

    with tarfile.open(unitypackage_path, "r:gz") as tar:
        # Group tar members by top-level GUID folder
        guid_members: dict[str, dict[str, tarfile.TarInfo]] = {}
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if len(parts) >= 2:
                guid, file_name = parts[0], parts[1]
                guid_members.setdefault(guid, {})[file_name] = member

        for guid, files in guid_members.items():
            if "pathname" in files and "asset" in files:
                try:
                    pathname_file = tar.extractfile(files["pathname"])
                    if not pathname_file:
                        continue
                    relative_path_str = pathname_file.read().decode("utf-8", errors="ignore").strip()
                    # Clean relative path (remove leading Assets/ if present)
                    rel_path = Path(relative_path_str)
                    if rel_path.parts and rel_path.parts[0].lower() == "assets":
                        rel_path = Path(*rel_path.parts[1:])

                    dest_file = output_dir / rel_path
                    dest_file.parent.mkdir(parents=True, exist_ok=True)

                    asset_file = tar.extractfile(files["asset"])
                    if asset_file:
                        dest_file.write_bytes(asset_file.read())
                        extracted.append({
                            "guid": guid,
                            "path": str(dest_file),
                            "relative_path": str(rel_path),
                            "bytes": dest_file.stat().st_size,
                        })
                except Exception as exc:
                    errors.append(f"guid:{guid}:{exc}")

    return {
        "job": "export-unity-pack",
        "package_path": str(unitypackage_path),
        "output_dir": str(output_dir),
        "extracted_count": len(extracted),
        "extracted": extracted,
        "errors": errors,
    }
