# Intake propose API (Slice B)

Agent- and UI-facing JSON for `IntakeRun` records.

## Propose

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
- Slice B proposes only. Workers that drive downloads land in later slices.
