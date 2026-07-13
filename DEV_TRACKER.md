# Development Tracker: Vellum

> **Current Active Issue:** Fireworks — Unreal scratch inspect → Niagara render stills
> **Governing CFD:** `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`
> **Next Immediate Step:** Operator opens `C:\epic\VellumImport`, confirms Niagara systems, records scratch in UI; then upload viewport stills

---

## 1. Quick Runbook
*Keep your commands here so you never have to search for them.*

* **UI:** http://192.168.68.93:8770/
* **Axiom Read:** http://192.168.68.93:7895/#/axiom/vellum
* **Scratch + Niagara runbook:** `docs/scratch-inspect-niagara.md`
* **Record scratch:** `POST /api/scratch/record`
* **Upload Niagara still:** `POST /api/lookdev/ingest-render` (multipart)
* **Compose:** `docker compose up -d --build` (port **8770**)
* **Tests:** `PYTHONPATH=. pytest -q`
* **Governing CFD:** `#/axiom/praxis-tracker?inspiration=cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`

---

## 2. The Active Issue (Do Not Add Steps Here!)

* **What success looks like:** Fireworks scratch inspect recorded; at least one true Niagara viewport still ingested as `niagara-render` (separate from texture lookdev).
* **Sub-Tasks:**
  - [x] Scratch record API + UI + runbook
  - [x] Niagara render upload ingest
  - [ ] Operator confirms systems in Unreal + records scratch
  - [ ] Operator uploads ≥1 Niagara viewport still

---

## 3. The Parking Lot
*Ideas deferred until the active issue completes.*

* Unity tier reconcile (explicitly deferred).
* Deeper Movie Render Queue / automated UE captures.
* Optional deeper AI fit-tagging.

---

## 4. Work History Logs

* **2026-07-12** — Canonized as **Vellum** under Control Alt Games. Project root `/mnt/temp/config/vellum`; vault `/mnt/data/vault/vellum`. Registered in Axiom `apps.registry.yaml`. Handoff docs moved from Axiom `docs/control-alt-games/` salvage into this repo.
* **2026-07-12** — Public GitHub repo [`AptlyClever/vellum`](https://github.com/AptlyClever/vellum); initial canon pushed to `main`.
* **2026-07-12** — Architecture research completed (DAM layers, free lessons, Bandit+Conduit sibling pattern, slices A–F). Canvas + `docs/cfd/architecture-research.md`.
* **2026-07-13** — Governing CFD Inspiration created and plan approved in Axiom. Discovery + canon evidence attached.
* **2026-07-13** — Added `vellum` to handoff `registry/projects.yaml`; Axiom mount + bind-cfd verified.
* **2026-07-13** — **Slices A–F shipped** (register → intake → worker → Axiom Read → Epic stage Fireworks → lookdev texture stills).
* **2026-07-13** — **Next track:** Unreal scratch inspect + Niagara viewport stills for Fireworks; Unity reconcile parked. APIs `/api/scratch/record`, `/api/lookdev/ingest-render`; `docs/scratch-inspect-niagara.md`.
