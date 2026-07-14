# Capture hosting decision — Epic batch MRQ (historical binding)

**Locked:** 2026-07-14 (as Capture path)  
**Superseded for product direction by:** [`docs/asset-pipeline-product.md`](./asset-pipeline-product.md)

## What remains true

Epic’s command-line Movie Render Queue pattern (`UnrealEditor-Cmd` + `-unattended` + Python + PNG-on-disk gate) is still the correct **technology** for rendering Niagara VFX to portable clips.

In the product, that pattern is **one Conversion Factory job type** (`bake-vfx`), not the whole host-control product.

## Frozen

**Warm Lookdev Worker** — see `docs/ue-lookdev-worker.md`.

**Custom Capture Agent polling loop** — retired in favor of CI runner + library intake runbook.

## Authority

[Batch Rendering with Command-Line (Epic Developer Community)](https://dev.epicgames.com/community/learning/tutorials/WWMD/unreal-engine-batch-rendering-with-command-line)
