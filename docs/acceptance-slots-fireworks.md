# Acceptance test — Slots win fires converted fireworks

**Goal:** Prove game-ready delivery end-to-end without manual Unreal for the game surface.

## Preconditions

1. Library has `Content/FireworksV1`
2. Conversion Factory produced at least one VFX clip or sprite sheet for Fireworks
3. Element published to lane `slots` via Vellum UI or API
4. Slots / Bandit project can load a media URL or local path from the lane bundle

## Steps

```powershell
# 1) Plan / inventory bake (Cmd)
pwsh -File tools/pipeline/run_job.ps1 `
  -Job bake-vfx -Pack FireworksV1 -RunVfxMrq -MaxVfxSystems 1

# 2) After MRQ frames exist, pack_vfx_media runs inside run_job for bake-vfx.
#    If ffmpeg is on PATH this emits WebM; otherwise it emits a validated sprite sheet.
# 3) Ingest manifest into Vellum (from hub or Aurora with vault mount)
curl -sS -X POST http://192.168.68.93:8770/api/game-ready/ingest-manifest \
  -H "Content-Type: application/json" \
  -d "{\"asset_id\":\"fireworks-vol-1-niagara\",\"pack\":\"FireworksV1\",\"manifest_path\":\"F:/Games/AuroraVellum/Saved/VellumPipeline/FireworksV1/vfx/bake-vfx.manifest.json\"}"

# 4) Publish first element to slots
# GET /api/game-ready/elements?asset_id=fireworks-vol-1-niagara → pick id
# POST /api/game-ready/elements/{id}/publish  {"lane":"slots"}
```

## Pass criteria

| Check | Pass |
| --- | --- |
| Manifest `ok=true` and artifacts on disk | required |
| Catalog lists element with `kind` in `vfx-clip` / `sprite-sheet` / `bake-plan` | required |
| Lane folder contains copy under `05-derived-renders/slots/.../game-ready/` | required |
| Slots win / celebration hook plays the published clip once | operator witness |

## Harness stub

`tools/pipeline/acceptance/slots_fireworks_check.ps1` verifies catalog + lane file presence (does not launch Slots UI).
