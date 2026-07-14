# AuroraVellum Library Project

**SoT project:** `F:\Games\AuroraVellum\AuroraVellum.uproject`  
**Product SoT:** [`asset-pipeline-product.md`](./asset-pipeline-product.md)

## Layout (actual, load-bearing)

```
Content/
  <PackFolder>/             # purchased / Fab packs, exactly where Fab installs them
  Vellum/                   # Vellum-owned studio maps, sequences, pipeline helpers
  Python/                   # factory helpers synced from repo (no auto-run hooks)
  Developers/               # local scratch (never library SoT)
  Collections/  Fab/  __ExternalActors__/  __ExternalObjects__/
Quarantine/                 # (project root, OUTSIDE Content) corrupt packages
```

## The one hard rule

**Never move or rename `.uasset`/`.umap` files or folders on the filesystem.**
Unreal assets store absolute package paths (`/Game/<Pack>/…`) inside the binary.
A disk move breaks every reference (including references between files *inside
the same pack*) and the editor cannot repair it because no redirectors exist.

- Moves/renames happen **only inside the Unreal editor** (which rewrites
  references and leaves redirectors), followed by *Fix Up Redirectors*.
- Fab **Add to Project** decides the folder name at Content root — leave it.
- Isolation between packs comes from the folder-per-pack convention plus
  Perforce history, not from a parent `External/` directory.

(2026-07-14: an automated disk move to `Content/External/` was applied and
reverted the same day for exactly this reason.)

## Rules

1. One Fab pack = one folder at Content root; never merge packs.
2. Vellum register `content_root` = `/Game/<PackFolder>`.
3. Corrupt / zero-byte `.uasset` files go to `<ProjectRoot>/Quarantine/<Pack>/…`
   (outside `Content/` so the asset registry stops scanning them) and are
   re-added via Fab **Add to Project**.
4. Binary history lives in Perforce (see [`p4-library.md`](./p4-library.md)), not git.
5. No editor auto-run hooks in `Content/Python/` (the warm-worker
   `init_unreal.py` crash-looped the editor and is archived).

## Tooling

```powershell
# Inventory + corrupt-package scan (never moves pack folders)
pwsh -File tools/pipeline/library/reorganize_library_content.ps1 -InventoryOnly

# Quarantine zero/corrupt packages only
pwsh -File tools/pipeline/library/reorganize_library_content.ps1 -QuarantineCorrupt
```

## Health gate

- Project opens with no unloadable-package errors outside `_Quarantine/`
- `tools/pipeline/library/library_health_report.json` → `unloadable_count: 0`
- First P4 submit of `Content/` completed
