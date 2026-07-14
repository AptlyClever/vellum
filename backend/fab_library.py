"""Fab library intelligence — use the launcher's own metadata, not guesses.

The Epic Games Launcher keeps a SQLite catalog of the operator's Fab library
at ``VaultCache/FabLibrary/listings_v1.db``. Aurora's reconcile loop pushes a
copy to the hub (``data/fab-listings.db``). That catalog is authoritative
"free information" we previously ignored:

* ``download_meta.format`` — every listing we own is ``unreal-engine``.
  There is **no standalone file download**; content only materializes inside
  an Unreal project via *Add to Project*.
* Presence in ``local_listing`` — whether the launcher on Aurora has ever
  seen the pack. Absent packs cannot be staged, installed, or reconciled
  until the operator uses *Add to Project* once.
* ``download_meta.path`` / ``cache_size`` — whether VaultCache holds bits.

``acquisition_for_asset`` turns this into a per-pack acquisition method so
coverage, the import queue, and the reconcile exception report say exactly
what an operator (or agent) must do instead of a generic "download" hint.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Acquisition methods, most to least automated.
METHOD_VAULT_INSTALL = "vault_install"  # bits already in VaultCache; agent can install
METHOD_FAB_ADD_TO_PROJECT = "fab_add_to_project"  # launcher knows it; operator clicks once
METHOD_FAB_ADD_UNSEEN = "fab_add_to_project_unseen"  # launcher has never seen it
METHOD_MANUAL = "manual"  # non-Unreal or unknown source


def _db_path() -> Path:
    raw = (os.environ.get("VELLUM_FAB_LISTINGS_DB") or "").strip()
    if raw:
        return Path(raw)
    return ROOT / "data" / "fab-listings.db"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


_INDEX_CACHE: dict[str, dict[str, Any]] | None = None
_INDEX_CACHE_MTIME: float = -1.0
_INDEX_CACHE_PATH: str = ""


def clear_cache() -> None:
    global _INDEX_CACHE, _INDEX_CACHE_MTIME, _INDEX_CACHE_PATH
    _INDEX_CACHE = None
    _INDEX_CACHE_MTIME = -1.0
    _INDEX_CACHE_PATH = ""


def library_index(*, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Normalized title → launcher-known listing facts. Cached by db mtime."""
    global _INDEX_CACHE, _INDEX_CACHE_MTIME, _INDEX_CACHE_PATH
    db = _db_path()
    try:
        mtime = db.stat().st_mtime if db.is_file() else 0.0
    except OSError:
        mtime = 0.0
    if (
        not force_refresh
        and _INDEX_CACHE is not None
        and _INDEX_CACHE_MTIME == mtime
        and _INDEX_CACHE_PATH == str(db)
    ):
        return _INDEX_CACHE

    index: dict[str, dict[str, Any]] = {}
    if db.is_file():
        try:
            conn = sqlite3.connect(str(db))
        except sqlite3.Error:
            conn = None
        if conn is not None:
            try:
                rows = conn.execute(
                    """
                    SELECT ll.title, ll.listing_type, ll.category_path,
                           dm.format, dm.path, dm.cache_size
                    FROM local_listing ll
                    LEFT JOIN download_meta dm ON dm.listing_uid = ll.uid
                    """
                ).fetchall()
            except sqlite3.Error:
                rows = []
            finally:
                conn.close()
            for title, ltype, cat, fmt, vpath, csize in rows:
                key = _norm(str(title or ""))
                if not key:
                    continue
                row = index.setdefault(
                    key,
                    {
                        "title": str(title or ""),
                        "listing_type": str(ltype or ""),
                        "category_path": str(cat or ""),
                        "formats": [],
                        "vault_cache_path": "",
                        "cache_size": 0,
                    },
                )
                f = str(fmt or "").strip()
                if f and f not in row["formats"]:
                    row["formats"].append(f)
                if vpath:
                    row["vault_cache_path"] = str(vpath)
                try:
                    row["cache_size"] = max(row["cache_size"], int(csize or 0))
                except (TypeError, ValueError):
                    pass

    _INDEX_CACHE = index
    _INDEX_CACHE_MTIME = mtime
    _INDEX_CACHE_PATH = str(db)
    return index


def match_listing(display_name: str) -> dict[str, Any] | None:
    """Fuzzy-match a register display_name against launcher library titles."""
    name_n = _norm(display_name)
    if not name_n:
        return None
    index = library_index()
    exact = index.get(name_n)
    if exact:
        return exact
    best: tuple[int, dict[str, Any]] | None = None
    for key, row in index.items():
        score = 0
        if name_n in key or key in name_n:
            score = 800 - abs(len(key) - len(name_n))
        else:
            head = _norm(display_name.split("(")[0].split(" - ")[0])
            if len(head) >= 6 and (head in key or key.startswith(head)):
                score = 600 - abs(len(key) - len(head))
        if score > 0 and (best is None or score > best[0]):
            best = (score, row)
    return best[1] if best else None


def acquisition_for_asset(
    asset: dict[str, Any], *, installable: bool = False
) -> dict[str, Any]:
    """How this pack can actually be acquired, per launcher metadata.

    ``installable`` means VaultCache content candidates are already mapped
    (``fab_install_candidates``) so the host agent can install without a human.
    """
    display = str(asset.get("display_name") or asset.get("id") or "")
    engine = str(asset.get("engine") or "").strip().lower()
    listing = match_listing(display)
    formats = list((listing or {}).get("formats") or [])
    ue_only = (not formats) or formats == ["unreal-engine"]

    if installable:
        method = METHOD_VAULT_INSTALL
        hint = (
            "VaultCache already has the files — POST "
            f"/api/assets/{asset.get('id')}/import/fab-install "
            "(reconcile runs this automatically)."
        )
    elif listing is not None:
        method = METHOD_FAB_ADD_TO_PROJECT
        hint = (
            "Epic Launcher → Fab Library → "
            f"\"{listing['title']}\" → Add to Project → AuroraVellum. "
        )
        if ue_only:
            hint += "UE-only listing: no standalone file download exists."
    elif engine == "unreal":
        method = METHOD_FAB_ADD_UNSEEN
        hint = (
            "Launcher on Aurora has never seen this pack (not in the Fab "
            f"library cache). Epic Launcher → Fab Library → search \"{display}\" "
            "→ Add to Project → AuroraVellum. UE-only: it cannot be downloaded "
            "as files; it only materializes inside an Unreal project."
        )
    else:
        method = METHOD_MANUAL
        hint = "Non-Unreal source; acquire per store instructions and stage-upload."

    return {
        "method": method,
        "seen_by_launcher": listing is not None,
        "formats": formats,
        "ue_only": bool(ue_only and engine == "unreal"),
        "listing_title": (listing or {}).get("title") or None,
        "vault_cache_path": (listing or {}).get("vault_cache_path") or None,
        "cache_size": (listing or {}).get("cache_size") or 0,
        "operator_hint": hint,
    }


def save_listings_db(data: bytes) -> Path:
    """Atomically replace the hub copy of the launcher's listings DB."""
    if not data.startswith(b"SQLite format 3"):
        raise ValueError("not_sqlite")
    dest = _db_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".db.tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    clear_cache()
    return dest
