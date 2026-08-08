-- PX001 Wave 3 -- vellum schema seed: the intake-run ledger.
--
-- Replaces backend/intake.py's data/intake-runs.yaml file-backed store. Every
-- propose_intake()/patch_step() call was a read-whole-file, mutate-in-Python,
-- write-whole-file round trip with no lock of any kind -- and unlike a single
-- in-process lock, that file is bind-mounted into two separate containers
-- (vellum-app serving the HTTP API, vellum-worker draining the job queue via
-- backend/jobs.py's run_job -> intake_mod.patch_step). Two real OS processes
-- can race the same file with nothing to serialize them: a concurrent
-- propose_intake from the API and patch_step from the worker could silently
-- drop one write, corrupting the whole intake-run list, not just one row.
--
-- One row per intake run. `steps` stays JSONB (not a normalized child table):
-- the step list shape is owned by intake.py's build_proposed_steps() and is
-- always read/written as a whole list, so a JSONB column preserves that shape
-- exactly while still making each run's update atomic -- patch_step() takes a
-- row lock (SELECT ... FOR UPDATE) so two concurrent patches to the SAME run
-- serialize instead of racing, and patches to different runs proceed
-- independently with zero shared state (the file version had neither
-- property).
CREATE TABLE IF NOT EXISTS vellum.intake_runs (
  run_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  display_name TEXT,
  engine TEXT,
  store_lane TEXT,
  source_bundle TEXT,
  status TEXT NOT NULL,
  requested_by TEXT,
  note TEXT NOT NULL DEFAULT '',
  steps JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- list_runs(asset_id=...) and build_asset_journey() both filter on one
-- asset_id and order by created_at desc.
CREATE INDEX IF NOT EXISTS intake_runs_asset_created_idx
  ON vellum.intake_runs (asset_id, created_at DESC);

-- list_runs() with no asset_id filter (the /api/health summary, /api/intake
-- with no query) still orders by created_at desc across all runs.
CREATE INDEX IF NOT EXISTS intake_runs_created_idx
  ON vellum.intake_runs (created_at DESC);
