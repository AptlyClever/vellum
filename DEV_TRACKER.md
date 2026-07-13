# Development Tracker: Vellum

> **Current Active Issue:** Fireworks — Vellum UI → UE agent capture
> **Governing CFD:** `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`
> **Next Immediate Step:** Start `tools/unreal/vellum_ue_agent.ps1` on the Windows UE box; click **Capture from Unreal** in Vellum

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

* **What success looks like:** From Vellum UI alone, enqueue Unreal capture; background Windows agent runs UE and stills appear in Lookdev.
* **Sub-Tasks:**
  - [x] `POST /api/ue/capture` + claim/report for Windows agent
  - [x] UI **Capture from Unreal** button
  - [x] `vellum_ue_agent.ps1` poll loop
  - [ ] Operator: start agent once on UE box + first Capture click
  - [ ] Improve Niagara framing in `vellum_capture.py` after first success

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
* **2026-07-13** — Automation-first capture: `tools/unreal/run_vellum_capture.ps1` drives UnrealEditor-Cmd + posts results to Vellum (manual UI is fallback only).
* **2026-07-13** — UI-first: **Capture from Unreal** enqueues `ue_capture`; Windows `vellum_ue_agent.ps1` polls/claims/runs (operator stays in Vellum).
