# Conversion Factory operations and continuation

**Status:** active operating contract  
**Product SoT:** [`asset-pipeline-product.md`](./asset-pipeline-product.md)  
**Host:** Aurora (`F:\Games\AuroraVellum`) — primary asset/factory workstation  
**Controller:** `tools/pipeline/reconcile_aurora.ps1`

Borealis is the primary development workstation. That does not move this
factory role off Aurora; see [`machine-roles.md`](./machine-roles.md).

## What the factory owns

Once a pack exists under `AuroraVellum/Content`, the operator owes no
registration, staging, Perforce, inventory, "lookdev", or conversion work.
The hourly/logon reconcile controller owns:

1. register and host-path reconciliation;
2. vault staging;
3. Perforce submit;
4. Unreal package inventory/load validation;
5. Conversion Factory execution;
6. game-ready output upload and catalog registration;
7. health and quarantine reporting.

The UI phrase **"need lookdev" is retired**. `awaiting conversion (auto)`
means machine-owned backlog, not an operator task.

## Current execution model

`reconcile_aurora.ps1` finds on-disk packs without game-ready catalog
evidence and runs them through the following product path:

```text
reconcile
  -> bounded pack queue (default 30/run)
  -> 3 parallel pack workers
  -> one UnrealEditor-Cmd boot per pack
  -> factory-all.py
       -> export-models
       -> export-media
       -> bake-vfx plan
  -> smart ZIP (max 480 files; no recompression for PNG/GLB/WebM/WAV)
  -> POST /api/assets/{asset_id}/game-ready/upload-run
  -> one batched game-ready catalog write
```

Each worker has an isolated directory:

```text
F:\Games\AuroraVellum\Saved\VellumPipeline\workers\<Pack>\
```

Workers share `AuroraVellum` **read-only**. They must never save, migrate,
rename, fix up redirectors, compile assets, or otherwise mutate the Library
project concurrently. Any future factory job that writes Unreal content must
run exclusively, outside the parallel worker pool.

### Why this shape is binding

- One combined job avoids three Unreal cold starts per pack.
- Three workers use Aurora's CPU without stacking enough Unreal instances to
  exhaust RAM or destabilize the shared project.
- Worker-local scripts, logs, manifests, and outputs prevent clobbering.
- Synchronous Asset Registry scanning prevents false zero-asset success.
- A fresh, successful manifest is authoritative when Unreal crashes during
  process teardown.
- Hub ingest builds all rows and writes YAML once; per-element catalog
  rewrites are prohibited.
- Re-uploading a pack replaces that pack's prior catalog rows instead of
  duplicating them.

## Evidence and status semantics

These terms are intentionally different:

| Term | Meaning |
| --- | --- |
| `on_disk` | Pack is in the Aurora Library |
| `staged` | Source bundle exists in the Vellum vault |
| `validated` | Unreal inventory/load check completed |
| `converted` / `ready` in current availability | At least one game-ready catalog element exists |
| `published` | Selected game-ready element was copied into a game lane |
| `deferred` | Owned Complete Project pack; no work is owed until explicitly needed |

**Important:** current `converted` evidence can be a GLB, texture, audio file,
manifest, or VFX bake plan. It does not guarantee that every useful element
in the pack has been converted or that a Niagara effect has a playable web
artifact.

## Current verified baseline (2026-07-14)

- Active Fab intake: **0 blocked packs**
- Orphan Content folders: **0**
- Complete Project inventory: **3 deferred packs**
  - The Count's Church
  - Abandoned Cabin
  - Loot Drops Vol.2 - Niagara
- On-disk packs without game-ready catalog evidence: **0**
- Last full parallel drain: **23 packs**, **0 reconcile exceptions**
- Measured parallel run: three Unreal workers; Aurora reached approximately
  100% aggregate CPU during CPU-heavy phases

Accepted, non-actionable debt:

- Dungeon Ruins: three permanently corrupt/quarantined packages
- SlashTrail_SoftTofu: two UE4 `Rig` retarget assets that cannot load in UE 5.8

## The product is not finished

`factory-all` still inventories Niagara systems and writes a bake plan during
the parallel read-only worker phase. The real MRQ step is now a separate
exclusive reconcile phase because it authors transient `/Game/Vellum` assets
and must never run inside the shared parallel worker pool.

