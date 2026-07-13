# Slice E — Epic / Fab staging runbook (Fireworks pilot)

End-to-end path driven for **Fireworks Vol. 1 - Niagara** (`fireworks-vol-1-niagara`).

## What “download” means on Epic

Unreal packs do **not** get a Launcher Download button. Flow:

1. Redeem Humble key into Epic (same account as Launcher).
2. Install Unreal Engine; create a scratch project (e.g. `C:\epic\VellumImport`).
3. Fab Library → asset → **Add to Project**.
4. Pack lands under `…\Content\<PackFolder>\` (pilot: `C:\epic\VellumImport\Content\FireworksV1`).

## Copy into Vellum vault

Vault destination (host `192.168.68.93`):

```text
/mnt/data/vault/vellum/01-source-bundles/humble-all-in-one-unreal-unity-gamedev/epic-unreal/<asset-id>/
```

PowerShell:

```powershell
scp -r "C:\epic\VellumImport\Content\FireworksV1\*" `
  dev@192.168.68.93:/mnt/data/vault/vellum/01-source-bundles/humble-all-in-one-unreal-unity-gamedev/epic-unreal/fireworks-vol-1-niagara/
```

## Record in Vellum

```bash
# Propose
curl -sS -X POST http://192.168.68.93:8770/api/intake/propose \
  -H 'Content-Type: application/json' \
  -d '{"asset_id":"fireworks-vol-1-niagara","requested_by":"operator"}'

# Mark human gates (use returned run_id)
curl -sS -X PATCH http://192.168.68.93:8770/api/intake/{run_id}/steps/redeem_store \
  -H 'Content-Type: application/json' \
  -d '{"status":"done","notes":"Redeemed Humble→Epic"}'
curl -sS -X PATCH http://192.168.68.93:8770/api/intake/{run_id}/steps/download_epic \
  -H 'Content-Type: application/json' \
  -d '{"status":"done","notes":"Add to Project + scp into vault"}'

# Automatable stage/record/fit
curl -sS -X POST http://192.168.68.93:8770/api/intake/{run_id}/enqueue-automatable

# Register fields
curl -sS -X PATCH http://192.168.68.93:8770/api/assets/fireworks-vol-1-niagara \
  -H 'Content-Type: application/json' \
  -d '{"redemption_status":"redeemed","intake_notes":"…"}'
```

## Pilot evidence (2026-07-13)

| Field | Value |
| --- | --- |
| Asset | `fireworks-vol-1-niagara` |
| Windows source | `C:\epic\VellumImport\Content\FireworksV1` |
| Vault | `…/epic-unreal/fireworks-vol-1-niagara` (~115 files, ~609M) |
| IntakeRun | `intake-20260713-035932-40f887` |
| Honest leftovers | `license_note`, `scratch_inspect`, `derive_lookdev` still pending / needs-human |

Do **not** commit pack binaries or keys to git.
