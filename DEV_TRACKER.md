# Development Tracker: Vellum

> **Current Active Issue:** Slice B — Intake propose (IntakeRun step plans)
> **Governing CFD:** `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`
> **Next Immediate Step:** Implement IntakeRun propose API + UI against existing register (plan task `task-vellum-slice-b-intake-propose`)

---

## 1. Quick Runbook
*Keep your commands here so you never have to search for them.*

* **UI:** http://192.168.68.93:8770/
* **Health:** `curl -sS http://192.168.68.93:8770/api/health`
* **Compose:** `docker compose up -d --build` (port **8770**)
* **Tests:** `PYTHONPATH=. pytest -q`
* **Governing CFD (Axiom):** `#/axiom/praxis-tracker?inspiration=cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`
* **CFD mirror:** `docs/cfd/README.md`
* **Vault:** `/mnt/data/vault/vellum`
* **GitHub:** https://github.com/AptlyClever/vellum
* **Axiom registry id:** `vellum`

---

## 2. The Active Issue (Do Not Add Steps Here!)

* **What success looks like:** Human or agent can request an intake plan for a register asset; Vellum writes an IntakeRun with ordered steps and honest statuses (pending / blocked / needs-human), without pretending Epic/Unity downloads are fully automated yet.
* **Sub-Tasks:**
  - [ ] IntakeRun model + persistence
  - [ ] Propose endpoint (from asset id / humble source)
  - [ ] Minimal UI to view proposed steps
  - [ ] Agent-usable JSON shape documented

---

## 3. The Parking Lot
*Ideas deferred until the active issue completes.*

* Unity tier contents unresolved until redemption / library inspection.
* Slice C–F per governing CFD plan (workers, Axiom Read nav, drive imports, lookdev derive).
* Optional deeper AI fit-tagging after intake propose exists.

---

## 4. Work History Logs

* **2026-07-12** — Canonized as **Vellum** under Control Alt Games. Project root `/mnt/temp/config/vellum`; vault `/mnt/data/vault/vellum`. Registered in Axiom `apps.registry.yaml`. Handoff docs moved from Axiom `docs/control-alt-games/` salvage into this repo.
* **2026-07-12** — Public GitHub repo [`AptlyClever/vellum`](https://github.com/AptlyClever/vellum); initial canon pushed to `main`.
* **2026-07-12** — Architecture research completed (DAM layers, free lessons, Bandit+Conduit sibling pattern, slices A–F). Canvas + `docs/cfd/architecture-research.md`.
* **2026-07-13** — Governing CFD Inspiration created and plan approved in Axiom: `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`. Discovery + canon evidence attached. Active issue set to Slice A.
* **2026-07-13** — Added `vellum` to handoff `registry/projects.yaml` so Axiom workbench/tracker/bind-cfd can resolve the project.
* **2026-07-13** — **Slice A shipped:** `config/humble-seed.yaml` (37 items, no keys), FastAPI register API, browse UI with redeem-by green/red, Compose on `:8770`, tests green, vault register mirror. Active issue → Slice B.
