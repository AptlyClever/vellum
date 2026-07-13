# Vellum — asset import / intake engine

**Project:** Vellum (`/mnt/temp/config/vellum`) · **Vault:** `/mnt/data/vault/vellum` · **Brand home:** Control Alt Games  
**Status:** salvaged handoff (planning record; first slice not built)  
**Salvaged:** 2026-07-12  
**Provenance:** closed [praxis#145](https://github.com/AptlyClever/praxis/pull/145) (`mara/control-alt-games-asset-import-engine-signal`), formerly `objects/signals/control-alt-games-asset-import-engine.md` (Signal revision 1, captured 2026-07-01). Closed 2026-07-07 with the same ledger-archive reason as #144.  
**Inventory source:** [humble-asset-vault-inventory.md](./humble-asset-vault-inventory.md) (37 key-list entries)  
**Related:** [brand canon](./brand-canon.md) · [project README](../README.md)

**Intent (from original):** a repeatable redeem → stage → inspect → tag fit → derive artifact → record trail pipeline — **not** a full asset-management product on day one. Proposed first slice: local intake runner + vault skeleton + register for all 37 Humble items, no raw assets in git.

**Note on obsolete paths:** Step 1 still mentions creating `objects/protocols/...`. That Praxis object path is archived. Prefer durable docs in this Vellum repo when implementation starts.

---

## Metadata

| Field | Value |
| --- | --- |
| id | `signal-control-alt-games-asset-import-engine` |
| type | `praxis.signal` |
| status | `captured` |
| revision | `1` |
| created | `2026-07-01` |
| updated | `2026-07-01` |
| product_area | `Control Alt Games / Assets / Import / Unreal / Unity / Fab / Hail / LCARD / Slots / Dobsonian Universe` |
| possible_destinations | `response`, `protocol`, `registry`, `fiber`, `directive`, `readout`, `tooling` |
| related_signal | `signal-control-alt-games-humble-unreal-unity-asset-vault` |
| related_signal_context | `signal-control-alt-brand-architecture-games-label-canon` |
| related_projects | `Control Alt Games`, `LCARD`, `Hail Platform`, `Slots v0`, `Dobsonian Universe`, `Threshold Affairs`, `Field Command` |
| supersedes | none |
| superseded_by | none |

## Captured idea

The operator wants a plan for an **import engine of some sort** so purchased game-development assets can be brought into Control Alt Games quickly later, without forgetting the workflow and without damaging existing project repositories.

The immediate need is not a full asset-management product. The first useful thing is a repeatable intake/staging/import pipeline that can:

- track redeemed assets,
- record where the raw packages live,
- inspect what each asset contains,
- stage assets in private vault folders,
- create small Unreal or Unity scratch projects for inspection,
- generate project-fit notes,
- produce derived renders/clips/symbol sheets,
- avoid committing raw third-party assets into app repos,
- leave a Praxis trail of what was imported and why.

## Why this matters

The Humble bundle creates a real follow-through risk: assets can be redeemed, downloaded, and then forgotten because each engine has its own library/import workflow.

The import engine should make the next step obvious:

> Redeem asset -> stage raw package -> inspect in scratch project -> tag usefulness -> generate derived artifact -> record Readout -> only then decide whether a real project consumes it.

This keeps Control Alt Games moving without turning Unity/Unreal asset management into a permanent swamp.

## External implementation references

### Fab / Epic assets

Epic's Fab documentation says product keys can be redeemed through the Epic code redemption page and then downloaded from the Epic Games Launcher, Fab library, or Fab plugin. It also states that UE and UEFN products must be downloaded into a project from the Fab integration or Epic Games Launcher for UE formats.

The same documentation says Fab in Launcher can export downloaded files to several DCC/game-engine targets, including Unreal Engine, Unity, Maya, 3ds Max, Blender, and Cinema 4D.

Source:

`https://dev.epicgames.com/documentation/en-us/fab/purchasing-and-downloading-assets-in-fab`

### Unreal import automation

Unreal's Python API includes `unreal.AssetImportTask`, which contains data for a group of assets to import and exposes properties such as `automated`, `destination_path`, `filename`, `imported_object_paths`, `replace_existing`, and `save`.

Unreal's Interchange Framework is described as a file-format-agnostic, asynchronous, customizable import/export framework. It supports customizable pipeline stacks and can be used through C++, Blueprint, or Python. Epic's documentation specifically describes importing assets using Python through Interchange and checking file extensions such as `.glb`, `.gltf`, `.fbx`, and `.usd`.

Sources:

`https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/AssetImportTask?application_version=5.6`

`https://dev.epicgames.com/documentation/en-us/unreal-engine/importing-assets-using-interchange-in-unreal-engine`

### Unity import path

Unity's manual says local asset packages are `.unitypackage` files and can be imported into a project through `Assets > Import Package > Custom Package`. Unity places imported contents into the project's `Assets` folder.

Source:

`https://docs.unity3d.com/Manual/AssetPackagesImport.html`

## Proposed terminology

Use **asset import engine** for the broad concept.

Use **asset intake runner** for the first implementation slice.

Use **import engine** only after automation exists beyond manual checklists.

The first useful thing should not try to solve every engine. It should be a practical local runner plus documented workflow.

## Proposed system shape

### Scope v0 — Asset intake runner

A local CLI/scripted workflow that creates/updates asset intake records and filesystem staging paths.

Suggested command shape:

```text
vellum intake add --source humble --name "Portal VFX Enhanced" --engine unreal --store epic
vellum intake stage --asset portal-vfx-enhanced --raw-path /path/to/download
vellum intake inspect --asset portal-vfx-enhanced
vellum intake fit --asset portal-vfx-enhanced --project threshold-affairs --lane evidence-render
vellum intake readout --asset portal-vfx-enhanced
```

This does not need to import into Unreal automatically on day one. It should first prevent loss of asset identity, source, license, and intended use.

### Scope v1 — Unreal scratch project importer

Create a local Unreal scratch project dedicated to Control Alt Games asset inspection.

Possible path:

`/mnt/data/vault/vellum/03-scratch-projects/unreal/cag_asset_inspection/`

The runner can later generate Python scripts for Unreal Editor that use `unreal.AssetImportTask` or Interchange where applicable.

For Fab / Epic Marketplace content, the first phase may still require manual download/add-to-project through Epic Games Launcher or Fab integration. The import engine should record that step instead of pretending all marketplace ingestion can be fully automated.

### Scope v2 — Unity scratch project importer

Create a Unity scratch project dedicated to asset inspection.

Possible path:

`/mnt/data/vault/vellum/03-scratch-projects/unity/cag_asset_inspection/`

The runner should record `.unitypackage` locations and import outcomes. Unity-specific automation should wait until the exact Unity tier contents are known.

### Scope v3 — Derived artifact pipeline

Once assets are visible in scratch projects, the engine should help produce derived outputs:

- screenshots,
- short clips,
- symbol sheets,
- project-fit contact sheets,
- Hail/LCARD background cards,
- Threshold Affairs evidence stills,
- Field Command reference stills.

Derived artifacts can be copied into project-specific lookdev folders. Raw marketplace assets stay in private source/staging folders.

## Proposed vault layout

```text
/mnt/data/vault/vellum/
  00-admin/
    licenses/
    redemption-log.md
    do-not-commit-raw-assets.md
  01-source-bundles/
    humble-all-in-one-unreal-unity-gamedev/
      epic-unreal/
      unity-tier/
  02-index/
    asset-register.yaml
    project-fit-notes.md
    import-runs/
  03-scratch-projects/
    unreal/
      cag_asset_inspection/
    unity/
      cag_asset_inspection/
  04-lookdev/
    threshold-affairs/
    field-command/
    slots/
    hail-overlay/
    lcard/
  05-derived-renders/
    threshold-affairs/
    field-command/
    slots/
    hail-overlay/
  06-readouts/
  99-quarantine/
```

## Proposed asset register shape

```yaml
assets:
  - id: portal-vfx-enhanced
    display_name: Portal VFX Enhanced
    source_bundle: humble-all-in-one-unreal-unity-gamedev
    store_lane: epic-games-store
    engine: unreal
    package_type: vfx
    redemption_deadline: 2027-07-06T11:00:00-07:00
    redemption_status: not_recorded_in_praxis
    raw_location: pending
    scratch_project_status: pending
    license_note_status: pending
    allowed_lanes:
      - threshold-affairs-evidence
      - hail-stinger
      - field-command-anchor-effect
    blocked_lanes:
      - raw-public-repo-commit
      - ai-training
    first_experiment: threshold-affairs-case-0001-evidence-still
```

## Import engine responsibilities

### Must do

- Record asset identity.
- Record source bundle and store lane.
- Record redemption deadline and redemption status without recording keys.
- Record raw local path once downloaded.
- Record license/EULA note status.
- Record intended project-fit lanes.
- Create scratch-project staging paths.
- Generate import-run records.
- Generate Readout skeletons after experiments.
- Keep raw assets out of product repos.

### Should do later

- Generate Unreal Python import scripts for file-based formats.
- Generate Interchange pipeline notes for Unreal imports.
- Track derived screenshots/clips/symbol sheets.
- Generate contact sheets for asset review.
- Provide an Axiom-readable asset index.

### Must not do

- Store Humble/Epic/Unity keys.
- Circumvent launcher, marketplace, DRM, EULA, or redemption flows.
- Scrape private marketplace APIs.
- Commit raw third-party asset payloads to GitHub repositories.
- Train AI/ML models on purchased assets unless the asset license explicitly permits it.
- Auto-import assets into production repos.
- Treat marketplace packages as public redistributable source material.

## Import lanes by project

### Threshold Affairs

First import target should be evidence stills, not gameplay.

Best candidate packs:

- Japanese Old Shopping Mall Interior Environment,
- Motel Room Interior Environment,
- Motel Reception Interior Environment,
- Cyberpunk Hospital / Cyberpunk Clinic,
- Industrial Warehouse Night Environment - GARAGE,
- Portal VFX Enhanced,
- Glass Bundle Material,
- Master Mega Dirty Wall Pack Material 4K.

### Field Command

First import target should be tactical lookdev/reference scenes, not replacement gameplay.

Best candidate packs:

- Vertical Warehouse,
- HANGAR-X,
- Container City,
- Dungeon Ruins,
- Oil Rig Liope,
- Magic Projectiles Vol.3 - Niagara,
- Magic Abilities Vol. 3 Niagara,
- Niagara Mega Pack Vol. 3,
- Portal VFX Enhanced,
- Ground Explosion VFX.

### Hail Platform

First import target should be a short attract/stinger loop.

Best candidate packs:

- Steampunk Zeppelin Station,
- HANGAR-X,
- Fireworks Vol. 1 - Niagara,
- Portal VFX Enhanced,
- Niagara Mega Pack Vol. 3,
- Stylized VFX - Water,
- Explosion VFX 2.

### Slots v0

First import target should be a symbol sheet or win-state visual, not reel logic.

Best candidate packs:

- Fireworks Vol. 1 - Niagara,
- Loot Drops Vol.2 - Niagara,
- Portal VFX Enhanced,
- Magic Projectiles Vol.3 - Niagara,
- Steampunk Zeppelin Station,
- Glass Bundle Material.

## Recommended implementation sequence

### Step 1 — Create asset intake Protocol

Create `objects/protocols/control-alt-games-asset-intake.md`.

This should define the canonical intake fields, raw-vs-derived asset rule, license note requirements, and readout requirements.

### Step 2 — Create initial asset register

Create an `asset-register.yaml` or Markdown registry in the private asset vault, not in public app repos.

The first registry should use the 37-item Humble key-list inventory from `signal-control-alt-games-humble-unreal-unity-asset-vault`.

### Step 3 — Create vault skeleton

Create the vault root:

`/mnt/data/vault/vellum/`

Add `.gitignore` / `do-not-commit-raw-assets.md` equivalents if any local repo is introduced.

### Step 4 — Build tiny local intake runner

Start with a script that can:

- initialize the vault folders,
- create/update the asset register,
- write import-run notes,
- generate project-fit notes,
- generate Readout skeletons.

Do not automate Unreal or Unity import yet.

### Step 5 — Manual-first Epic/Fab redemption and staging

Redeem assets through the supported Epic/Fab flow. Record redemption status and local library/project paths after download/import.

Do not paste keys into Praxis or local logs.

### Step 6 — Unreal scratch project proof

Create one Unreal scratch project for inspection.

Test with one environment pack and one VFX pack:

- environment: `Japanese Old Shopping Mall Interior Environment` or `Industrial Warehouse Night Environment - GARAGE`,
- VFX: `Portal VFX Enhanced`.

Produce one screenshot/contact sheet and one Readout.

### Step 7 — Unity tier reconciliation

After redeeming the Unity tier, inspect exact package names and decide whether Unity import automation is necessary.

## First implementation slice

The first implementation slice should be:

> A local Control Alt Games asset intake runner that creates the private vault skeleton and writes a register entry for each Humble key-list item, without importing any raw assets into production repos.

Success criteria:

- `/mnt/data/vault/vellum/` exists.
- A register exists with all 37 key-list items.
- No keys are stored.
- No raw assets are committed to GitHub.
- At least one asset has a project-fit note.
- At least one import-run Readout skeleton exists.

## Open questions

1. Should the intake runner live as a standalone script in the vault, or inside a future Control Alt Games tooling repo?
2. Should Axiom eventually read the asset register, or should Praxis plus filesystem index be enough for now?
3. Should Unreal scratch-project setup be done on dev-ubuntu, Aurora, or the Lenovo laptop?
4. Where will Epic/Fab downloaded content physically live after redemption?
5. Should Field Command's existing asset vault become a subfolder under the wider Control Alt Games asset vault?
6. Should the first proof import be `Portal VFX Enhanced`, `Japanese Old Shopping Mall`, or `Industrial Warehouse Night Environment - GARAGE`?

## Disposition

Captured as a planning Signal for later Protocol/Directive work.

## Authority boundary

This Signal does not authorize implementation, engine installation, raw asset import, marketplace scraping, key storage, repo restructuring, or production project changes.

It does not authorize changes to Axiom, LCARD, Hail, Slots, Threshold Affairs, Field Command, local infrastructure, or public websites.

It only preserves the import-engine concept, import/staging workflow, tool shape, source references, first implementation slice, and boundaries for later approval.