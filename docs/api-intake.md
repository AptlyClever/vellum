# Intake propose + jobs API

## Propose (Slice B)

`POST /api/intake/propose`

```json
{
  "asset_id": "portal-vfx-enhanced",
  "requested_by": "cursor",
  "note": "optional"
}
```

Returns a full `IntakeRun` including ordered `steps[]`.

## List / get

- `GET /api/intake?asset_id=&limit=50`
- `GET /api/intake/{run_id}`

## Patch a step

`PATCH /api/intake/{run_id}/steps/{step_id}`

```json
{
  "status": "done",
  "notes": "Staged under vault path …"
}
```

Allowed step statuses: `pending`, `needs-human`, `blocked`, `done`, `skipped`.

## Honesty rules

- Epic/Unity download and redeem steps start as `needs-human` (or `blocked` if redeem window expired).
- Expired redeem **does not** mean delete local assets — only that re-fetch from store may be impossible.
- Workers never fake Epic/Unity redeem or download.

## Enqueue automatable jobs (Slice C)

`POST /api/intake/{run_id}/enqueue-automatable`

Queues worker jobs for pending automatable steps only:

- `stage_vault` → `prepare_stage` (creates vault staging dir + marker)
- `record_paths` → `record_paths` (writes `raw_location` on register)
- `confirm_project_fit` → `confirm_project_fit`

Does **not** enqueue Epic/Unity redeem or download (`needs-human`).

## Patch asset register fields (Slice E)

`PATCH /api/assets/{asset_id}`

```json
{
  "redemption_status": "redeemed",
  "raw_location": "/mnt/data/vault/vellum/.../fireworks-vol-1-niagara",
  "intake_notes": "optional provenance"
}
```

Use after a human redeem/download lands files in the vault. See `docs/slice-e-epic-staging.md`.

## Jobs

- `POST /api/jobs` — `{kind, asset_id?, intake_run_id?, step_id?, payload?}`
- `GET /api/jobs?status=&asset_id=`
- `GET /api/jobs/{job_id}`

Worker: `python -m backend.worker` (Compose service `vellum-worker`).
On success, linked IntakeRun steps are marked `done`.
