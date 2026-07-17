# Development Tracker: Vellum

> **Current Active Issue:** Asset Pipeline Product — Library + Conversion Factory + game-ready delivery  
> **Governing CFD:** `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in` (slices A–F met; post-CFD track)  
> **Product SoT:** `docs/asset-pipeline-product.md`  
> **Next Immediate Step:** Keep the exclusive VFX render phase healthy in
> Aurora reconcile and extend equivalent quality gates to model, texture, and
> audio outputs. Fireworks VFX now has validated `slots` lane clips.

---

## 1. Quick Runbook

* **UI:** http://192.168.68.93:8770/
* **Axiom Read:** http://192.168.68.93:7895/#/axiom/vellum
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

* **What success looks like:** New packs enter via redeem → Fab Add-to-Project → P4 submit → Vellum register. Factory jobs emit manifested glTF / VFX clips / textures into the vault. Games pull game-ready bundles. A future Unreal title can Migrate from the Library.
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
  - [x] Library project layout + health tooling
  - [x] P4 setup runbook + depot bootstrap scripts
  - [x] Intake runbook (human Fab → P4 → register)
  - [x] CI runner docs + workflow stubs
  - [x] export-models / bake-vfx / export-media factory jobs
  - [x] Reconcile controller: automatic register/stage/P4/inventory/factory loop
  - [x] Combined `factory-all` (one UE boot per pack)
  - [x] Three isolated parallel pack workers + bounded smart uploads
  - [x] Batched game-ready run ingest (no per-element YAML rewrite)
  - [x] Active Fab intake closed: 0 blocked / 0 orphan / 3 deferred Complete Projects
  - [x] Baseline factory evidence for every on-disk pack (parallel drain, 0 exceptions)
  - [x] Game-ready catalog API + UI
  - [x] Acceptance harness doc (Slots win fireworks)
  - [x] Native Unreal title consumption doc
  - [x] Execute Niagara bake plans through MRQ/Niagara Baker
  - [x] Package and validate transparent WebM / sprite sheets
  - [x] Prove one VFX artifact in an actual Games web runtime
  - [x] Add bounded exclusive VFX-render phase to Aurora reconcile
  - [ ] Add durable factory run/progress records to the API/UI
  - [ ] Add equivalent quality gates for model, texture, and audio outputs

---

## 3. The Parking Lot

* Unity tier reconcile (explicitly deferred).
* Optional deeper AI fit-tagging.
* Warm Lookdev Worker (frozen).
* Custom Capture agent as primary control plane (frozen).
* SQLite game-ready catalog migration (before sustained 5,000+ elements).

---

## 4. Work History Logs

* **2026-07-12** — Canonized as **Vellum** under Control Alt Games. Project root `/mnt/temp/config/vellum`; vault `/mnt/data/vault/vellum`. Registered in Axiom `apps.registry.yaml`.
* **2026-07-12** — Public GitHub repo [`AptlyClever/vellum`](https://github.com/AptlyClever/vellum); initial canon pushed to `main`.
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
