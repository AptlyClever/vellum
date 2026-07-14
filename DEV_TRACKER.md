# Development Tracker: Vellum

> **Current Active Issue:** Finish the inventory — drain on-disk MRQ, then agent-close the 19 missing Fab downloads (no hand-click homework dump). See **`OPS_NOW.md`**.
> **Governing CFD:** `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in` (slices A–F met; `completion_assessment.met`)
> **Next Immediate Step:** Keep `ue_capture` healthy until On-disk lookdev = 0, then batch-fill VaultCache for the 19 `need_download` packs and `host_fab_install`. Unity parked.

---

## 1. Quick Runbook
*Keep your commands here so you never have to search for them.*

* **UI:** http://192.168.68.93:8770/
* **Axiom Read:** http://192.168.68.93:7895/#/axiom/vellum
* **Scratch / hosts:** `docs/scratch-inspect-niagara.md`
* **UE MRQ capture capability (SoT):** `docs/ue-mrq-capture.md`
* **Capture hosting (binding):** `docs/capture-hosting-decision.md` — Epic batch Cmd  
* **UE Lookdev Worker (FROZEN):** `docs/ue-lookdev-worker.md`
* **Warm worker:** `pwsh -File tools/unreal/host-install/install.ps1 -StartWorkerNow` (service + logon task)
* **Manual worker (debug):** `pwsh -File tools/unreal/vellum_ue_worker.ps1 -Ensure`
* **Recover interrupted MRQ dirs:** `pwsh -File tools/unreal/vellum_ue_agent.ps1 -RecoverOnly`
* **Record scratch:** `POST /api/scratch/record`
* **Upload Niagara still:** `POST /api/lookdev/ingest-render` (multipart)
* **Compose:** `docker compose up -d --build` (port **8770**)
* **Tests:** `PYTHONPATH=. pytest -q`
* **UE hosts:** `config/ue-hosts.json` / `GET /api/ue/hosts` (Aurora active)
* **Governing CFD:** `#/axiom/praxis-tracker?inspiration=cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in`

---

## 2. The Active Issue (Do Not Add Steps Here!)

* **What success looks like:** Operator clicks **Capture** in Vellum; Aurora finishes **the whole Fireworks pack** into lookdev (skipping anything already vaulted). No per-system operator work. After Fireworks: same path for remaining purchased packs.
* **Sub-Tasks:**
  - [x] Job/agent/host plumbing (Aurora preflight resolves UE + `F:\Games\AuroraVellum`)
  - [x] Stop improvising on SceneCapture / HighResShot (2026-07-13)
  - [x] Capability spec: `docs/ue-mrq-capture.md`
  - [x] Lock §12 decisions (B / C / C / C / B)
  - [x] Aurora: Fireworks in `AuroraVellum` at `/Game/FireworksV1` + MRQ/Python plugins
  - [x] Operator will not hand-author Sequencer/MRQ UI — spike/proof is scripted
  - [x] Implement cmdline **MRQ + Sequencer** backend + agent wiring
  - [x] Prove slots + hail-overlay lookdev in vault (recover ingest 2026-07-13: Chrysanthemum/Peony/Willow Single)
  - [x] Batch path: one author + one MoviePipelineQueue MRQ + per-system ingest (`mrq-batch-queue`)
  - [x] Skip vault-covered / local-ready systems; `force` override (`mrq-batch-skip`)
  - [x] Default Capture = **entire pack** (`max_systems=0`, Single-over-Loop) — `mrq-full-pack`
  - [x] Inventory cache + vault-only skip without UE; soft-fail per system (`mrq-pack-resilient`)
  - [x] Host specs report from UE agent → `GET /api/ue/hosts`
  - [x] Lookdev Studio map (permanent photo stage) + capture wiring (`mrq-lookdev-studio`)
  - [x] Aurora **Lookdev Worker** (Option 1): warm UE + loopback capture API (`docs/ue-lookdev-worker.md`)
  - [x] Fireworks pack lookdev complete in vault (all unique systems; skip already-done)
  - [x] Import pack UI + Aurora `host_stage` vault upload (folder picker, Start next, post-stage Derive)
  - [x] Next purchased Unreal packs through Import → Derive/Capture (no operator digging)
  - [x] Agent Fab install: VaultCache → F: Content (`host_fab_install`) + batch coverage UI
  - [x] Fab-thumbnail derive fallback for uasset-only stages (`data/fab-listings.db`) — env packs get vault heroes without operator stills
  - [x] Coverage inventory fast path (no per-asset lookdev scan)
  - [ ] Niagara/VFX `ue_capture` drain for free orphans (Basic VFX / Free Niagara / Vefects) + any packs still without MRQ
  - [ ] Metal Material 3 catalog thumb missing from Fab listings export (uasset-only; optional later)
  - [ ] ~19 Humble Unreal packs still need Epic Fab download (hard wall) before install/stage
  - [ ] Unity: unpark stage + texture derive per `docs/unity-intake-unpark.md` (VFX capture still later)

