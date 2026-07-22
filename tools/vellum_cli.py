"""Vellum Developer CLI utility (vellum pull).

Allows game developers working in Godot or other engines to fetch published game-ready assets
directly from Vellum into project directories.

Usage:
  python tools/vellum_cli.py pull --lane godot-field-ops --target ./res/assets/vellum/
  python tools/vellum_cli.py pull --lane godot-threshold-affairs --target ./res/assets/vellum/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


DEFAULT_VELLUM_API = "http://192.168.68.93:8770"


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "VellumCLI/1.0"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_file(url: str, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "VellumCLI/1.0"})
    with urllib.request.urlopen(req) as resp, open(dest_path, "wb") as out:
        out.write(resp.read())


def cmd_pull(lane: str, target_dir: Path, base_url: str, kind: str | None = None) -> int:
    api_base = os.environ.get("VELLUM_API_URL", base_url).rstrip("/")
    url = f"{api_base}/api/game-ready/elements?lane={lane}"
    if kind:
        url += f"&kind={kind}"

    print(f"[VellumCLI] Querying catalog for lane '{lane}' at {url}...")
    try:
        data = fetch_json(url)
    except Exception as exc:
        print(f"[VellumCLI] Error fetching catalog: {exc}")
        return 1

    elements = data.get("elements", [])
    print(f"[VellumCLI] Found {len(elements)} published element(s) for lane '{lane}'.")

    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0

    for elem in elements:
        eid = elem.get("id")
        kind_str = elem.get("kind", "file")
        filename = Path(elem.get("path", "asset")).name
        file_url = f"{api_base}/api/game-ready/elements/{eid}/file"
        dest_file = target_dir / kind_str / filename

        print(f" -> Downloading {kind_str}/{filename}...")
        try:
            download_file(file_url, dest_file)
            downloaded += 1
        except Exception as exc:
            print(f"    [Warning] Failed to download {eid}: {exc}")

    print(f"[VellumCLI] Complete. Downloaded {downloaded} file(s) into {target_dir.resolve()}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Vellum Developer CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pull_parser = subparsers.add_parser("pull", help="Pull published assets for a target game lane")
    pull_parser.add_argument("--lane", required=True, help="Target game lane (e.g. godot-field-ops, godot-threshold-affairs)")
    pull_parser.add_argument("--target", type=Path, required=True, help="Target directory (e.g. ./res/assets/vellum/)")
    pull_parser.add_argument("--kind", help="Optional asset kind filter (model-gltf, texture, audio, vfx-clip)")
    pull_parser.add_argument("--base-url", default=DEFAULT_VELLUM_API, help="Vellum server API base URL")

    args = parser.parse_args()

    if args.command == "pull":
        sys.exit(cmd_pull(args.lane, args.target, args.base_url, args.kind))


if __name__ == "__main__":
    main()
