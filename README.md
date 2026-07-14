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
| **[docs/intake-runbook.md](./docs/intake-runbook.md)** | Redeem → Fab → P4 → register |
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
- **Now:** **Asset Pipeline Product** (`docs/asset-pipeline-product.md`) — curated Library + P4, Conversion Factory (`tools/pipeline/`), game-ready catalog. Capture science-project frozen as `prototype-v0`. Unity reconcile parked.


## Boundaries

- Raw assets and keys stay under `/mnt/data/vault/vellum` (private data), never in this repo.
- Product repos consume derived lookdev only.
- Redeem-by expiry is an indicator only — it does not invalidate staged assets.
