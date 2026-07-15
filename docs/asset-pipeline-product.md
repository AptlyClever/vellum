# Vellum Asset Pipeline Product (binding)

**Locked:** 2026-07-14  
**Status:** active product direction  
**Supersedes:** `docs/ue-lookdev-worker.md` (frozen), ad-hoc Capture agent stack (`vellum_ue_agent.ps1` polling), science-project lookdev-as-product framing  
**Related:** [`factory-operations.md`](./factory-operations.md) (binding runtime
and continuation contract), `docs/capture-hosting-decision.md` (Epic Cmd batch
pattern retained as **one factory job type**, not the product), Governing CFD
slices A–F (complete)

## Problem the product solves

Control Alt Games owns purchased Unreal (and parked Unity) packs. The goal is not pictures — it is **real game elements** for Slots, Hail, LCARD, and future titles, plus a durable way to import packs #38+.

## Product shape

| Layer | Role |
| --- | --- |
| **Asset Library** | One curated Unreal project (`AuroraVellum`) with one folder per pack at `Content/<Pack>`, versioned in Perforce |
| **Conversion Factory** | Aurora reconcile runs three isolated parallel pack workers; each pack pays one headless `UnrealEditor-Cmd` boot for `factory-all` (models + media + VFX plan) |
| **Delivery Catalog** | Vellum vault + manifests + game-ready UI; lanes publish bundles to Games projects |
| **Native readiness** | Same Library + P4 is the substrate for a future Unreal title (migrate Content Browser) |

## Frozen (do not resume without operator unpark)

- Warm Lookdev Worker (`vellum_ue_worker_boot.py`, HTTP `:8771`)
- Custom `VellumUeAgent` scheduled-task polling loop as the primary host control plane
- SceneCapture / HighResShot backends
- Live mid-job hotpatch of host scripts

Unpark phrases (operator only): `Unpark: Lookdev Worker` / `Unpark: Capture Agent`.

## Success criteria

1. Pack install is boring: the human redeems/adds via Fab; reconcile owns P4,
   register, staging, validation, and conversion without operator bookkeeping.
2. Conversion jobs are idempotent, bounded, artifact-gated, observable, and
   run from versioned PowerShell + Python.
3. Games consume **validated, manifested** VFX clips / sprite sheets / glTF /
   textures / audio — not ad-hoc PNG heroes or bake plans.
4. A native Unreal title can Migrate from the Library without re-buying packs.

## Binding operating decisions

- **Hybrid target:** convert for web games now; retain the curated Unreal
  Library so a native title remains possible.
- **Human boundary:** Epic/Fab ownership and Add to Project are human UI steps.
  Everything after content appears in `AuroraVellum/Content` is machine-owned.
- **No manual lookdev gate:** "need lookdev" is retired. Availability may say
  `awaiting conversion (auto)`; that is factory backlog, not operator work.
- **One Library:** Fab installs only into
  `F:\Games\AuroraVellum`; never move `.uasset` folders on disk.
- **One controller:** `tools/pipeline/reconcile_aurora.ps1`, scheduled at logon
  and hourly. Do not revive the retired polling Capture agent.
- **Factory shape:** one Unreal boot per pack, three parallel read-only pack
  workers with isolated work/output directories, bounded smart uploads, and
  batched hub catalog writes.
- **Deferred is not blocked:** Fab Complete Project listings remain owned
  inventory but do not count as unfinished work until a game needs them.
- **Evidence over claims:** a running process is not success. Require manifests,
  plausible exported counts, catalog rows, and a clean reconcile report.

## Current completion boundary

As of 2026-07-14, active intake is reconciled, no on-disk pack lacks catalog
evidence, and the parallel factory backlog has drained without exceptions.
That closes **intake and baseline extraction**, not the whole product.

The next required slice is real Niagara output. `bake-vfx` currently creates
bake plans; it does not render transparent WebM or sprite sheets. Vellum must
execute MRQ/Niagara Baker, validate the media, and prove it in a real Games web
runtime before VFX conversion is complete. See
[`factory-operations.md`](./factory-operations.md).

## Prototype freeze

Repo tag `prototype-v0` marks the end of the Capture science project. Scratch scripts live under `archive/prototype-v0/`.
