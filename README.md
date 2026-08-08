# Vellum

**Vellum is an asset vault and conversion pipeline for purchased game-asset packs.**

You buy Unreal/Unity packs in bundles. They arrive as tens of gigabytes of
`.uasset` folders, FBX files, 4K textures and Niagara systems. Dropping that
into a product git repo is how repos die. Vellum is the layer in between: it
catalogs what you own, tracks intake, converts packs into game-ready artifacts,
and publishes only the validated output into consuming projects.

```
purchase → intake → Library (Unreal + Perforce) → Conversion Factory → game-ready catalog → product repos
```

## What it does

| Stage | What happens |
| --- | --- |
| **Catalog** | Every owned pack is a row: store lane, engine, package type, redemption state. |
| **Intake** | `IntakeRun` proposes and tracks the steps to get a pack from storefront to Library. Automatable steps go on a job queue. |
| **Library** | One Unreal project holds installed packs at their Fab-default layout, versioned in Perforce. |
| **Conversion Factory** | Job workers drive Unreal headless (MRQ capture, Niagara bakes), Blender, and texture packing to produce transparent WebM, sprite sheets, glTF, and OGG. |
| **Lookdev** | Preview stills derive into per-project lanes without copying `.uasset` packs anywhere. |
| **Delivery** | A game-ready catalog that consuming projects read. Product repos consume validated artifacts — never raw marketplace packs. |
| **Visual Research** | Reference images live in a separate vault collection from game-ready assets, uploaded as image + source-text bundles. |

## Status: read-only reference, not a turnkey install

This is a **working system extracted from a private homelab**, published as a
reference. It is honest about what it is:

- The backend expects a **Postgres** database and a **vault filesystem** mount.
- Several integrations (an asset-generation service, a research library, a
  control plane, and downstream game projects) are **HTTP calls to services that
  are not in this repo**. They degrade to no-ops or errors without them.
- The Unreal-side tooling assumes a Windows factory host with UE 5.8 installed.

`config/ue-hosts.json` and `config/seed-catalog.yaml` ship as **examples** — edit
them for your own machines and your own library.

Making this bootstrap standalone (local Postgres in Compose, stubbed
integrations, a real quickstart) is tracked work, not done work. Issues and
questions welcome.

## Run it anyway

```bash
docker compose up -d --build
```

Local, without Compose:

```bash
PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port 8770
```

Tests (the Postgres-backed ones need a database; the rest run bare):

```bash
PYTHONPATH=. pytest -q
```

Everything is configured by environment variable — see `docker-compose.yml` for
the full list and `secrets/vellum.env.example` for the secret half.

## Layout

| Path | What |
| --- | --- |
| `backend/` | FastAPI app: register, intake, jobs, lookdev, game-ready, attach, research |
| `web/` | Operator UI (vanilla JS, no build step) |
| `tools/pipeline/` | Conversion job implementations (Blender, ffmpeg, texture packing) |
| `tools/unreal/` | Unreal Python + PowerShell: MRQ capture, lookdev authoring, pack staging |
| `tools/godot_addon/` | Godot editor dock for pulling game-ready assets |
| `deploy/postgres/migrations/` | Schema |
| `docs/` | API contracts and pipeline design |

## Docs

- [`docs/asset-pipeline-product.md`](./docs/asset-pipeline-product.md) — the design this implements
- [`docs/intake-runbook.md`](./docs/intake-runbook.md) — redeem → install → register
- [`docs/library-project.md`](./docs/library-project.md) / [`docs/p4-library.md`](./docs/p4-library.md) — Unreal Library + Perforce
- [`docs/ue-mrq-capture.md`](./docs/ue-mrq-capture.md) — headless Unreal capture
- API contracts: [intake](./docs/api-intake.md) · [import](./docs/api-import.md) · [lookdev](./docs/api-lookdev.md) · [game-ready](./docs/api-game-ready.md) · [visual research](./docs/api-visual-research.md)

## Boundaries

- Raw assets and store keys live in the vault, **never in this repo**.
- Product repos consume validated game-ready artifacts, never raw packs.
- A bake plan is evidence, not a playable artifact.

## License

MIT — see [LICENSE](./LICENSE). The license covers this code only. Asset packs
you catalog with it stay under their own marketplace licenses.
