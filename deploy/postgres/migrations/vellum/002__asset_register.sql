-- PX001 Wave 4 -- vellum schema: the asset register (Vellum's catalog of
-- every owned/tracked pack).
--
-- Replaces backend/register.py's data/asset-register.yaml file-backed store,
-- the same identical bug 001__intake_runs.sql fixed for backend/intake.py:
-- every list_assets()/get_asset()/patch_asset()/create_asset() call went
-- through ensure_register(), which did a read-whole-file, mutate-in-Python,
-- write-whole-file round trip on data/asset-register.yaml with no lock of any
-- kind -- and that file is bind-mounted into the same two containers as the
-- intake ledger was (vellum-app serving the HTTP API, vellum-worker draining
-- the job queue via backend/jobs.py's run_job -> _execute_record_paths ->
-- register.patch_asset). A concurrent PATCH /api/assets/{id} from the API and
-- a worker's record_paths job finishing for the same asset could race the
-- same file and silently drop one write -- corrupting the whole 37+ row
-- catalog, not just one asset.
--
-- Unlike intake_runs, this table backs core catalog data: nearly every route
-- in backend/main.py calls register_mod.get_asset()/list_assets() to resolve
-- an asset before doing anything else, and backend/scratch.py, jobs.py,
-- lookdev.py, game_ready.py, import_flow.py and journey.py all depend on it
-- too. That is NOT the "informational surface" intake_runs's reads are
-- (recent-run counts, journey timelines) -- there is no honest degraded mode
-- where the asset catalog is silently empty, so unlike intake.py, BOTH reads
-- and writes on this table raise loudly when Postgres is unconfigured or
-- unreachable. See backend/register.py's module docstring for the full
-- reasoning.
--
-- One row per asset. `tags` stays JSONB (a short, whole-list field owned by
-- register.py, never queried element-by-element). All other mutable fields
-- (redemption_status, raw_location, scratch_*, content_*, ue_in_project,
-- intake_notes) are plain columns so patch_asset() can UPDATE only the
-- fields it was given, instead of always rewriting an entire JSON blob.
CREATE TABLE IF NOT EXISTS vellum.asset_register (
  id TEXT PRIMARY KEY,
  list_index INTEGER NOT NULL,
  display_name TEXT NOT NULL,
  store_lane TEXT,
  store_label TEXT,
  package_type TEXT,
  engine TEXT NOT NULL DEFAULT 'unreal',
  redemption_deadline TEXT,
  redemption_status TEXT,
  project_fit TEXT,
  source_bundle TEXT,
  raw_location TEXT,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  content_folder_name TEXT,
  content_root TEXT,
  host_content_path TEXT,
  ue_in_project TEXT,
  intake_notes TEXT,
  scratch_project_path TEXT,
  scratch_project_status TEXT,
  scratch_engine_version TEXT,
  scratch_notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- list_assets() always returns in list_index order (the Humble inventory's
-- original ordering); this is every read's sort key.
CREATE INDEX IF NOT EXISTS asset_register_list_index_idx
  ON vellum.asset_register (list_index);

-- list_assets(engine=...) filters by engine on nearly every /api/assets call.
CREATE INDEX IF NOT EXISTS asset_register_engine_idx
  ON vellum.asset_register (engine);
