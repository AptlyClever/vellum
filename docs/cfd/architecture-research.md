# Vellum architecture research (CFD discovery record)

**CFD task:** `task-vellum-architecture-research`  
**Governing CFD:** `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`  
**Recorded:** 2026-07-12 / 2026-07-13  
**Interactive board:** Cursor canvas `vellum-architecture-research.canvas.tsx`

## Operator answers that shaped this

1. Jobs: find/reuse, intake, lookdev — rights/deadlines are indicator-only (green→red after expiry).
2. Users: one human + agents for ~1 year; still touch TV/LCARD/Hail as consumers.
3. Surface: full Vellum webapp + Axiom leftnav under **Read** (label **Vellum**).
4. AI: propose intake steps, write register entries, and drive downloads/imports; know Axiom/Praxis/Games context.
5. Scale: more assets, more game projects, more agents; automation depth evolves.
6. Hard boundaries: default local-first vault on LAN; no keys in git; no cloud DAM required.

## What Vellum is

A Control Alt Games **asset vault + register + intake/lookdev pipeline** — not an enterprise DAM, not Perforce, not Control Alt core (Axiom/Eidolon).

## Layers (industry → Vellum)

| Layer | Industry | Vellum |
| --- | --- | --- |
| Storage | Object store / NAS | `/mnt/data/vault/vellum` filesystem |
| Catalog | Metadata DB | Asset register (IDs stable; paths movable) |
| Ingest | Staged pipeline | IntakeRun propose → stage → register |
| Workers | Async jobs | Conduit-style API + worker |
| Consumers | Engines / CMS | Derived lookdev into Games project lanes |
| UI | DAM console | Vellum webapp + Axiom Read embed |

## Free lessons locked in

1. Folders are not a catalog.
2. Ingest scope is a product decision (Humble → vault → lookdev) — already chosen.
3. Rights are metadata lights, not a department.
4. Binary VCS (Perforce) ≠ purchased-pack vault.
5. Previews/derived stills beat perfect tags on day one.
6. Marketplace automation must be staged and honest (`needs-human`).
7. Scale agents via APIs/jobs/register mutations, not chat memory.

## Sibling steal-list

| Concern | Copy |
| --- | --- |
| Webapp + health | Bandit (FastAPI + UI, `/api/health`, Repo Ops) |
| Long intake jobs | Conduit (Celery/Redis job pattern) |
| Theme/brand | `/api/effective/vellum` |
| Fleet row | `apps.registry.yaml` id `vellum` (already present) |
| Read nav | Hardcode in Axiom `Shell.tsx` (Read is not registry-driven) |

## Build slices (plan phases)

| Slice | Outcome |
| --- | --- |
| A | Register + browse; 37 Humble rows; redeem-by lights |
| B | Intake propose → IntakeRun |
| C | Worker stage jobs |
| D | Axiom sibling + Read nav |
| E | Drive brittle imports with checkpoints |
| F | Lookdev derive into project lanes |

## Recommended shape

**Outside:** Bandit-shaped FastAPI webapp.  
**Inside:** Conduit-shaped workers.  
**Objects:** Asset, IntakeRun, Job, DerivedOutput, ProjectLane.
