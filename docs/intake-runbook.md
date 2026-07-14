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
2. Push the launcher's Fab catalog (`VaultCache/FabLibrary/listings_v1.db`) to
   the hub — the launcher's own record of ownership and download formats
3. Register unknown folders (orphans) in Vellum
4. Patch register rows missing `host_content_path` / `in_project`
5. Stage un-vaulted packs (zip upload)
6. `p4 reconcile` + submit Content changes
7. Unreal load-check (`inventory-pack`) new/changed packs
8. Corrupt-package scan + quarantine report
9. Launcher visibility guard — keeps `CreatedProjectPaths=F:/Games` (the
   **parent** folder, not the project folder) in the launcher ini so
   AuroraVellum always appears in Fab's *Add to Project* dropdown
10. Stray-project scan (Fab installed into the wrong project)

Everything it cannot fix lands in
`F:\Games\AuroraVellum\Saved\VellumReconcile\reconcile_report.json`
as an exception with a fix hint. **After adding a pack, either wait for the
hourly run or run the script once — no manual registration steps.**

### How "not on Aurora" packs are classified

Fab Unreal listings have **no standalone file download** — content only
materializes inside an Unreal project via *Add to Project*. The hub reads the
launcher catalog and classifies every missing pack
(`acquisition` on `/api/import/coverage` and `/api/import/queue`):

| Method | Meaning | Who acts |
| --- | --- | --- |
| `vault_install` | Bits already in VaultCache and mapped | Agent (`fab-install`) |
| `fab_add_to_project` | Launcher owns it; one click: Fab Library → Add to Project → AuroraVellum | Human, once |
| `fab_add_to_project_unseen` | Launcher on Aurora has never seen the pack; find it in Fab Library first | Human, once |
| `fab_create_project_migrate` | Fab Distribution Method is **Complete Project** — cannot Add to Project. Deferred: create a temp project + Migrate only if the pack is ever needed | Nobody (until pulled into scope) |
| `manual` | Non-Unreal source (e.g. Unity-only) | Human |

The reconcile exception report carries the same per-pack instructions
(`acquire_*` kinds), so the old generic "Epic Launcher: download" hint is gone.

### Deferred packs (Complete Project)

Fab listings whose Distribution Method is *Complete Project* (The Count's
Church, Abandoned Cabin, Loot Drops Vol.2 - Niagara) do **not** count as
unfinished inventory. Coverage reports them under `deferred` /
`deferred_count`; the import queue lists them under `deferred_epic`. They are
owned and documented, but no one owes work on them unless a game actually
needs the content. Arabic Fortress is an *Asset Package* (UE 5.3–5.7): use
Add to Project with "show all projects" if the UE 5.8 AuroraVellum is hidden.

Dungeon Ruins ships with three permanently corrupt assets
(`decor_07`, `Pillar_Base_02`, `Pillar_Base_03`); these are accepted debt —
reconcile logs them as `accepted_quarantine` actions, not exceptions.

## Recovery

- Corrupt packages → `<ProjectRoot>/Quarantine/` (outside Content) then re-Add from Fab
- Library health → `pwsh -File tools/pipeline/library/reorganize_library_content.ps1 -InventoryOnly`
