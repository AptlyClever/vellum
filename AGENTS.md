# AGENTS.md — Vellum

Vellum is the Control Alt Games asset vault and intake/prototyping project.

## Classification

- **Canonical home:** Control Alt Games (creative label).
- **Not** Control Alt core. Axiom and Eidolon are Control Alt core projects; Vellum is not.
- **Repo:** `/mnt/temp/config/vellum`
- **Data vault:** `/mnt/data/vault/vellum` (private; never commit raw assets or keys)

## Read first

1. `README.md` — project identity, paths, first slice.
2. `DEV_TRACKER.md` — Active Issue + **Governing CFD**.
3. **`docs/asset-pipeline-product.md`** — **product SoT** (Library + Conversion Factory + delivery catalog).
4. **`docs/factory-operations.md`** — binding factory execution, evidence,
   recovery, verified baseline, and next slice.
5. Live CFD: `GET /api/cfd/inspirations/cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in` (Axiom) or mirror `docs/cfd/governing-inspiration.json`.
6. `docs/cfd/architecture-research.md` — locked architecture lessons.
7. `docs/humble-asset-vault-inventory.md` — 37-item inventory (no keys).
8. `docs/intake-runbook.md` — redeem → Fab → automatic reconcile.
9. `docs/library-project.md` — curated Unreal Library layout.
10. `docs/api-intake.md` — IntakeRun + jobs + asset patch API for agents.
11. `docs/api-lookdev.md` / `docs/api-game-ready.md` — derived + game-ready catalog APIs.
12. `docs/slice-e-epic-staging.md` — Epic/Fab Add-to-Project notes.
13. `docs/brand-canon.md` — core vs Games classification rules.
14. Frozen archaeology: `docs/ue-lookdev-worker.md`, `docs/ue-mrq-capture.md`, `archive/prototype-v0/`.

## Working rules

- Prefer vault register + filesystem staging over dumping packs into app repos.
- Never store Humble/Epic/Unity keys in git or in Axiom registry files.
- Keep derived / game-ready outputs project-lane-scoped under the vault; leave raw packs in `01-source-bundles/`.
- Factory jobs live under `tools/pipeline/`; do not revive the Capture agent polling loop without operator unpark.
- After a pack appears under `AuroraVellum/Content`, reconcile owns register,
  stage, P4, validation, and conversion. Never present "lookdev" as manual
  operator work.
- Parallel factory workers are read-only against the Library and must use
  isolated work/output directories. Any Unreal-content-writing job is
  exclusive, never part of the parallel pool.
- Do not call a process launch success. Verify manifests, plausible exported
  counts, catalog rows, and reconcile exceptions.
- `bake-vfx` currently emits plans, not playable clips. The next product slice
  is MRQ/Niagara Baker execution + WebM/sprite-sheet validation in a game.
- A native Unreal title may consume the Library project — that is allowed under the product SoT; do not dump packs into product git repos.
- Registry identity for fleet discovery lives in Axiom `config/apps.registry.yaml` (`id: vellum`).
- Do not mutate Axiom/Praxis/Eidolon/LCARD runtime infra unless the operator explicitly asks.

## Provenance

Salvaged 2026-07-12 from closed Praxis PRs (#144 inventory, #145 import engine, #142 brand canon) via `ctrl-alt-axiom/docs/control-alt-games/`, then canonized here as **Vellum**.
