"""Shared pytest fixtures for Vellum's backend test suite.

``pg_intake`` points backend.intake at a disposable Postgres test database
and truncates ``vellum.intake_runs`` before the test runs. It is opt-in per
test (a normal pytest fixture, not autouse) so the rest of the suite is
completely unaffected by it.

Deliberately reads its own ``VELLUM_TEST_POSTGRES_*`` variables rather than
reusing ``VELLUM_POSTGRES_*`` directly: the PX001 lesson from a sibling
service's pilot (see Mneme memory / issue-20260805T234920Z-11f612b3) is that
exporting real fleet Postgres credentials as ambient environment variables
before running a *whole* test suite lets some unrelated, unisolated test
quietly write real rows into production through them. Requiring a distinctly
named test variable means that never happens by accident here -- if only
``VELLUM_POSTGRES_PASSWORD`` (the production name) is set and
``VELLUM_TEST_POSTGRES_PASSWORD`` is not, this fixture skips rather than
treating the former as good enough.

Every var this fixture sets on the real names is scoped to the single test
via ``monkeypatch`` and reverted on teardown -- no test file that does not
request ``pg_intake`` ever sees Postgres configured at all, so it exercises
intake.py's read-degrades-gracefully / write-raises-loudly contract instead.

``pg_register`` is the same idea for backend.register's asset catalog:
opt-in, truncates ``vellum.asset_register``, skips cleanly when the test
database is not configured. Request it whenever a test wants a guaranteed
fresh 37-asset baseline regardless of what earlier tests in the run did to
shared rows.

``_vellum_register_ambient_postgres`` (below, autouse, session-scoped) is a
deliberate DEPARTURE from the pg_intake opt-in-only design, not an
inconsistency: intake.py's reads are advisory and degrade to empty without
Postgres, so leaving most of the suite with no Postgres configured at all is
itself a useful demonstration of that contract. backend/register.py has no
such degraded mode -- it is core catalog data that nearly every route in
main.py resolves an asset through (get_asset()/list_assets()), and
scratch.py, jobs.py, lookdev.py, game_ready.py, import_flow.py and journey.py
all depend on it too. Roughly a dozen existing test files across the suite
call ensure_register()/patch_asset()/create_asset() (or hit endpoints that
do) expecting the standard Humble-seed catalog to just be there, the same
way it always was against the old file-backed store. Making every one of
those opt in individually would mean editing every one of those files for no
behavioral gain -- there is no "does it degrade gracefully" property being
demonstrated by leaving them unconfigured, only a maintenance burden. This
fixture is still non-prod-safe: it only ever reads ``VELLUM_TEST_POSTGRES_*``
(never touches the real ``VELLUM_POSTGRES_PASSWORD`` fleet credential), and
if that test credential is not configured it changes nothing -- register-
touching tests then fail loudly with a clear "not configured" error instead
of silently skipping, which is a more honest local-dev signal than a mystery
404 would be.
"""

from __future__ import annotations

import os

import psycopg
import pytest

_TEST_PG_VARS = (
    "VELLUM_POSTGRES_HOST",
    "VELLUM_POSTGRES_PORT",
    "VELLUM_POSTGRES_DB",
    "VELLUM_POSTGRES_USER",
    "VELLUM_POSTGRES_PASSWORD",
)


def _test_pg_creds() -> dict[str, str] | None:
    password = os.environ.get("VELLUM_TEST_POSTGRES_PASSWORD", "").strip()
    if not password:
        return None
    db = os.environ.get("VELLUM_TEST_POSTGRES_DB", "control_alt_fleet_test")
    assert db != "control_alt_fleet", (
        "test Postgres fixtures must not point at the real control_alt_fleet database"
    )
    return {
        "host": os.environ.get("VELLUM_TEST_POSTGRES_HOST", "127.0.0.1"),
        "port": os.environ.get("VELLUM_TEST_POSTGRES_PORT", "5433"),
        "dbname": db,
        "user": os.environ.get("VELLUM_TEST_POSTGRES_USER", "vellum_writer"),
        "password": password,
    }


def _dsn(creds: dict[str, str]) -> str:
    return (
        f"host={creds['host']} port={creds['port']} dbname={creds['dbname']} "
        f"user={creds['user']} password={creds['password']}"
    )


