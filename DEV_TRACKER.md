# Development Tracker: Vellum

> **Current Active Issue:** Control Alt Games Platform & Solo-Operator Workflow Expansion  
> **Governing CFD:** `cfd-inspiration-20260722-215000-control-alt-games-platform-expansion`  
> **Product SoT:** `docs/asset-pipeline-product.md`  
> **Next Immediate Step:** Phase 1: Establish Inter-System Architecture & Proscenium Presentation Contracts.

---

## 1. Quick Runbook

* **UI:** http://192.168.68.93:8770/
* **Proscenium UI:** http://192.168.68.93:8788/
* **Axiom Hub:** http://192.168.68.93:7895/
* **Product SoT:** `docs/asset-pipeline-product.md`
* **Intake runbook:** `docs/intake-runbook.md`
* **Library layout:** `docs/library-project.md`
* **Native title pattern:** `docs/native-unreal-titles.md`
* **Pipeline jobs:** `tools/pipeline/` (`factory-all`, `export-models`, `bake-vfx`, `export-media`)
* **Factory operating contract:** `docs/factory-operations.md`
* **CI runner (Aurora):** `tools/pipeline/ci/README.md`
* **Compose:** `docker compose up -d --build` (port **8770**)
* **Tests:** `PYTHONPATH=. pytest -q`
* **UE hosts:** `config/ue-hosts.json` / `GET /api/ue/hosts` (Aurora active)
* **Prototype freeze tag:** `prototype-v0` (archive under `archive/prototype-v0/`)

---

## 2. The Active Issue (Do Not Add Steps Here!)

* **What success looks like:** A unified, machine-owned Control Alt Games platform and workflow where Vellum converts and vaults 3D/audio assets; Proscenium acts as the home presentation authority and live stage viewport; Eidolon and Mneme supply concept art and lore briefs; automated background sync delivers manifested assets directly into Field Ops and Threshold Affairs Godot repos on dev-ubuntu; and headless engine validation guarantees 0 import errors.
* **Stopped (do not resume without operator unpark):**
  - Warm Lookdev Worker (`Unpark: Lookdev Worker`)
  - Custom `VellumUeAgent` polling Capture control plane (`Unpark: Capture Agent`)
  - `-game` + `HighResShot`; SceneCapture bake path
* **Keep:**
  - Vellum register / intake / jobs / lookdev ingest APIs (vault catalog)
  - Host profiles in `config/ue-hosts.json`
  - Epic Cmd MRQ **as bake-vfx job technology**
  - Vault under `/mnt/data/vault/vellum` (never keys/raw packs in git)
* **Sub-Tasks:**
  - [x] Freeze Capture prototype (`prototype-v0`); archive scratch; retire agent tasks
  - [x] Product decision SoT (`docs/asset-pipeline-product.md`)
  - [x] Baseline factory evidence for every on-disk pack
  - [x] Execute Niagara bake plans through MRQ / Niagara Baker
  - [x] Prove VFX artifact in Games web runtime (`slots`)
  - [x] Uncouple Dobsonian games into `godot-field-ops` and `godot-threshold-affairs` lanes
  - [x] Add ORM texture bakes, Ogg audio conversion, prop search, Unity pack extractor, `vellum pull` CLI, and Godot addon
  - [x] Conduct empirical workspace discovery across Proscenium, Axiom, Eidolon, Mneme, LCARD, and Vellum repos
  - [x] Bind & supplement Governing CFD (`cfd-inspiration-20260722-215000-control-alt-games-platform-expansion`)
  - [ ] **Phase 1: Inter-System Architecture & Proscenium Presentation Contracts** — Register `godot-field-ops` and `godot-threshold-affairs` in Proscenium's `delivery-targets.json` using `delivery.py`
  - [ ] **Phase 2: Machine-Owned Lane Delivery Engine** — Implement `lane_sync` job kind in Vellum's `backend/jobs.py` SQLite queue to deliver assets to Godot repos on `dev-ubuntu`
  - [ ] **Phase 3: Headless Engine Import & Quality Verification** — Implement `headless_verify` job kind for `godot --headless` scanning for 0 import errors on `dev-ubuntu`
  - [ ] **Phase 4: Proscenium Stage & Presentation Integration for Dobsonian Games** — Wire game event stings from Field Ops and Threshold Affairs into Proscenium display targets (`overlay-apk` & room screens)
  - [ ] **Phase 5: Axiom Studio Leaf & Unified Production Briefs** — Deliver Axiom Studio Leaf (`praxis-games`) presenting Eidolon art + Mneme lore + Vellum assets + Proscenium stage preview