Verified baseline (2026-07-16):

- `FireworksV1` rendered 31 Niagara systems through MRQ on Aurora.
- `pack_vfx_media.ps1` accepted 16 systems after alpha / visible-content /
  motion / dimension / frame-count validation.
- The hub catalog was replaced with the filtered valid run.
- `slots` now has 32 validated `vfx-clip` lane rows:
  16 `contained` + 16 `breakout`.
- Invalid systems remain useful diagnostic evidence but are not published to
  game lanes.

**Vault access rule (binding):** Aurora talks to the Vellum hub over HTTP only
(`upload-run`, `publish`, `unpublish`, catalog queries on `:8770`). Never mount,
share, or hand-edit the vault filesystem (`/mnt/data/vault/vellum`) from the
factory host — it exists only on the press (`192.168.68.93`).

The current VFX operating slice is therefore:

1. keep `reconcile_aurora.ps1` phase 6c bounded (`-MaxVfxPerRun 1` by default);
2. render bake-plan packs exclusively through `run_job.ps1 -Job bake-vfx -RunVfxMrq`;
3. accept partial valid VFX packs when at least one validated artifact exists;
4. upload only filtered / validated game-ready outputs;
5. publish only validation-passing `contained` / `breakout` clips to lanes;
6. prove each consuming game reads catalog rows instead of scanning stale files.

After VFX, finish equivalent acceptance gates for models, textures, and audio.
Catalog presence alone must not become the final quality standard.

## Observability and truth rules

Do not infer progress from a process existing, a command being launched, or a
CPU prediction. Verify all three layers:

1. **Machine activity**
   - `Get-Process UnrealEditor-Cmd`
   - Task Manager aggregate CPU/GPU/disk
2. **Factory artifacts**
   - worker manifest under `Saved\VellumPipeline\workers\<Pack>\<Pack>\`
   - non-zero exported counts where the pack contains matching asset classes
3. **Product state**
   - game-ready API contains rows for the asset
   - reconcile report has zero unexpected exceptions

Primary files:

```text
F:\Games\AuroraVellum\Saved\VellumReconcile\reconcile_report.json
F:\Games\AuroraVellum\Saved\VellumReconcile\factory-all-<Pack>.log
F:\Games\AuroraVellum\Saved\VellumReconcile\vfx-render-<Pack>.log
F:\Games\AuroraVellum\Saved\VellumPipeline\workers\<Pack>\
```

The controller must stream progress directly. Do not pipe long-running
reconcile output through `Select-Object -Last`, which buffers output and makes
healthy work look idle.

## Running and recovery

Normal operation is the scheduled task:

```powershell
Get-ScheduledTask -TaskName VellumReconcile
```

Manual full reconcile:

```powershell
pwsh -NoProfile -File tools\pipeline\reconcile_aurora.ps1
```

Controlled factory drain:

```powershell
pwsh -NoProfile -File tools\pipeline\reconcile_aurora.ps1 `
  -MaxFactoryPerRun 30 -FactoryWorkers 3
```

Controlled VFX render pass:

```powershell
pwsh -NoProfile -File tools\pipeline\reconcile_aurora.ps1 `
  -SkipInventory -SkipFactory -MaxVfxPerRun 1
```

Three workers is the validated default for Aurora's 8-core/16-thread CPU and
64 GB RAM. Increase it only after measuring CPU, memory, disk contention,
Unreal stability, and output correctness.

If a run is interrupted:

1. stop child `UnrealEditor-Cmd` and reconcile PowerShell processes;
2. remove only the stale
   `Saved\VellumReconcile\reconcile.lock`;
3. keep failed upload ZIPs for diagnosis;
4. rerun reconcile—completed packs are skipped by catalog evidence.

## Scaling decisions already made

- Keep the controller push-based; do not revive the retired polling agent.
- Keep raw packs in the Library/vault; game repos consume derived artifacts.
- Keep pack workers isolated and read-only against the Library.
- Prefer bounded concurrency over unlimited fan-out.
- Replace the YAML game-ready catalog with SQLite before catalog size or
  concurrent writes become a recurring bottleneck (target: before sustained
  5,000+ elements).
- Add durable run/progress records to the API/UI; terminal output is
  diagnostic evidence, not the product's status surface.
