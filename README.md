# Vellum

**Vellum** is the Control Alt Games asset vault and visual prototyping accelerator.

It owns ingest, catalog, and reuse of purchased Unreal/Unity game-dev assets (starting with the Humble All-in-One Unreal & Unity GameDev bundle) for Threshold Affairs, Field Command, Hail, LCARD, Slots/Bandit, and Dobsonian work — without dumping raw marketplace packs into product repos or migrating engines.

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
| **[docs/ue-mrq-capture.md](./docs/ue-mrq-capture.md)** | **New:** Unreal MRQ + Sequencer lookdev capture capability |
| **[docs/cfd/](./docs/cfd/)** | CFD mirrors + architecture research |
| **[docs/humble-asset-vault-inventory.md](./docs/humble-asset-vault-inventory.md)** | Authoritative **37-item** inventory (keys excluded) |
| **[config/humble-seed.yaml](./config/humble-seed.yaml)** | Seed register (no keys) |
| **[docs/asset-import-engine.md](./docs/asset-import-engine.md)** | Intake plan (slices B+) |
| **[docs/brand-canon.md](./docs/brand-canon.md)** | Control Alt vs Control Alt Games |

## Slice status

- **A (shipped):** register + browse UI, redeem-by green/red, `/api/health`, Compose on `:8770`
- **B (shipped):** IntakeRun propose API + UI (`docs/api-intake.md`)
- **C (shipped):** SQLite job queue + `vellum-worker`; enqueue automatable IntakeRun steps
- **D (shipped):** Axiom Read `#/axiom/vellum` + `?embed=axiom`
- **E (shipped):** Epic Add-to-Project → vault stage (Fireworks pilot); `PATCH /api/assets`; `docs/slice-e-epic-staging.md`
- **F (shipped):** lookdev derive into project lanes (`docs/api-lookdev.md`); Fireworks stills → slots + hail-overlay
- **Now:** Unreal **MRQ + Sequencer** lookdev capture for Fireworks (`docs/ue-mrq-capture.md`); SceneCapture/HighResShot retired; Unity reconcile parked — host runbook `docs/scratch-inspect-niagara.md`


## Boundaries

- Raw assets and keys stay under `/mnt/data/vault/vellum` (private data), never in this repo.
- Product repos consume derived lookdev only.
- Redeem-by expiry is an indicator only — it does not invalidate staged assets.
