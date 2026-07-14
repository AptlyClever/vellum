# Intake runbook — pack into Library + Vellum register

**Product SoT:** [`asset-pipeline-product.md`](./asset-pipeline-product.md)  
**Audience:** one operator + agents. Honest about what stays human.

## Happy path (Unreal / Fab)

| Step | Who | Action |
| --- | --- | --- |
| 1 | Human | Redeem / purchase on Epic/Fab if needed (keys never enter git) |
| 2 | Human | Fab **Add to Project** → **AuroraVellum** only (`F:\Games\AuroraVellum`). Pack lands at `Content/<PackFolder>` — leave it there. **Never move pack folders on disk** (breaks .uasset references; see [`library-project.md`](./library-project.md)) |
| 3 | Human / agent | Open project once if Fab prompts compile |
| 4 | Agent | `p4 reconcile` + `p4 submit -d "Add pack <id>"` (see [`p4-library.md`](./p4-library.md)) |
| 5 | Agent | Stage pack to vault + update register (`content_root=/Game/<Pack>`, `host_content_path`, staged files). Prefer Vellum `host_stage` / `stage_pack_to_vellum.py` |
| 6 | CI | Conversion Factory jobs: `export-models` / `bake-vfx` / `export-media` for that pack (artifact-gated) |
| 7 | Operator | Publish game-ready rows to lanes from Vellum catalog UI |

## Do not

- Dump packs into Slots/Hail/LCARD git repos
- Run retired `vellum_ue_agent.ps1` / Lookdev Worker without unpark phrase
- Commit vault binaries or store keys in this repo
- Install Fab packs into any project other than AuroraVellum

## Register fields that matter

- `content_root` — Unreal path (`/Game/<PackFolder>`)
- `host_content_path` — Windows path under Aurora Library
- `raw_location` — vault `01-source-bundles/...` after stage
- Game-ready manifests — vault `05-derived-renders/game-ready/...` + catalog API

## Reconcile (the anti-"man in the middle" loop)

`tools/pipeline/reconcile_aurora.ps1` runs on Aurora at logon + hourly
(scheduled task `VellumReconcile`) and makes every layer agree without
operator bookkeeping:

1. Push fresh Content scan to hub
2. Register unknown folders (orphans) in Vellum
3. Patch register rows missing `host_content_path` / `in_project`
4. Stage un-vaulted packs (zip upload)
5. `p4 reconcile` + submit Content changes
6. Unreal load-check (`inventory-pack`) new/changed packs
7. Corrupt-package scan + quarantine report
8. Stray-project scan (Fab installed into the wrong project)

Everything it cannot fix lands in
`F:\Games\AuroraVellum\Saved\VellumReconcile\reconcile_report.json`
as an exception with a fix hint. **After adding a pack, either wait for the
hourly run or run the script once — no manual registration steps.**

## Recovery

- Corrupt packages → `<ProjectRoot>/Quarantine/` (outside Content) then re-Add from Fab
- Library health → `pwsh -File tools/pipeline/library/reorganize_library_content.ps1 -InventoryOnly`
