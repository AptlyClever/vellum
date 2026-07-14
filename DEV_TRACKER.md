# Development Tracker: Vellum

> **Current Active Issue:** Asset Pipeline Product — Library + Conversion Factory + game-ready delivery  
> **Governing CFD:** `cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in` (slices A–F met; post-CFD track)  
> **Product SoT:** `docs/asset-pipeline-product.md`  
> **Next Immediate Step:** Run Library health + P4 first submit; land first `bake-vfx` / `export-models` CI jobs on Aurora

---

## 1. Quick Runbook

* **UI:** http://192.168.68.93:8770/
* **Axiom Read:** http://192.168.68.93:7895/#/axiom/vellum
* **Product SoT:** `docs/asset-pipeline-product.md`
* **Intake runbook:** `docs/intake-runbook.md`
* **Library layout:** `docs/library-project.md`
* **Native title pattern:** `docs/native-unreal-titles.md`
* **Pipeline jobs:** `tools/pipeline/` (`export-models`, `bake-vfx`, `export-media`)
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
  - [x] Game-ready catalog API + UI
  - [x] Acceptance harness doc (Slots win fireworks)
  - [x] Native Unreal title consumption doc

---

## 3. The Parking Lot

* Unity tier reconcile (explicitly deferred).
* Optional deeper AI fit-tagging.
* Warm Lookdev Worker (frozen).
* Custom Capture agent as primary control plane (frozen).

---

## 4. Work History Logs

* **2026-07-12** — Canonized as **Vellum** under Control Alt Games. Project root `/mnt/temp/config/vellum`; vault `/mnt/data/vault/vellum`. Registered in Axiom `apps.registry.yaml`.
* **2026-07-12** — Public GitHub repo [`AptlyClever/vellum`](https://github.com/AptlyClever/vellum); initial canon pushed to `main`.
* **2026-07-12…13** — Architecture research + Governing CFD; slices A–F shipped (register → intake → worker → Axiom Read → Epic stage Fireworks → texture lookdev).
* **2026-07-13** — Capture science project: HighResShot → SceneCapture → MRQ+Sequencer → Lookdev Worker → Epic batch Cmd firefighting (87 commits in ~48h).
* **2026-07-14** — **Product pivot:** freeze Capture prototype as `prototype-v0`; Asset Pipeline Product SoT (`docs/asset-pipeline-product.md`) — Library + P4 + Conversion Factory + game-ready catalog; keep path open for native Unreal titles.