---

## 3. Discovered Reuse Infrastructure

* **Proscenium Presentation Delivery (`proscenium/backend/presentation/delivery.py`):** `deliver_product_action()` is 100% reused to deliver Hails and overlays to Android TV (`overlay-apk/`) targets.
* **Vellum SQLite Job Engine (`vellum/backend/jobs.py`):** `data/jobs.sqlite3` queue is 100% reused to execute `lane_sync` and `headless_verify` background jobs.
* **Axiom App Registry (`ctrl-alt-axiom/config/apps.registry.yaml`):** Leaf contract and Theme SoT (`GET /api/effective/{app_id}`) are 100% reused for Studio Leaf registration.
* **Eidolon & Mneme Read APIs (`ctrl-alt-eidolon` & `mneme`):** `GET /api/batches` and `GET /api/documents` are 100% reused for Production Briefs.

---

## 4. The Parking Lot

* Unity tier reconcile (explicitly deferred).
* Optional deeper AI fit-tagging.
* Warm Lookdev Worker (frozen).
* Custom Capture agent as primary control plane (frozen).
* SQLite game-ready catalog migration (before sustained 5,000+ elements).

---

## 4. Work History Logs

* **2026-07-12** — Canonized as **Vellum** under Control Alt Games. Project root `/mnt/temp/config/vellum`; vault `/mnt/data/vault/vellum`. Registered in Axiom `apps.registry.yaml`.
* **2026-07-12** — Public GitHub repo [`AptlyClever/vellum`](https://github.com/AptlyClever/vellum); initial canon pushed to `main`.
* **2026-07-22** — **Godot 4.3 end-to-end import verification.** Installed Godot
  4.3 stable (`77dcf97d8`) on dev-ubuntu. Created Godot 4.3 project skeletons at
  `/mnt/temp/config/godot-field-ops` and `/mnt/temp/config/godot-threshold-affairs`
  with Vellum addon pre-installed. `godot --headless --import --quit` ran clean
  (exit 0) on both projects. `vellum pull --lane godot-field-ops` fetched 1
  published texture into `assets/vellum/texture/`; post-pull headless re-import
  confirmed Godot processed it to `.ctex` in `.godot/imported/`. Addon
  (`vellum_plugin.gd` + dock) in-tree for both projects.
* **2026-07-12…13** — Architecture research + Governing CFD; slices A–F shipped (register → intake → worker → Axiom Read → Epic stage Fireworks → texture lookdev).
* **2026-07-13** — Capture science project: HighResShot → SceneCapture → MRQ+Sequencer → Lookdev Worker → Epic batch Cmd firefighting (87 commits in ~48h).
* **2026-07-14** — **Product pivot:** freeze Capture prototype as `prototype-v0`; Asset Pipeline Product SoT (`docs/asset-pipeline-product.md`) — Library + P4 + Conversion Factory + game-ready catalog; keep path open for native Unreal titles.
* **2026-07-14** — Closed active Fab intake: asset-package packs reconciled;
  three Complete Project listings classified as deferred/non-blocking; accepted
  known Dungeon Ruins and legacy Paragon UE4 debt.
* **2026-07-14** — Productized Aurora reconcile: launcher catalog truth,
  orphan/register repair, vault stage, P4, inventory/load validation, and
  machine-owned conversion. Retired "need lookdev" as an operator state.
* **2026-07-14** — Optimized and verified the factory: one Unreal boot per
  pack, three isolated parallel workers, synchronous Asset Registry scan,
  UE 5.8 texture export, smart ZIP, and batched hub ingest. Final drain
  processed 23 packs with 0 exceptions; all on-disk packs have baseline
  game-ready catalog evidence.
* **2026-07-16** — Proved Fireworks Niagara VFX end-to-end on Aurora:
  MRQ rendered 31 systems, pack validation accepted 16 systems, hub ingest
  replaced `FireworksV1`, and `slots` now has 32 validated clips (contained +
  breakout) with zero invalid lane rows. Added a bounded exclusive reconcile
  phase for future bake-plan -> MRQ -> pack -> upload -> publish runs.
