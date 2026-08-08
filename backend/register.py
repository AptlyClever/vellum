"""Vellum asset register — load seed, compute redeem window, query.

Storage is Postgres (PX001 Wave 4), not a YAML file. The file version
(data/asset-register.yaml) did the exact same read-whole-file/mutate/write-
whole-file round trip on every ensure_register()/patch_asset()/create_asset()
call that backend/intake.py's IntakeRun ledger did (see
deploy/postgres/migrations/vellum/001__intake_runs.sql) -- no lock of any
kind, bind-mounted into two separate containers (vellum-app serving the HTTP
API, vellum-worker draining the job queue via jobs.py's run_job ->
_execute_record_paths -> patch_asset). A concurrent PATCH /api/assets/{id}
and a worker's record_paths job finishing for the same asset raced the same
file and could silently drop one write. See
deploy/postgres/migrations/vellum/002__asset_register.sql for the schema this
replaced it with.

Unlike intake.py, reads here do NOT degrade gracefully. intake.py's reads
back purely informational surfaces (recent-run counts, journey timelines)
that can honestly show "no data". This module backs the asset catalog itself
-- nearly every route in main.py resolves an asset via get_asset()/
list_assets() before doing anything else, and scratch.py, jobs.py,
lookdev.py, game_ready.py, import_flow.py and journey.py all depend on it.
There is no honest degraded mode where the catalog is silently empty, so
both reads and writes raise when Postgres is unconfigured or unreachable --
same "core state, not advisory telemetry" reasoning intake.py's writes
already used, just applied to this module's reads too.

The seed file (config/seed-catalog.yaml) is still a plain, checked-in YAML
file -- it is read-only content, never written to by this module, so it
carries none of the race the register data itself had. ensure_register()
seeds vellum.asset_register from it exactly once (first call against an
empty table); every later call is a plain read. Concurrent first-boot seeding
from vellum-app and vellum-worker starting at the same time is itself handled
(`ON CONFLICT (id) DO NOTHING`) rather than assumed away.
"""

from __future__ import annotations

import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = ROOT / "config" / "seed-catalog.yaml"


