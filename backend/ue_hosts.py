"""UE host profiles (Aurora asset/factory host; Borealis dev workstation)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOSTS = ROOT / "config" / "ue-hosts.json"


def hosts_path() -> Path:
    return DEFAULT_HOSTS


def specs_dir() -> Path:
    raw = (os.environ.get("VELLUM_UE_HOST_SPECS_DIR") or "").strip()
    if raw:
        path = Path(raw)
    else:
        path = Path(os.environ.get("VELLUM_DATA_DIR") or (ROOT / "data")) / "ue-host-specs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def specs_path(host_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in host_id.strip().lower())
    return specs_dir() / f"{safe}.json"


def load_host_specs(host_id: str) -> dict[str, Any] | None:
    path = specs_path(host_id)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def save_host_specs(host_id: str, specs: dict[str, Any]) -> dict[str, Any]:
    hid = host_id.strip().lower()
    # Ensure host exists in profiles.
    get_host(hid)
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "schema_version": 1,
        "host_id": hid,
        "updated_at": now,
        "specs": specs,
    }
    path = specs_path(hid)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def merge_host_specs(host_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge top-level keys into existing specs (utilization heartbeats)."""
    hid = host_id.strip().lower()
    existing = load_host_specs(hid) or {}
    specs = dict(existing.get("specs") or {}) if isinstance(existing, dict) else {}
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(specs.get(key), dict):
            merged = dict(specs[key])
            merged.update(value)
            specs[key] = merged
        else:
            specs[key] = value
    return save_host_specs(hid, specs)


def load_hosts() -> dict[str, Any]:
    path = hosts_path()
    if not path.is_file():
        raise FileNotFoundError(f"ue_hosts_missing:{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def active_host_id(doc: dict[str, Any] | None = None) -> str:
    data = doc or load_hosts()
    return str(data.get("active") or "aurora").strip().lower()


def get_host(host_id: str | None = None, doc: dict[str, Any] | None = None) -> dict[str, Any]:
    data = doc or load_hosts()
    hid = (host_id or active_host_id(data)).strip().lower()
    hosts = data.get("hosts") or {}
    if hid not in hosts:
        known = ", ".join(sorted(hosts))
        raise KeyError(f"unknown_ue_host:{hid};known={known}")
    profile = dict(hosts[hid])
    profile["id"] = hid
    profile["active"] = hid == active_host_id(data)
    specs = load_host_specs(hid)
    if specs:
        profile["host_specs"] = specs.get("specs")
        profile["host_specs_updated_at"] = specs.get("updated_at")
    return profile


def public_hosts_payload() -> dict[str, Any]:
    data = load_hosts()
    active = active_host_id(data)
    hosts_out = []
    for hid, raw in (data.get("hosts") or {}).items():
        row = dict(raw)
        row["id"] = hid
        row["active"] = hid == active
        specs = load_host_specs(hid)
        if specs:
            row["host_specs"] = specs.get("specs")
            row["host_specs_updated_at"] = specs.get("updated_at")
        hosts_out.append(row)
    hosts_out.sort(key=lambda h: (0 if h.get("active") else 1, h.get("id") or ""))
    return {
        "schema_version": int(data.get("schema_version") or 1),
        "active": active,
        "notes": data.get("notes") or "",
        "hosts": hosts_out,
        "active_host": get_host(active, data),
    }


def list_content_folders(host_id: str | None = None) -> dict[str, Any]:
    host = get_host(host_id)
    specs = host.get("host_specs") or {}
    folders = specs.get("content_folders") or []
    if not isinstance(folders, list):
        folders = []
    return {
        "schema_version": 1,
        "host_id": host.get("id"),
        "updated_at": host.get("host_specs_updated_at"),
        "content_root_path": specs.get("content_root_path") or host.get("project_dir"),
        "content_scan_roots": specs.get("content_scan_roots")
        or host.get("content_scan_roots")
        or [],
        "fab_target_project": specs.get("fab_target_project")
        or host.get("fab_target_project")
        or host.get("project"),
        "fab_target_label": specs.get("fab_target_label")
        or host.get("fab_target_label")
        or host.get("label"),
        "folders": folders,
        "count": len(folders),
    }


def normalize_host_path(path: str) -> str:
    return (path or "").strip().replace("/", "\\").rstrip("\\").lower()


def path_known_in_content_scan(path: str, host_id: str | None = None) -> dict[str, Any] | None:
    """Return matching content_folders row if path was seen by latest host_scan."""
    want = normalize_host_path(path)
    if not want:
        return None
    for folder in list_content_folders(host_id).get("folders") or []:
        if not isinstance(folder, dict):
            continue
        if normalize_host_path(str(folder.get("path") or "")) == want:
            return folder
    return None


def default_project_dir() -> str:
    host = get_host()
    return str(host.get("project_dir") or host.get("project") or r"F:\Games\AuroraVellum")
