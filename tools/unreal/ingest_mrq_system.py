#!/usr/bin/env python3
"""Host-side MRQ pick + lookdev ingest (stdlib only).

PowerShell must not drive curl/python for hero uploads — that hang class burned
hours on Aurora. This script owns:

  pick heroes (or reuse JSON) → copy to stills → store-zip sequence →
  POST ingest-render (each hero × lane) → POST ingest-sequence (lanes=) →
  write --result-json

Progress heartbeats go to Vellum when --job-id is set.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Same directory as this file when staged next to pick_heroes.py
_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from pick_heroes import build_heroes_payload  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _progress(vellum_base: str, job_id: str, message: str) -> None:
    if not vellum_base or not job_id:
        print(message, flush=True)
        return
    print(message, flush=True)
    body = json.dumps({"message": message, "log_tail": ""}).encode("utf-8")
    req = Request(
        f"{vellum_base.rstrip('/')}/api/jobs/{job_id}/progress",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urlopen(req, timeout=5) as resp:
            resp.read()
    except (HTTPError, URLError, TimeoutError, OSError):
        pass


def _post_multipart(
    url: str,
    fields: dict[str, str],
    files: dict[str, Path],
    *,
    timeout: int,
) -> tuple[int, str]:
    boundary = f"----vellum{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for name, path in files.items():
        data = path.read_bytes()
        filename = path.name
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
            ).encode()
        )
        body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        body.extend(data)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    req = Request(url, data=bytes(body), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Content-Length", str(len(body)))
    try:
        with urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")


def _store_zip(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    root = source_dir.resolve()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            zf.write(p, p.relative_to(root).as_posix())


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    vellum = args.vellum_base.rstrip("/")
    lanes = [x.strip() for x in args.lanes.split(",") if x.strip()]
    if not lanes:
        raise ValueError("lanes_required")
    seq_dir = Path(args.seq_dir)
    out_dir = Path(args.out_dir)
    stills_dir = Path(args.stills_dir)
    stills_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    heroes_json = Path(args.heroes_json) if args.heroes_json else out_dir / f"heroes-ingest-{_safe_name(args.system_name)}.json"
    result_path = Path(args.result_json)

    errors: list[str] = []
    uploaded = 0
    still_heroes: list[dict[str, Any]] = []

    def prog(msg: str) -> None:
        _progress(vellum, args.job_id, msg)

    # --- pick / reuse ---
    hero_doc: dict[str, Any] | None = None
    if args.reuse_heroes and heroes_json.is_file():
        try:
            hero_doc = json.loads(heroes_json.read_text(encoding="utf-8"))
            if not hero_doc.get("ok") or not hero_doc.get("heroes"):
                hero_doc = None
            else:
                prog(f"ingest {args.system_name}: reuse heroes")
        except (OSError, json.JSONDecodeError):
            hero_doc = None

    if hero_doc is None:
        prog(f"ingest {args.system_name}: pick heroes")
        hero_doc = build_heroes_payload(
            seq_dir,
            min_rgb=int(args.min_rgb),
            score_budget=int(args.score_budget),
        )
        heroes_json.write_text(json.dumps(hero_doc, indent=2) + "\n", encoding="utf-8")

    if not hero_doc.get("ok") or not hero_doc.get("heroes"):
        err = str(hero_doc.get("error") or "hero_pick_failed")
        errors.append(err)
        out = {
            "ok": False,
            "uploaded": 0,
            "errors": errors,
            "heroes": [],
            "frame_count": int(hero_doc.get("frame_count") or 0),
            "system_name": args.system_name,
            "finished_at": _now(),
        }
        _write_result(result_path, out)
        return out

    prog(f"ingest {args.system_name}: heroes ready ({len(hero_doc['heroes'])})")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = _safe_name(args.system_name)
    for h in hero_doc["heroes"]:
        src = Path(str(h["path"]))
        if not src.is_file():
            errors.append(f"hero_missing:{h.get('role')}")
            continue
        dest = stills_dir / f"{args.asset_id}-{safe}-{h['role']}-{stamp}.png"
        shutil.copy2(src, dest)
        still_heroes.append(
            {
                "role": str(h["role"]),
                "path": str(dest),
                "max_rgb": int(h.get("max_rgb") or 0),
                "bytes": dest.stat().st_size,
            }
        )

    note_prefix = args.note_prefix
    for hero in still_heroes:
        for lane in lanes:
            role = hero["role"]
            prog(f"Ingest render {args.system_name} {role} -> {lane}")
            status, body = _post_multipart(
                f"{vellum}/api/lookdev/ingest-render",
                {
                    "asset_id": args.asset_id,
                    "lane": lane,
                    "system_name": args.system_name,
                    "note": f"{note_prefix} {role} {args.system_name} via mrq-batch",
                },
                {"file": Path(hero["path"])},
                timeout=int(args.render_timeout),
            )
            if status >= 400:
                errors.append(f"ingest_render_failed:{lane}:{status}")
                print(f"WARNING ingest-render {status}: {body[:200]}", flush=True)
                continue
            uploaded += 1

    if seq_dir.is_dir():
        zip_path = out_dir / f"seq-{safe}.zip"
        prog(f"Zip sequence {args.system_name} (store)")
        _store_zip(seq_dir, zip_path)
        lane_csv = ",".join(lanes)
        prog(f"Ingest sequence {args.system_name} -> {lane_csv}")
        status, body = _post_multipart(
            f"{vellum}/api/lookdev/ingest-sequence",
            {
                "asset_id": args.asset_id,
                "lanes": lane_csv,
                "system_name": args.system_name,
                "note": f"{note_prefix} sequence {args.system_name} via mrq-batch",
            },
            {"archive": zip_path},
            timeout=int(args.sequence_timeout),
        )
        if status >= 400:
            errors.append(f"ingest_sequence_failed:{status}")
            print(f"WARNING ingest-sequence {status}: {body[:200]}", flush=True)
        else:
            uploaded += len(lanes)

    out = {
        "ok": uploaded > 0 and not errors,
        "uploaded": uploaded,
        "errors": errors,
        "heroes": still_heroes,
        "frame_count": int(hero_doc.get("frame_count") or 0),
        "system_name": args.system_name,
        "finished_at": _now(),
        # Soft-ok: uploads landed even if one lane warned
        "partial": uploaded > 0 and bool(errors),
    }
    if out["partial"]:
        out["ok"] = True
    _write_result(result_path, out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vellum-base", required=True)
    ap.add_argument("--job-id", default="")
    ap.add_argument("--asset-id", required=True)
    ap.add_argument("--system-name", required=True)
    ap.add_argument("--seq-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--stills-dir", required=True)
    ap.add_argument("--lanes", default="slots,hail-overlay")
    ap.add_argument("--heroes-json", default="")
    ap.add_argument("--result-json", required=True)
    ap.add_argument("--reuse-heroes", action="store_true")
    ap.add_argument("--note-prefix", default="auto Niagara MRQ")
    ap.add_argument("--score-budget", type=int, default=8)
    ap.add_argument("--min-rgb", type=int, default=8)
    ap.add_argument("--render-timeout", type=int, default=180)
    ap.add_argument("--sequence-timeout", type=int, default=900)
    args = ap.parse_args()
    try:
        result = run(args)
    except Exception as exc:  # noqa: BLE001
        payload = {
            "ok": False,
            "uploaded": 0,
            "errors": [f"ingest_exception:{exc}"],
            "heroes": [],
            "frame_count": 0,
            "system_name": args.system_name,
            "finished_at": _now(),
        }
        try:
            _write_result(Path(args.result_json), payload)
        except OSError:
            pass
        print(f"FAIL {exc}", flush=True)
        raise SystemExit(1) from exc
    if not result.get("ok") and not result.get("partial"):
        raise SystemExit(2)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