---

## 3. The Parking Lot
*Ideas deferred until the active issue completes.*

* Unity tier: was parked for Fireworks MRQ focus — **rethink** in `docs/unity-intake-unpark.md` (stage + texture derive first; VFX capture still later).
* Optional deeper AI fit-tagging.
* ~~Deeper Movie Render Queue~~ → **promoted to active** (was parking-lot improvisation deferral; now the capture backend).

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
* **2026-07-13** — Aurora Capture `job-20260713-181144-c1ce27`: host OK, `systems_found=0` / `no_systems_to_bake` (Fireworks not in project yet). Operator: **stop** SceneCapture/HighResShot improvisation; do **not** cut scope to flipbook-only; next capture backend is **MRQ + Sequencer** (full lookdev fidelity).
* **2026-07-13** — Capability documented: `docs/ue-mrq-capture.md` (new functionality SoT — control/host/agent keep; MRQ+Sequencer capture backend to build; §12 open decisions).
* **2026-07-13** — §12 locked: outputs **B**, duration/framing **C**, executor **C**, content-root **C**, multi-lane **B** (slots+hail-overlay).
* **2026-07-13** — Aurora: Fireworks at `/Game/FireworksV1`; MRQ + Python plugins on. Operator declined manual Sequencer/MRQ UI spike — proof path is **fully scripted**; Capture stays Vellum UI + agent only.
* **2026-07-13** — Implemented scripted **mrq-sequencer** runner: inventory (+ `/Game` fallback), author map/sequence/MRQ config, cmdline MRQ, mid+max-luma heroes, sequence zip ingest to **slots** + **hail-overlay**.
* **2026-07-13** — Transient-actor bug fixed (`spawn_* …, True` was `transient=True`); persistent actors + spawnables → non-black MRQ frames.
* **2026-07-13** — Interrupted job recover: 3 systems × slots+hail-overlay heroes/sequences ingested (`Recover done ok=True systems=3 ingested=18`). Validated max_luma peaks 113–198 via lookdev `/file`.
* **2026-07-13** — Phase B optimization: batch author + MoviePipelineQueue + **per-system ingest** (`mrq-batch-queue`).
* **2026-07-13** — Skip already-captured systems (`mrq-batch-skip`): vault lookdev on slots+hail-overlay, or local good MRQ → ingest-only; `force` / Force re-render / `-ForceCapture`.
* **2026-07-13** — Reset Capture default to **entire pack** (`mrq-full-pack`, `max_systems=0`); drop `*_Loop` when `*_Single` sibling exists. Operator path: click Capture once; no per-system digging.
* **2026-07-13** — Live import panel on asset detail (job progress + lookdev refresh).
* **2026-07-13** — `mrq-pack-resilient`: inventory cache (skip UE cold start), continue on black/ingest failure, host specs POST from agent.
* **2026-07-13** — **Lookdev Studio** (`mrq-lookdev-studio`): permanent photo-studio map (`VellumLookdevStudio`) with center slot + lights + mid cam; capture defaults to 60 frames (~2s); Phase 0 builds studio once. Old void stills inconsistent — Force re-render for pack.
* **2026-07-13** — Adaptive per-system frame estimate (`mrq-adaptive-frames`), max 4s / 120 frames.
* **2026-07-14** — **Capture hosting rebound:** Epic batch Cmd (`run_vellum_capture.ps1`) is primary per Epic MRQ command-line tutorial. Warm Lookdev Worker **frozen** (`docs/capture-hosting-decision.md`). Not an operator pick.
* **2026-07-13** — **Option 1 locked (later frozen):** Aurora Lookdev Worker warm path — superseded 2026-07-14 by capture-hosting-decision.
* **2026-07-13** — Host wrappers: WinSW service `VellumUeAgent` + At-logon/watchdog tasks (`tools/unreal/host-install/`) so Capture is not console-babysat.
* **2026-07-14** — Import polish: Content folder picker (`host_scan` + `GET …/content-folders`), `host_stage` (Unity-capable; `ue_stage` alias), home **Start next pack**, post-stage **Derive texture stills** CTA. Live: `FireworksV1` + `Vellum` on Aurora.
* **2026-07-14** — Fab trust fix: packs were landing in retired `C:\dev\AuroraVellum`; consolidated → `F:\Games\AuroraVellum`, renamed typo uproject, deleted C:\dev dump. Mark/Stage require scanned folder paths.
* **2026-07-14** — **Finish post-CFD Unreal on F:** agent Fab install + stage hang fix + orphan register. **Lookdev:** Fab catalog thumbnail derive for uasset-only packs (19/23 staged now have vault heroes). Coverage API fast path. Remaining: 3 free Niagara captures + Metal Material catalog gap + ~19 Humble packs still need Epic download. Unity parked.
