"""UE capture host profiles (Aurora primary / Borealis secondary)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOSTS = ROOT / "config" / "ue-hosts.json"


def hosts_path() -> Path:
    return DEFAULT_HOSTS


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
    return profile


def public_hosts_payload() -> dict[str, Any]:
    data = load_hosts()
    active = active_host_id(data)
    hosts_out = []
    for hid, raw in (data.get("hosts") or {}).items():
        row = dict(raw)
        row["id"] = hid
        row["active"] = hid == active
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
    return str(host.get("project_dir") or host.get("project") or r"F:\Games\VellumImport")
