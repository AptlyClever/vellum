"""Shared Postgres storage for Vellum's single-document derived-data catalogs.

``attach.py``, ``lookdev.py``, ``game_ready.py`` and ``research.py`` each held their
catalog as one YAML file under ``data/`` -- the exact unlocked read-whole-file/
mutate/write-whole-file round trip that ``backend/intake.py``'s IntakeRun ledger and
``backend/register.py``'s asset catalog had before PX001 migrated them (see
``deploy/postgres/migrations/vellum/001__intake_runs.sql``,
``002__asset_register.sql``), bind-mounted into both ``vellum-app`` and
``vellum-worker``, which mutate them concurrently.

``vellum.catalogs`` (``003__catalogs.sql``) holds one row per catalog name, the
whole document as JSONB -- these are single JSON documents, not per-item
relational data, so a named row per catalog is the natural replacement for a named
YAML file, not a bespoke table per catalog.

Same convention ``register.py`` established for this repo: no safe default for an
unconfigured password, and no honest degraded mode -- reads and writes raise
directly (``RuntimeError`` / ``psycopg.Error``) rather than silently returning an
empty catalog, because callers cannot tell "genuinely empty" from "misconfigured".
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


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
    cfg = _pg_env()
    if not cfg["password"]:
        if required:
            raise RuntimeError("VELLUM_POSTGRES_PASSWORD not configured")
        return None
    return (
        f"host={cfg['host']} port={cfg['port']} dbname={cfg['dbname']} "
        f"user={cfg['user']} password={cfg['password']}"
    )


def load_catalog(name: str, empty: dict[str, Any]) -> dict[str, Any]:
    """Fetch the named catalog document, or a copy of `empty` if never saved."""
    dsn = _dsn(required=True)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT doc FROM vellum.catalogs WHERE name = %s", (name,))
            row = cur.fetchone()
    return row["doc"] if row is not None else dict(empty)


@contextmanager
def catalog_transaction(name: str, empty: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Lock the named catalog's row for the duration of a read-modify-write.

    Yields the current document -- mutate it in place (e.g.
    ``doc["items"].append(...)``) -- and on clean exit the mutated document is
    written back and the transaction commits. Serializes concurrent mutations to
    the SAME catalog the way ``register.py``'s per-row ``FOR UPDATE`` serializes
    concurrent patches to the same asset; this is coarser (one lock per whole
    catalog, not per item) because these catalogs are a single JSON document, not
    a table of independently addressable rows. An exception raised inside the
    ``with`` block rolls back instead of writing the partial mutation.
    """
    dsn = _dsn(required=True)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "INSERT INTO vellum.catalogs (name, doc) VALUES (%s, %s) "
                "ON CONFLICT (name) DO NOTHING",
                (name, Jsonb(empty)),
            )
            cur.execute(
                "SELECT doc FROM vellum.catalogs WHERE name = %s FOR UPDATE", (name,)
            )
            doc = cur.fetchone()["doc"]
            yield doc
            cur.execute(
                "UPDATE vellum.catalogs SET doc = %s, updated_at = now() WHERE name = %s",
                (Jsonb(doc), name),
            )
        conn.commit()
