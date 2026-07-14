# Vellum Asset Pipeline Product (binding)

**Locked:** 2026-07-14  
**Status:** active product direction  
**Supersedes:** `docs/ue-lookdev-worker.md` (frozen), ad-hoc Capture agent stack (`vellum_ue_agent.ps1` polling), science-project lookdev-as-product framing  
**Related:** `docs/capture-hosting-decision.md` (Epic Cmd batch pattern retained as **one factory job type**, not the product), Governing CFD slices A–F (complete)

## Problem the product solves

Control Alt Games owns purchased Unreal (and parked Unity) packs. The goal is not pictures — it is **real game elements** for Slots, Hail, LCARD, and future titles, plus a durable way to import packs #38+.

## Product shape

| Layer | Role |
| --- | --- |
| **Asset Library** | One curated Unreal project (`AuroraVellum`) with one folder per pack at `Content/<Pack>`, versioned in Perforce |
| **Conversion Factory** | CI runner on Aurora runs headless `UnrealEditor-Cmd` jobs: export-models, bake-vfx, export-media |
| **Delivery Catalog** | Vellum vault + manifests + game-ready UI; lanes publish bundles to Games projects |
| **Native readiness** | Same Library + P4 is the substrate for a future Unreal title (migrate Content Browser) |

## Frozen (do not resume without operator unpark)

- Warm Lookdev Worker (`vellum_ue_worker_boot.py`, HTTP `:8771`)
- Custom `VellumUeAgent` scheduled-task polling loop as the primary host control plane
- SceneCapture / HighResShot backends
- Live mid-job hotpatch of host scripts

Unpark phrases (operator only): `Unpark: Lookdev Worker` / `Unpark: Capture Agent`.

## Success criteria

1. Pack install is a boring checklist: redeem → Fab Add-to-Project → P4 submit → Vellum register.
2. Conversion jobs are idempotent, artifact-gated, and run from versioned CI YAML + Python.
3. Games consume **manifested** VFX clips / sprite sheets / glTF / textures / audio — not ad-hoc PNG heroes.
4. A native Unreal title can Migrate from the Library without re-buying packs.

## Prototype freeze

Repo tag `prototype-v0` marks the end of the Capture science project. Scratch scripts live under `archive/prototype-v0/`.
