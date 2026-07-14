#!/usr/bin/env python3
"""Stage an Unreal Content folder from the UE host into the Vellum vault.

Runs on Aurora (Windows). Stdlib only — zip (store) + streaming multipart upload.
Never loads the whole archive into RAM (multi‑GB packs).
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import uuid
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def _post_json(url: str, payload: dict, *, timeout: int = 30) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            resp.read()
    except (HTTPError, URLError, TimeoutError, OSError):
        pass


def _progress(vellum_base: str, job_id: str, message: str) -> None:
    print(message, flush=True)
    if not vellum_base or not job_id:
        return
    _post_json(
        f"{vellum_base.rstrip('/')}/api/jobs/{job_id}/progress",
        {"message": message, "log_tail": ""},
        timeout=5,
    )


def _report_job(
    vellum_base: str,
    job_id: str,
    *,
    ok: bool,
    host_content_path: str,
    error: str | None = None,
) -> None:
    """Close the claimed job even if the PowerShell wrapper hangs after exit."""
    if not vellum_base or not job_id:
        return
    if ok:
        payload: dict = {
            "result": {
                "ok": True,
                "host_content_path": host_content_path,
                "notes": "stage_pack_to_vellum.py",
            }
        }
    else:
        payload = {"error": (error or "stage_failed")[:2000]}
    _post_json(
        f"{vellum_base.rstrip('/')}/api/jobs/{job_id}/report",
        payload,
        timeout=30,
    )


def _store_zip(source_dir: Path, zip_path: Path) -> int:
    if zip_path.exists():
        zip_path.unlink()
    root = source_dir.resolve()
    count = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            zf.write(p, p.relative_to(root).as_posix())
            count += 1
            if count % 100 == 0:
                print(f"  zipped {count} files…", flush=True)
    return count


def _post_multipart(
    url: str,
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
    *,
    timeout: int,
) -> tuple[int, str]:
    """Stream multipart body — do NOT read the zip into memory."""
    boundary = f"----vellum{uuid.uuid4().hex}"
    head = bytearray()
    for name, value in fields.items():
        head.extend(f"--{boundary}\r\n".encode())
        head.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        head.extend(str(value).encode("utf-8"))
        head.extend(b"\r\n")
    head.extend(f"--{boundary}\r\n".encode())
    head.extend(
        (
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_path.name}"\r\n'
        ).encode()
    )
    head.extend(b"Content-Type: application/zip\r\n\r\n")
    tail = f"\r\n--{boundary}--\r\n".encode()
    file_size = file_path.stat().st_size
    total = len(head) + file_size + len(tail)

    parsed = urlparse(url)
    if parsed.scheme != "http":
        raise SystemExit(f"unsupported_url_scheme:{parsed.scheme}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    print(f"  uploading {file_size} bytes (streamed, timeout={timeout}s)", flush=True)
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.putrequest("POST", path)
        conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        conn.putheader("Content-Length", str(total))
        conn.endheaders()
        conn.send(bytes(head))
        sent = 0
        with file_path.open("rb") as fh:
            while True:
                chunk = fh.read(8 * 1024 * 1024)
                if not chunk:
                    break
                conn.send(chunk)
                sent += len(chunk)
                if sent == len(chunk) or sent % (64 * 1024 * 1024) < len(chunk):
                    print(f"  upload {sent}/{file_size} bytes", flush=True)
        conn.send(tail)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        return int(resp.status), body
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vellum-base", required=True)
    ap.add_argument("--asset-id", required=True)
    ap.add_argument("--host-content-path", required=True)
    ap.add_argument("--job-id", default="")
    ap.add_argument("--content-folder-name", default="")
    ap.add_argument("--work-dir", default="")
    ap.add_argument("--upload-timeout", type=int, default=14400)
    args = ap.parse_args()

    src = Path(args.host_content_path)
    if not src.is_dir():
        print(f"FAIL not_a_directory:{src}", flush=True)
        _report_job(
            args.vellum_base,
            args.job_id,
            ok=False,
            host_content_path=str(src),
            error=f"not_a_directory:{src}",
        )
        raise SystemExit(2)

    folder = (args.content_folder_name or src.name).strip()
    work = Path(args.work_dir) if args.work_dir else src.parent
    work.mkdir(parents=True, exist_ok=True)
    zip_path = work / f"vellum-stage-{args.asset_id}.zip"

    try:
        _progress(args.vellum_base, args.job_id, f"Stage zip {folder} from {src}")
        n = _store_zip(src, zip_path)
        size = zip_path.stat().st_size
        _progress(
            args.vellum_base,
            args.job_id,
            f"Stage upload {n} files ({size} bytes streamed)",
        )

        status, body = _post_multipart(
            f"{args.vellum_base.rstrip('/')}/api/assets/{args.asset_id}/import/stage-upload",
            {
                "host_content_path": str(src),
                "content_folder_name": folder,
            },
            "archive",
            zip_path,
            timeout=int(args.upload_timeout),
        )
    except Exception as exc:  # noqa: BLE001
        _report_job(
            args.vellum_base,
            args.job_id,
            ok=False,
            host_content_path=str(src),
            error=str(exc),
        )
        raise SystemExit(4) from exc
    finally:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass

    if status >= 400:
        print(f"FAIL upload status={status} body={body[:400]}", flush=True)
        _report_job(
            args.vellum_base,
            args.job_id,
            ok=False,
            host_content_path=str(src),
            error=f"upload_status_{status}",
        )
        raise SystemExit(3)

    _progress(args.vellum_base, args.job_id, f"Stage done {folder}")
    _report_job(
        args.vellum_base,
        args.job_id,
        ok=True,
        host_content_path=str(src),
    )
    print(body[:500], flush=True)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
