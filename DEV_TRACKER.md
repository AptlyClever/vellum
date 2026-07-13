# Development Tracker: Vellum

> **Current Active Issue:** Fireworks — Niagara SceneCapture stills on **Aurora** (primary host)
> **Governing CFD:** `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in` (slices A–F met; this is the post-CFD track)
> **Next Immediate Step:** `git pull` on Aurora → restart agent → confirm preflight finds `F:\Games\AuroraVellum\AuroraVellum.uproject` → Capture from Vellum

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

* **What success looks like:** From Vellum UI alone, enqueue Unreal capture on **Aurora**; Lookdev gets distinct `niagara-render` stills that show Fireworks particles (not pure black, not only a debug cube).
* **Sub-Tasks:**
  - [x] `POST /api/ue/capture` + claim/report for Windows agent
  - [x] UI **Capture from Unreal** button
  - [x] `vellum_ue_agent.ps1` poll loop
  - [x] Borealis smoke: agent + Capture (`job-20260713-062514-5e88d4`) — pipeline OK; stills were debug cube / black (host issues; stop investing here)
  - [x] Host profiles: `config/ue-hosts.json` (aurora active / borealis secondary) + `GET /api/ue/hosts`
  - [x] Aurora project path: `F:\Games\AuroraVellum`
  - [ ] Aurora: Fireworks in project + Python Editor Script Plugin
  - [ ] Aurora: agent preflight OK + Capture
  - [ ] Confirm stills show real Niagara particles (not cube-only / not pure black)

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
* **2026-07-13** — `-game` HighResShot abandoned (blank window / zero PNGs). Switched to editor SceneCapture2D → `export_render_target` (`editor-scenecapture-noblack`). Pure-black exports rejected.
* **2026-07-13** — **Verified on Borealis:** pipeline OK (`job-20260713-062514-5e88d4`, 3 stills ingested). Earlier batch pure black; latest batch gray debug cube only — Niagara particles missing. Operator: stop Borealis capture debug; switch UE agent host to **Aurora**.
* **2026-07-13** — Aurora first Capture failed (`job-20260713-174728-597c9c`): `UnrealEditor-Cmd.exe not found` — UE not under `C:\Program Files\Epic Games`; job payload still Borealis `C:\epic\VellumImport`. Agent/runner now discover E:/D: installs + registry; support `VELLUM_UE_CMD` / `VELLUM_UE_PROJECT` (`aurora-ue-discovery`).
* **2026-07-13** — **UE host profiles:** `config/ue-hosts.json` — Aurora primary (`F:\Games\UE_5.8\…\UnrealEditor.exe`, derives `-Cmd`), Borealis secondary; `active: aurora`. Shared `tools/unreal/ue-hosts.ps1`; agent `-HostName` / `VELLUM_UE_HOST`; API `GET /api/ue/hosts`; UI defaults to active host.
* **2026-07-13** — Aurora scratch project path set to `F:\Games\AuroraVellum`.