def seed_path() -> Path:
    configured = os.environ.get("VELLUM_SEED_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_SEED


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def redeem_window(deadline: str | None, *, now: datetime | None = None) -> str:
    """Return open | expired | unknown. Indicator only — does not invalidate owned assets."""
    dt = parse_deadline(deadline)
    if dt is None:
        return "unknown"
    current = now or _now()
    return "expired" if current >= dt else "open"


def enrich_asset(asset: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    out = deepcopy(asset)
    out["redeem_window"] = redeem_window(out.get("redemption_deadline"), now=now)
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Register at {path} must be a mapping")
    return raw


def _pg_env() -> dict[str, str]:
    """Read fresh from the environment on every call (not cached at import) so
    tests can monkeypatch per-test without reloading this module."""
    return {
        "host": os.environ.get("VELLUM_POSTGRES_HOST", "127.0.0.1"),
        "port": os.environ.get("VELLUM_POSTGRES_PORT", "5433"),
        "dbname": os.environ.get("VELLUM_POSTGRES_DB", "control_alt_fleet"),
        "user": os.environ.get("VELLUM_POSTGRES_USER", "vellum_writer"),
        "password": os.environ.get("VELLUM_POSTGRES_PASSWORD", "").strip(),
    }


def _dsn(*, required: bool) -> str | None:
    """Connection string for the fleet Postgres, or None if not configured.

    No safe default for the password: an unconfigured deploy must not guess
    at trust/peer auth against a LAN-reachable database.
    """
    cfg = _pg_env()
    if not cfg["password"]:
        if required:
            raise RuntimeError("VELLUM_POSTGRES_PASSWORD not configured")
        return None
    return (
        f"host={cfg['host']} port={cfg['port']} dbname={cfg['dbname']} "
        f"user={cfg['user']} password={cfg['password']}"
    )


def _row_to_asset(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "list_index": row.get("list_index"),
        "display_name": row.get("display_name"),
        "store_lane": row.get("store_lane"),
        "store_label": row.get("store_label"),
        "package_type": row.get("package_type"),
        "engine": row.get("engine"),
        "redemption_deadline": row.get("redemption_deadline"),
        "redemption_status": row.get("redemption_status"),
        "project_fit": row.get("project_fit"),
        "source_bundle": row.get("source_bundle"),
        "raw_location": row.get("raw_location"),
        "tags": row.get("tags") or [],
        "content_folder_name": row.get("content_folder_name"),
        "content_root": row.get("content_root"),
        "host_content_path": row.get("host_content_path"),
        "ue_in_project": row.get("ue_in_project"),
        "intake_notes": row.get("intake_notes"),
        "scratch_project_path": row.get("scratch_project_path"),
        "scratch_project_status": row.get("scratch_project_status"),
        "scratch_engine_version": row.get("scratch_engine_version"),
        "scratch_notes": row.get("scratch_notes"),
    }


def _seed_header() -> dict[str, Any]:
    """Static doc-level metadata, read straight from the (read-only) seed file.

    Nothing outside this module reads version/project/brand_family/source --
    only vault_root is consumed elsewhere (jobs.py, intake.py, lookdev.py,
    import_flow.py) -- but ensure_register() keeps returning the same doc
    shape callers already expect.
    """
    seed = _load_yaml(seed_path())
    return {
        "version": int(seed.get("version") or 1),
        "project": seed.get("project") or "vellum",
        "brand_family": seed.get("brand_family") or "control-alt-games",
        "vault_root": seed.get("vault_root") or "/mnt/data/vault/vellum",
        "source": seed.get("source") or str(seed_path()),
    }


def _mirror_to_vault(assets: list[dict[str, Any]], header: dict[str, Any]) -> None:
    """Best-effort human-readable export into the vault index.

    Diagnostic only, same as the pre-Postgres version's mirror: Postgres is
    the source of truth, so a failure here must never break a request that
    already committed.
    """
    vault_mirror = os.environ.get("VELLUM_VAULT_REGISTER_PATH", "").strip()
    if not vault_mirror:
        return
    try:
        doc = {**header, "seeded_at": _now().isoformat(), "assets": assets}
        mirror = Path(vault_mirror)
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(yaml.dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    except Exception:
        pass


def _seed_rows(cur) -> None:
    """Seed vellum.asset_register from the seed YAML if it is empty.

    ON CONFLICT DO NOTHING makes this safe to run from both vellum-app and
    vellum-worker starting at the same time against a fresh database: whoever
    commits first wins, the other's insert is a silent no-op instead of a
    duplicate-key crash at startup.
    """
    seed = _load_yaml(seed_path())
    for row in seed.get("assets") or []:
        if not isinstance(row, dict):
            continue
        cur.execute(
            """
            INSERT INTO vellum.asset_register (
              id, list_index, display_name, store_lane, store_label,
              package_type, engine, redemption_deadline, redemption_status,
              project_fit, source_bundle, raw_location, tags
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                row.get("id"),
                row.get("list_index"),
                row.get("display_name"),
                row.get("store_lane"),
                row.get("store_label"),
                row.get("package_type"),
                str(row.get("engine") or "unreal").lower(),
                row.get("redemption_deadline"),
                row.get("redemption_status"),
                row.get("project_fit"),
                row.get("source_bundle"),
                row.get("raw_location"),
                Jsonb(list(row.get("tags") or [])),
            ),
        )


def ensure_register(*, force_reseed: bool = False) -> dict[str, Any]:
    """Ensure vellum.asset_register is seeded; return the doc-shaped catalog."""
    dsn = _dsn(required=True)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            if force_reseed:
                cur.execute("DELETE FROM vellum.asset_register")
            cur.execute("SELECT COUNT(*) FROM vellum.asset_register")
            (count,) = cur.fetchone()
            if count == 0:
                _seed_rows(cur)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM vellum.asset_register ORDER BY list_index")
            rows = cur.fetchall()
    header = _seed_header()
    return {**header, "assets": [_row_to_asset(r) for r in rows]}


def list_assets(
    *,
    q: str | None = None,
    engine: str | None = None,
    redeem_window_filter: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    doc = ensure_register()
    assets = [enrich_asset(a, now=now) for a in (doc.get("assets") or [])]
    if engine:
        eng = engine.strip().lower()
        assets = [a for a in assets if str(a.get("engine") or "").lower() == eng]
    if redeem_window_filter:
        rw = redeem_window_filter.strip().lower()
        assets = [a for a in assets if a.get("redeem_window") == rw]
    if q:
        needle = q.strip().lower()
        if needle:
            def matches(a: dict[str, Any]) -> bool:
                blob = " ".join(
                    str(a.get(k) or "")
                    for k in ("display_name", "package_type", "project_fit", "store_label", "id", "engine")
                ).lower()
                tags = " ".join(str(t) for t in (a.get("tags") or [])).lower()
                return needle in blob or needle in tags

            assets = [a for a in assets if matches(a)]
    assets.sort(key=lambda a: int(a.get("list_index") or 0))
    return assets


def get_asset(asset_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    aid = asset_id.strip()
    for asset in list_assets(now=now):
        if asset.get("id") == aid:
            return asset
    return None


def patch_asset(
    asset_id: str,
    *,
    redemption_status: str | None = None,
    raw_location: str | None = None,
    intake_notes: str | None = None,
    scratch_project_path: str | None = None,
    scratch_project_status: str | None = None,
    scratch_engine_version: str | None = None,
    scratch_notes: str | None = None,
    content_root: str | None = None,
    host_content_path: str | None = None,
    content_folder_name: str | None = None,
    ue_in_project: str | None = None,
) -> dict[str, Any]:
    """Update mutable register fields for an owned asset."""
    aid = asset_id.strip()
    dsn = _dsn(required=True)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Row lock: two concurrent patches to the SAME asset (e.g. an
            # operator's PATCH /api/assets/{id} racing vellum-worker's
            # record_paths job for the same asset) serialize here instead of
            # racing a whole-file read/mutate/write like the YAML store did.
            # Patches to different assets never contend at all.
            cur.execute(
                "SELECT * FROM vellum.asset_register WHERE id = %s FOR UPDATE",
                (aid,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(aid)

            fields: dict[str, Any] = {}
            if redemption_status is not None:
                fields["redemption_status"] = redemption_status.strip()
            if raw_location is not None:
                fields["raw_location"] = raw_location.strip() or None
            if intake_notes is not None:
                fields["intake_notes"] = intake_notes
            if scratch_project_path is not None:
                fields["scratch_project_path"] = scratch_project_path.strip() or None
            if scratch_project_status is not None:
                fields["scratch_project_status"] = scratch_project_status.strip()
            if scratch_engine_version is not None:
                fields["scratch_engine_version"] = scratch_engine_version.strip() or None
            if scratch_notes is not None:
                fields["scratch_notes"] = scratch_notes
            if content_root is not None:
                fields["content_root"] = content_root.strip() or None
            if host_content_path is not None:
                fields["host_content_path"] = host_content_path.strip() or None
            if content_folder_name is not None:
                fields["content_folder_name"] = content_folder_name.strip() or None
            if ue_in_project is not None:
                fields["ue_in_project"] = ue_in_project.strip() or None

            if not fields:
                updated = row
            else:
                set_clause = ", ".join(f"{k} = %s" for k in fields)
                cur.execute(
                    f"UPDATE vellum.asset_register SET {set_clause}, updated_at = now() "
                    "WHERE id = %s RETURNING *",
                    (*fields.values(), aid),
                )
                updated = cur.fetchone()
    assert updated is not None
    asset = _row_to_asset(updated)
    _mirror_to_vault(list_assets(), _seed_header())
    return asset


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:80]


def create_asset(
    *,
    display_name: str,
    engine: str = "unreal",
    package_type: str = "Unreal Engine pack",
    store_lane: str = "epic-games-store",
    store_label: str = "Epic Games Store (free / extra)",
    source_bundle: str = "epic-free-or-extra",
    project_fit: str = "",
    content_folder_name: str | None = None,
    host_content_path: str | None = None,
    asset_id: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Append a non-Humble pack (free Epic, extras) to the live register."""
    name = (display_name or "").strip()
    if not name:
        raise ValueError("display_name_required")
    aid = (asset_id or slugify(name)).strip()
    if not aid:
        raise ValueError("asset_id_invalid")

    folder = (content_folder_name or "").strip() or None
    content_root = f"/Game/{folder}" if folder else None
    notes = f"Registered via create_asset at {_now().isoformat()}"

    dsn = _dsn(required=True)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Ensure the table exists/is seeded before computing the next
            # list_index against it (a totally fresh database has never had
            # ensure_register() called).
            cur.execute("SELECT COUNT(*) FROM vellum.asset_register")
            (count,) = cur.fetchone()
            if count == 0:
                _seed_rows(cur)
            # Lock existing rows so two concurrent create_asset calls can't
            # compute the same "next" list_index. list_index is cosmetic
            # ordering, not a uniqueness constraint, but this keeps
            # concurrent creates from colliding on it the way the whole-file
            # write used to collide on everything.
            cur.execute("SELECT list_index FROM vellum.asset_register FOR UPDATE")
            existing = cur.fetchall()
            max_idx = 0
            for r in existing:
                try:
                    max_idx = max(max_idx, int(r["list_index"] or 0))
                except (TypeError, ValueError):
                    pass

            cur.execute(
                """
                INSERT INTO vellum.asset_register (
                  id, list_index, display_name, store_lane, store_label,
                  package_type, engine, redemption_status, project_fit,
                  source_bundle, tags, content_folder_name, content_root,
                  host_content_path, ue_in_project, intake_notes
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING
                RETURNING *
                """,
                (
                    aid,
                    max_idx + 1,
                    name,
                    store_lane,
                    store_label,
                    package_type,
                    engine.strip().lower() or "unreal",
                    "owned",
                    project_fit or "Operator-added Epic free/extra pack.",
                    source_bundle,
                    Jsonb(list(tags or ["epic-free-or-extra"])),
                    folder,
                    content_root,
                    (host_content_path or "").strip() or None,
                    "in_project" if host_content_path else None,
                    notes,
                ),
            )
            row = cur.fetchone()
    if row is None:
        raise KeyError(f"asset_exists:{aid}")
    asset = _row_to_asset(row)
    _mirror_to_vault(list_assets(), _seed_header())
    return asset


def catalog_version() -> str:
    """A cheap change signal for callers that used to cache-key off the
    register file's mtime (see import_flow.py's availability_index()).

    Postgres has no file to stat, so this is the catalog's own last-write
    timestamp instead -- still a single cheap indexed-free aggregate over a
    ~40-row table, far cheaper than the full list_assets() + availability
    pass it guards.
    """
    dsn = _dsn(required=True)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(updated_at) FROM vellum.asset_register")
            (max_updated,) = cur.fetchone()
    return max_updated.isoformat() if max_updated else "unseeded"


def register_summary(*, now: datetime | None = None) -> dict[str, Any]:
    assets = list_assets(now=now)
    open_n = sum(1 for a in assets if a.get("redeem_window") == "open")
    expired_n = sum(1 for a in assets if a.get("redeem_window") == "expired")
    return {
        "count": len(assets),
        "redeem_open": open_n,
        "redeem_expired": expired_n,
        "engines": sorted({str(a.get("engine")) for a in assets if a.get("engine")}),
    }
