# Unreal scratch inspect + Niagara renders (Fireworks pilot)

Unity tier reconcile is **parked**. This path uses **Fireworks Vol. 1 - Niagara** only.

## 1. Scratch inspect (you · Unreal)

Your scratch project is already:

`C:\epic\VellumImport` (Content includes `FireworksV1`)

Checklist in Unreal 5.8:

1. Open `VellumImport.uproject`.
2. Content Browser → `FireworksV1` (or Maps / Particles).
3. Open a map or drop a Niagara system into an empty level.
4. Confirm systems simulate (timeline / Niagara viewport).
5. Note which systems look useful for Slots / Hail.

Then in Vellum (asset detail → **Scratch inspect**):

- Path: `C:\epic\VellumImport`
- Engine: `5.8`
- **Record scratch inspect**

Or:

```bash
curl -sS -X POST http://192.168.68.93:8770/api/scratch/record \
  -H 'Content-Type: application/json' \
  -d '{
    "asset_id": "fireworks-vol-1-niagara",
    "scratch_project_path": "C:\\epic\\VellumImport",
    "engine_version": "5.8",
    "notes": "Fireworks Niagara systems load",
    "intake_run_id": "intake-20260713-035932-40f887"
  }'
```

Vault hint folder (notes only, not the .uproject):  
`/mnt/data/vault/vellum/03-scratch-projects/unreal/cag_asset_inspection/`

## 2. True Niagara render stills (after inspect)

Texture stills from Slice F are **not** Niagara renders. For real viewport stills:

1. In Unreal, frame a Niagara system (dark bg helps fireworks).
2. Capture: Editor **High Resolution Screenshot**, or Win+Print → crop, or Movie Render Queue still.
3. Save a png/jpg on the Windows box.
4. In Vellum detail → **Upload Niagara render** (defaults to `slots` lane),  
   or:

```bash
curl -sS -X POST http://192.168.68.93:8770/api/lookdev/ingest-render \
  -F asset_id=fireworks-vol-1-niagara \
  -F lane=slots \
  -F note='Niagara viewport still' \
  -F file=@/path/to/fireworks-still.png
```

Files land under:

`05-derived-renders/<lane>/fireworks-vol-1-niagara/niagara/`  
(kind: `niagara-render` in the DerivedOutput catalog)

## 3. Boundaries

- Do not copy raw `.uasset` packs into product git repos.
- Scratch `.uproject` can stay on the Windows workstation.
- Keys stay out of git / Vellum logs.
