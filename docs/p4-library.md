# Perforce (P4) for the AuroraVellum Library

**Product SoT:** [`asset-pipeline-product.md`](./asset-pipeline-product.md)  
**Library project:** `F:\Games\AuroraVellum`  
**Free tier:** Perforce Helix Core — up to 5 users / 20 workspaces self-hosted.

## Why P4 (not git) for Content

Unreal `.uasset` / `.umap` binaries do not merge. P4 file locking + large binary storage is the Epic-recommended pattern. **Git stays** for the Vellum code/tools repo (`E:\Dev\vellum`).

## Topology (LAN)

| Piece | Host | Notes |
| --- | --- | --- |
| `p4d` server | Aurora (or hub) | Port `1666`, depot `//vellum_library/...` |
| Workspace | Aurora | Root `F:\Games\AuroraVellum` |
| Clients | operators / CI | Optional second workspace on hub for read-only sync |

## Bootstrap (Aurora admin)

```powershell
# 1) Prefer the official Helix Core Server installer (creates superuser correctly):
#    https://www.perforce.com/downloads/helix-core-p4d
#    Free for 5 users / 20 workspaces.
# 2) Optional: binaries-only bootstrap (p4 + p4d already under Program Files\Perforce):
pwsh -File tools/pipeline/p4/bootstrap_p4_server.ps1

# 3) Create depot + client + first submit of Content/
pwsh -File tools/pipeline/p4/first_library_submit.ps1
```

Live status: [`tools/pipeline/p4/STATUS.md`](../tools/pipeline/p4/STATUS.md).

Scripts expect `p4` / `p4d` on PATH. If missing, they exit with clear instructions.

## Everyday pack submit

```text
1. Fab Add-to-Project → AuroraVellum (lands at Content/<Pack>; leave it there)
2. p4 reconcile //vellum_library/AuroraVellum/Content/...
3. p4 submit -d "Add pack <name>"
4. Vellum register update (automated stage / PATCH content_root)
```

## Ignore rules

Do **not** version: `Intermediate/`, `Saved/`, `DerivedDataCache/`, `.vs/`, `Binaries/` (unless shipping a custom plugin build). See `tools/pipeline/p4/p4ignore.txt`.
