# DEV_TRACKER — Vellum (Completion-First Development)

> **Current Active Issue:** Slice A — Register + browse (37 Humble items, redeem-by lights)
> **Governing CFD:** `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`
> **Next Immediate Step:** Implement register + browse web surface against vault/register model (plan task `task-vellum-slice-a-register-browse`)

---

## 1. Quick Runbook

* **Governing CFD (Axiom):** `#/axiom/praxis-tracker?inspiration=cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`
* **CFD mirror:** `docs/cfd/README.md`
* **Architecture research:** `docs/cfd/architecture-research.md`
* **Project root:** `/mnt/temp/config/vellum`
* **Vault:** `/mnt/data/vault/vellum`
* **GitHub:** https://github.com/AptlyClever/vellum
* **Axiom registry id:** `vellum` (base URL empty until HTTP service exists)

---

## 2. The Active Issue (Do Not Add Steps Here!)

* **What success looks like:** Operators (human + agents) can browse a register of the 37 Humble inventory items without keys; redeem-by dates show green before expiry and red after, without invalidating already-staged assets; catalog identity is stable even if folders move.
* **Sub-Tasks:**
  - [ ] Persist register model (seed from inventory doc / vault stub)
  - [ ] Browse/search UI
  - [ ] Redeem-by green/red indicator
  - [ ] Health endpoint + compose packaging (prep for Slice D)

---

## 3. The Parking Lot

* Unity tier contents unresolved until redemption / library inspection.
* Slice B–F per governing CFD plan (intake propose, workers, Axiom Read nav, drive imports, lookdev derive).
* Optional deeper AI fit-tagging after register browse exists.

---

## 4. Work History Logs

* **2026-07-12** — Canonized as **Vellum** under Control Alt Games. Project root `/mnt/temp/config/vellum`; vault `/mnt/data/vault/vellum`. Registered in Axiom `apps.registry.yaml`. Handoff docs moved from Axiom `docs/control-alt-games/` salvage into this repo.
* **2026-07-12** — Public GitHub repo [`AptlyClever/vellum`](https://github.com/AptlyClever/vellum); initial canon pushed to `main`.
* **2026-07-12** — Architecture research completed (DAM layers, free lessons, Bandit+Conduit sibling pattern, slices A–F). Canvas + `docs/cfd/architecture-research.md`.
* **2026-07-13** — Governing CFD Inspiration created and plan approved in Axiom: `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`. Discovery + canon evidence attached. Active issue set to Slice A.
