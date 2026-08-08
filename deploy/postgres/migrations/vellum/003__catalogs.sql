-- PX001 follow-up to 001/002 -- Vellum's remaining derived-data catalogs.
--
-- attach.py, lookdev.py, game_ready.py and research.py each did the identical
-- unlocked read-whole-file/mutate/write-whole-file round trip on their own YAML
-- file under data/ that backend/intake.py's IntakeRun ledger and
-- backend/register.py's asset catalog had before being migrated (see
-- 001__intake_runs.sql, 002__asset_register.sql) -- all bind-mounted into both
-- vellum-app and vellum-worker, which mutate them concurrently.
--
-- One row per catalog, the whole document as JSONB: these are single-document
-- catalogs (a dict with one list inside), not per-item relational data, so a
-- named row per catalog is the natural shape -- see backend/pg_catalog.py.
CREATE TABLE IF NOT EXISTS vellum.catalogs (
  name TEXT PRIMARY KEY,
  doc JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
