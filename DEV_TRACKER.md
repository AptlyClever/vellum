# Development Tracker: Vellum

> **Current Active Issue:** *(none — slices A–F complete)*
> **Governing CFD:** `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`
> **Next Immediate Step:** Operator levelset / next Inspiration (Unity tier reconcile, scratch inspect, or deeper Niagara renders)

---

## 1. Quick Runbook
*Keep your commands here so you never have to search for them.*

* **UI:** http://192.168.68.93:8770/
* **Axiom Read:** http://192.168.68.93:7895/#/axiom/vellum
* **Health:** `curl -sS http://192.168.68.93:8770/api/health`
* **Derive lookdev:** `curl -sS -X POST http://192.168.68.93:8770/api/lookdev/derive -H 'Content-Type: application/json' -d '{"asset_id":"fireworks-vol-1-niagara","lanes":["slots","hail-overlay"]}'`
* **Lookdev outputs:** `curl -sS 'http://192.168.68.93:8770/api/lookdev/outputs?asset_id=fireworks-vol-1-niagara'`
* **Epic staging runbook:** `docs/slice-e-epic-staging.md`
* **Lookdev API:** `docs/api-lookdev.md`
* **Compose:** `docker compose up -d --build` (app + worker, port **8770**)
* **Tests:** `PYTHONPATH=. pytest -q`
* **Governing CFD:** `#/axiom/praxis-tracker?inspiration=cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`

---

## 2. The Active Issue (Do Not Add Steps Here!)

* **What success looks like:** *(plan A–F complete — pick next Inspiration)*
* **Sub-Tasks:**
  - [x] Slices A–F shipped

---

## 3. The Parking Lot
*Ideas deferred until the active issue completes.*

* Unity tier contents unresolved until redemption / library inspection.
* Scratch Unreal inspect + real Niagara viewport renders (beyond texture stills).
* Optional deeper AI fit-tagging.

---

## 4. Work History Logs

* **2026-07-12** — Canonized as **Vellum** under Control Alt Games. Project root `/mnt/temp/config/vellum`; vault `/mnt/data/vault/vellum`. Registered in Axiom `apps.registry.yaml`. Handoff docs moved from Axiom `docs/control-alt-games/` salvage into this repo.
* **2026-07-12** — Public GitHub repo [`AptlyClever/vellum`](https://github.com/AptlyClever/vellum); initial canon pushed to `main`.
* **2026-07-12** — Architecture research completed (DAM layers, free lessons, Bandit+Conduit sibling pattern, slices A–F). Canvas + `docs/cfd/architecture-research.md`.
* **2026-07-13** — Governing CFD Inspiration created and plan approved in Axiom. Discovery + canon evidence attached.
* **2026-07-13** — Added `vellum` to handoff `registry/projects.yaml`; Axiom mount + bind-cfd verified.
* **2026-07-13** — **Slice A shipped:** register + browse + redeem-by lights on `:8770`.
* **2026-07-13** — **Slice B shipped:** IntakeRun propose/list/get/patch-step API; honest needs-human/blocked steps; detail UI “Propose intake”; `docs/api-intake.md`. Active issue → Slice C.
* **2026-07-13** — **Slice C shipped:** SQLite jobs + `vellum-worker`; enqueue automatable steps; job status API/UI. Epic/Unity stay needs-human. Active issue → Slice D.
* **2026-07-13** — **Slice D shipped:** Axiom Read nav `#/axiom/vellum` (Shell hardcode + registry embed); Vellum `?embed=axiom` chrome. Active issue → Slice E.
* **2026-07-13** — **Slice E shipped:** Fireworks Vol. 1 Niagara Epic Add-to-Project → vault stage (~115 files / 609M); intake human gates marked done; `PATCH /api/assets`; runbook `docs/slice-e-epic-staging.md`. Active issue → Slice F.
* **2026-07-13** — **Slice F shipped:** DerivedOutput + lanes; `derive_lookdev` job copies preview stills into `04-lookdev` / `05-derived-renders` (Fireworks → slots + hail-overlay); UI grid + `docs/api-lookdev.md`. Plan A–F complete.
