# AGENTS.md — Vellum

Vellum is the Control Alt Games asset vault and intake/prototyping project.

## Classification

- **Canonical home:** Control Alt Games (creative label).
- **Not** Control Alt core. Axiom and Eidolon are Control Alt core projects; Vellum is not.
- **Data vault:** `/mnt/data/vault/vellum` on the hub (private; never commit raw assets or keys)

## Environment roles (HARD — read before touching any path)

Same studio/press model as Axiom (`ctrl-alt-axiom/docs/handbook/how-we-work.md`),
plus a factory role. Do not collapse these into one path:

| Role | Machine | Path | Job |
| --- | --- | --- | --- |
| **Studio** | Any dev machine (Borealis, Aurora, …) | GitHub clone, e.g. `E:\Dev\vellum` | Read, code, test, commit, **push** |
| **Press** | `dev-ubuntu` (`192.168.68.93`) | `/mnt/temp/config/vellum` | Repo Ops deploy checkout; Docker runtime; hub API `:8770`; vault mount |
| **Factory** | Aurora (`192.168.68.100`) | `F:\Games\AuroraVellum` + this repo checkout | Unreal Library, Perforce, reconcile, MRQ conversion |

- `/mnt/temp/config/vellum` and `/mnt/data/vault/vellum` exist **only on the
  press**. From studio or factory they are not filesystems you can reach —
  no WSL/UNC/SSH file access, ever.
- **Vault I/O is HTTP-only** off the press: `upload-run`, `publish`,
  `unpublish`, and catalog queries against `http://192.168.68.93:8770`.
  Never hand-edit catalog YAML from another machine.
- Ship path: commit → push → Repo Ops `deploy.auto` (`#/axiom/repo-ops`).
  Never run the Vellum compose stack from a studio checkout as "the runtime."
- Aurora pulls this repo via git to run factory scripts; that checkout is a
  studio clone plus factory scripts, not a deploy target.

## Art ownership vs Eidolon (HARD)

**Vellum converts and catalogs art we already own. Eidolon/OpenAI authors art
that does not exist yet.** Canonical table lives in Eidolon:
`../eidolon/docs/art-ownership.md` (or `ctrl-alt-eidolon` `docs/art-ownership.md`).

- **Vellum IS for:** vault packs → factory (Niagara MRQ → WebM + sprite-sheet),
  game-ready catalog, lane publish. Celebration **particle** FX =
  `fireworks-vol-1-niagara` (and similar), not OpenAI redraws.
- **Vellum is NOT for:** inventing float numerals, typed “BIG WIN” banners, or
  keycap legends with no source frames — that is Eidolon brief work.
- **Vellum does not call OpenAI.** Do not turn the vault into an image generator.

## Read first

1. `README.md` — project identity, paths, first slice.
2. `DEV_TRACKER.md` — Active Issue + **Governing CFD**.
3. **`docs/asset-pipeline-product.md`** — **product SoT** (Library + Conversion Factory + delivery catalog).
4. **`docs/factory-operations.md`** — binding factory execution, evidence,
   recovery, verified baseline, and next slice.
5. **`docs/machine-roles.md`** — Borealis is dev-primary; Aurora remains
   asset/factory-primary and still useful for host-local agents.
6. Live CFD: `GET /api/cfd/inspirations/cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in` (Axiom) or mirror `docs/cfd/governing-inspiration.json`.
7. `docs/cfd/architecture-research.md` — locked architecture lessons.
8. `docs/humble-asset-vault-inventory.md` — 37-item inventory (no keys).
9. `docs/intake-runbook.md` — redeem → Fab → automatic reconcile.
10. `docs/library-project.md` — curated Unreal Library layout.
11. `docs/api-intake.md` — IntakeRun + jobs + asset patch API for agents.
12. `docs/api-lookdev.md` / `docs/api-game-ready.md` — derived + game-ready catalog APIs.
13. `docs/slice-e-epic-staging.md` — Epic/Fab Add-to-Project notes.
14. `docs/brand-canon.md` — core vs Games classification rules.
15. Frozen archaeology: `docs/ue-lookdev-worker.md`, `docs/ue-mrq-capture.md`, `archive/prototype-v0/`.

## Working rules

- Prefer vault register + filesystem staging over dumping packs into app repos.
- Never store Humble/Epic/Unity keys in git or in Axiom registry files.
- Keep derived / game-ready outputs project-lane-scoped under the vault; leave raw packs in `01-source-bundles/`.
- Factory jobs live under `tools/pipeline/`; do not revive the Capture agent polling loop without operator unpark.
- Do not confuse machine roles: Borealis is primary for development; Aurora is
  still primary for the asset Library, Epic/Fab state, Perforce Library,
  reconcile, and Conversion Factory. Do not move factory responsibility to
  Borealis without an explicit migration plan.
- After a pack appears under `AuroraVellum/Content`, reconcile owns register,
  stage, P4, validation, and conversion. Never present "lookdev" as manual
  operator work.
- Parallel factory workers are read-only against the Library and must use
  isolated work/output directories. Any Unreal-content-writing job is
  exclusive, never part of the parallel pool.
- Do not call a process launch success. Verify manifests, plausible exported
  counts, catalog rows, and reconcile exceptions.
- `factory-all` emits bake plans in the parallel phase; the exclusive VFX
  render phase (reconcile 6c) turns plans into validated WebM/sprite-sheet
  clips and publishes only validation-passing variants to game lanes.
- A native Unreal title may consume the Library project — that is allowed under the product SoT; do not dump packs into product git repos.
- Registry identity for fleet discovery lives in Axiom `config/apps.registry.yaml` (`id: vellum`).
- Do not mutate Axiom/Praxis/Eidolon/LCARD runtime infra unless the operator explicitly asks.

## Provenance

Salvaged 2026-07-12 from closed Praxis PRs (#144 inventory, #145 import engine, #142 brand canon) via `ctrl-alt-axiom/docs/control-alt-games/`, then canonized here as **Vellum**.
