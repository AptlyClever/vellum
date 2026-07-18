# Vellum

**Vellum** is the Control Alt Games asset vault and **asset pipeline product**:
catalog, intake, Library project, Conversion Factory, and game-ready delivery
for purchased Unreal/Unity packs — without dumping raw marketplace packs into
product git repos.

| Fact | Value |
| --- | --- |
| Canonical home | **Control Alt Games** (creative label under Control Alt) |
| Project root | `/mnt/temp/config/vellum` |
| Private vault (data) | `/mnt/data/vault/vellum` |
| Operator UI | http://192.168.68.93:8770/ |
| Health | http://192.168.68.93:8770/api/health |
| GitHub | [`AptlyClever/vellum`](https://github.com/AptlyClever/vellum) (public) |
| Axiom registry id | `vellum` |
| Not | Control Alt core (that family includes Axiom, Praxis, Eidolon, …) |

## Run

```bash
docker compose up -d --build
# or local: PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port 8770
pytest -q
```

## Start here

| Doc | What it is |
| --- | --- |
| **[DEV_TRACKER.md](./DEV_TRACKER.md)** | Active issue + Governing CFD |
| **[docs/asset-pipeline-product.md](./docs/asset-pipeline-product.md)** | **Product SoT** — Library + Factory + catalog |
| **[docs/factory-operations.md](./docs/factory-operations.md)** | Binding factory runtime, evidence, recovery, and continuation point |
| **[docs/machine-roles.md](./docs/machine-roles.md)** | Borealis dev-primary / Aurora factory-primary split |
| **[docs/intake-runbook.md](./docs/intake-runbook.md)** | Redeem → Fab → P4 → register |
| **[docs/api-visual-research.md](./docs/api-visual-research.md)** | **Visual Research** collection — Bandit read contract + upload API |
| **[docs/cfd/](./docs/cfd/)** | CFD mirrors + architecture research |
| **[docs/humble-asset-vault-inventory.md](./docs/humble-asset-vault-inventory.md)** | Authoritative **37-item** inventory (keys excluded) |
| **[config/humble-seed.yaml](./config/humble-seed.yaml)** | Seed register (no keys) |
| **[docs/brand-canon.md](./docs/brand-canon.md)** | Control Alt vs Control Alt Games |

## Slice status

- **A (shipped):** register + browse UI, redeem-by green/red, `/api/health`, Compose on `:8770`
- **B (shipped):** IntakeRun propose API + UI (`docs/api-intake.md`)
- **C (shipped):** SQLite job queue + `vellum-worker`; enqueue automatable IntakeRun steps
- **D (shipped):** Axiom Read `#/axiom/vellum` + `?embed=axiom`
- **E (shipped):** Epic Add-to-Project → vault stage (Fireworks pilot); `PATCH /api/assets`; `docs/slice-e-epic-staging.md`
- **F (shipped):** lookdev derive into project lanes (`docs/api-lookdev.md`); Fireworks stills → slots + hail-overlay
- **Now:** **Asset Pipeline Product** (`docs/asset-pipeline-product.md`) —
  curated Library + P4, automatic reconcile, parallel Conversion Factory, and
  game-ready catalog. Intake and baseline extraction are reconciled. The next
  required slice is real Niagara MRQ/Baker output (transparent WebM / sprite
  sheets) proven in a Games runtime. Capture science-project remains frozen as
  `prototype-v0`; Unity reconcile remains parked.


## Visual Research

Reference/inspiration images (PNG, JPG, GIF, SVG, WebP) live in a separate
vault collection from game-ready assets. Operators upload image + source-text
bundles via the **Visual Research** tab; capture tools
`POST /api/visual-research/bundles` with `VELLUM_RESEARCH_WRITE_TOKEN`.
Vellum stores the image while Mneme stores the linked Markdown source text.
Control Alt project agents browse with the read APIs only — see
[`docs/api-visual-research.md`](./docs/api-visual-research.md).

## Boundaries

- Raw assets and keys stay under `/mnt/data/vault/vellum` (private data), never in this repo.
- Product repos consume validated game-ready artifacts, never raw marketplace
  packs. A bake plan is evidence, not a playable artifact.
- Redeem-by expiry is an indicator only — it does not invalidate staged assets.
- Visual Research write token stays on the press / operator tools — never give
  it to Bandit agents.
