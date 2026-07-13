"""UE capture host profiles (Aurora primary / Borealis secondary)."""

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


def default_project_dir() -> str:
    host = get_host()
    return str(host.get("project_dir") or host.get("project") or r"F:\Games\AuroraVellum")
