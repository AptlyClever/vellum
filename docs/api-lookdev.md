# Lookdev derive API (Slice F)

Derived stills live under the private vault (`04-lookdev/`, `05-derived-renders/`).
Raw marketplace packs stay in `01-source-bundles/` and are **never** copied into product git repos.

## Lanes

`GET /api/lookdev/lanes`

Known project lanes: `slots`, `hail-overlay`, `field-command`, `threshold-affairs`, `lcard`.

## List / get outputs

- `GET /api/lookdev/outputs?asset_id=&lane=`
- `GET /api/lookdev/outputs/{id}`
- `GET /api/lookdev/outputs/{id}/file` — preview bytes (path must stay under vault)

## Derive

`POST /api/lookdev/derive`

```json
{
  "asset_id": "fireworks-vol-1-niagara",
  "lanes": ["slots", "hail-overlay"],
  "intake_run_id": "optional"
}
```

Enqueues a `derive_lookdev` worker job. Copies png/jpg (not `.uasset`) from the asset’s `raw_location` into lane folders and writes `DerivedOutput` records (+ a short readout under `06-readouts/`).

If the staged pack is uasset-only, derive falls back to the Fab library catalog thumbnail (`data/fab-listings.db`) so environment packs still get a vault hero. When neither stills nor a catalog match exist, the job succeeds and marks the step `skipped` (`no_preview_stills`).

## Ingest Niagara viewport still

`POST /api/lookdev/ingest-render` (multipart form)

- `asset_id`, `lane`, optional `note`, `file` (png/jpg/webp)

Writes kind `niagara-render` under `05-derived-renders/<lane>/<asset>/niagara/`.

`POST /api/lookdev/ingest-sequence` — zip of MRQ PNG frames → kind `niagara-sequence`.

Capture capability (MRQ + Sequencer, full fidelity): `docs/ue-mrq-capture.md`.  
Host profiles / retired backends: `docs/scratch-inspect-niagara.md`.
