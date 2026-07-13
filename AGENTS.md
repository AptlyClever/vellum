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
3. Live CFD: `GET /api/cfd/inspirations/cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in` (Axiom) or mirror `docs/cfd/governing-inspiration.json`.
4. `docs/cfd/architecture-research.md` — locked architecture lessons.
5. `docs/humble-asset-vault-inventory.md` — 37-item inventory (no keys).
6. `docs/asset-import-engine.md` — intake runner / vault layout plan.
7. `docs/brand-canon.md` — core vs Games classification rules.

## Working rules

- Prefer vault register + filesystem staging over dumping packs into app repos.
- Never store Humble/Epic/Unity keys in git or in Axiom registry files.
- Keep derived lookdev outputs project-lane-scoped under the vault; leave raw packs in `01-source-bundles/`.
- Do not treat this as an Unreal/Unity engine-migration project.
- Registry identity for fleet discovery lives in Axiom `config/apps.registry.yaml` (`id: vellum`).
- Do not mutate Axiom/Praxis/Eidolon/LCARD runtime infra unless the operator explicitly asks.

## Provenance

Salvaged 2026-07-12 from closed Praxis PRs (#144 inventory, #145 import engine, #142 brand canon) via `ctrl-alt-axiom/docs/control-alt-games/`, then canonized here as **Vellum**.