@pytest.fixture(scope="session", autouse=True)
def _vellum_register_ambient_postgres():
    """Configure VELLUM_POSTGRES_* for the whole session from VELLUM_TEST_POSTGRES_*
    and seed a known-good baseline once. See module docstring for why this one
    fixture is session-wide/autouse instead of per-test opt-in like pg_intake.
    """
    creds = _test_pg_creds()
    if creds is None:
        yield
        return

    previous = {name: os.environ.get(name) for name in _TEST_PG_VARS}
    os.environ["VELLUM_POSTGRES_HOST"] = creds["host"]
    os.environ["VELLUM_POSTGRES_PORT"] = str(creds["port"])
    os.environ["VELLUM_POSTGRES_DB"] = creds["dbname"]
    os.environ["VELLUM_POSTGRES_USER"] = creds["user"]
    os.environ["VELLUM_POSTGRES_PASSWORD"] = creds["password"]
    try:
        from backend.register import ensure_register

        ensure_register(force_reseed=True)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture
def pg_intake(monkeypatch):
    creds = _test_pg_creds()
    if creds is None:
        pytest.skip(
            "VELLUM_TEST_POSTGRES_PASSWORD not configured; skipping "
            "Postgres-backed intake tests"
        )

    monkeypatch.setenv("VELLUM_POSTGRES_HOST", creds["host"])
    monkeypatch.setenv("VELLUM_POSTGRES_PORT", str(creds["port"]))
    monkeypatch.setenv("VELLUM_POSTGRES_DB", creds["dbname"])
    monkeypatch.setenv("VELLUM_POSTGRES_USER", creds["user"])
    monkeypatch.setenv("VELLUM_POSTGRES_PASSWORD", creds["password"])

    dsn = _dsn(creds)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE vellum.intake_runs")
    return dsn


@pytest.fixture
def pg_register(monkeypatch):
    creds = _test_pg_creds()
    if creds is None:
        pytest.skip(
            "VELLUM_TEST_POSTGRES_PASSWORD not configured; skipping "
            "Postgres-backed register tests"
        )

    monkeypatch.setenv("VELLUM_POSTGRES_HOST", creds["host"])
    monkeypatch.setenv("VELLUM_POSTGRES_PORT", str(creds["port"]))
    monkeypatch.setenv("VELLUM_POSTGRES_DB", creds["dbname"])
    monkeypatch.setenv("VELLUM_POSTGRES_USER", creds["user"])
    monkeypatch.setenv("VELLUM_POSTGRES_PASSWORD", creds["password"])

    dsn = _dsn(creds)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE vellum.asset_register")
    return dsn


@pytest.fixture
def pg_catalogs(monkeypatch):
    """Same idea as `pg_intake`/`pg_register`, for the single-document catalogs
    in `vellum.catalogs` (attach.py/lookdev.py/game_ready.py/research.py -- see
    backend/pg_catalog.py). Clears every catalog row rather than one table, since
    all four catalogs share the same table keyed by name.
    """
    creds = _test_pg_creds()
    if creds is None:
        pytest.skip(
            "VELLUM_TEST_POSTGRES_PASSWORD not configured; skipping "
            "Postgres-backed catalog tests"
        )

    monkeypatch.setenv("VELLUM_POSTGRES_HOST", creds["host"])
    monkeypatch.setenv("VELLUM_POSTGRES_PORT", str(creds["port"]))
    monkeypatch.setenv("VELLUM_POSTGRES_DB", creds["dbname"])
    monkeypatch.setenv("VELLUM_POSTGRES_USER", creds["user"])
    monkeypatch.setenv("VELLUM_POSTGRES_PASSWORD", creds["password"])

    dsn = _dsn(creds)
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vellum.catalogs")
        conn.commit()
    return dsn


def seed_catalog(dsn: str, name: str, doc: dict) -> None:
    """Seed a catalog row directly, matching how a real write would leave it --
    for tests that need a pre-existing document rather than building it up
    through the module's own mutating calls."""
    from psycopg.types.json import Jsonb

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO vellum.catalogs (name, doc) VALUES (%s, %s) "
                "ON CONFLICT (name) DO UPDATE SET doc = EXCLUDED.doc",
                (name, Jsonb(doc)),
            )
        conn.commit()
