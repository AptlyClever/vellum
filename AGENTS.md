# AGENTS.md — Vellum

Vellum is the Control Alt Games asset vault and intake/prototyping project.

## Classification

- **Canonical home:** Control Alt Games (creative label).
- **Not** Control Alt core. Axiom and Eidolon are Control Alt core projects; Vellum is not.
- **Repo:** `/mnt/temp/config/vellum`
- **Data vault:** `/mnt/data/vault/vellum` (private; never commit raw assets or keys)

## Read first

0. **`OPS_NOW.md`** + **`GET /api/ops/now`** — **binding live ops SoT** (mission, scoreboard, capture queue).  
   Refresh markdown: `PYTHONPATH=. python3 tools/ops_now.py`. Do **not** invent next work from chat memory when this exists.
1. `README.md` — project identity, paths, first slice.
2. `DEV_TRACKER.md` — Active Issue + **Governing CFD**.
3. Live CFD: `GET /api/cfd/inspirations/cfd-inspiration-20260713-015950-vellum-control-alt-games-asset-vault-register-in` (Axiom) or mirror `docs/cfd/governing-inspiration.json`.
4. `docs/cfd/architecture-research.md` — locked architecture lessons.
5. `docs/humble-asset-vault-inventory.md` — 37-item inventory (no keys).
6. `docs/api-intake.md` — IntakeRun + jobs + asset patch API for agents.
7. `docs/api-lookdev.md` — DerivedOutput / project-lane derive API.
8. `docs/api-import.md` — Fab install / stage / post-stage lookdev chain.
9. `docs/ue-mrq-capture.md` — **Unreal MRQ + Sequencer lookdev capture** (new capability SoT).
10. `docs/scratch-inspect-niagara.md` — UE host profiles + retired HighResShot/SceneCapture backends.
11. `docs/slice-e-epic-staging.md` — Epic/Fab Add-to-Project → vault copy runbook.
12. `docs/asset-import-engine.md` — intake runner / vault layout plan.
13. `docs/brand-canon.md` — core vs Games classification rules.

## Working rules

- Prefer vault register + filesystem staging over dumping packs into app repos.
- Never store Humble/Epic/Unity keys in git or in Axiom registry files.
- Keep derived lookdev outputs project-lane-scoped under the vault; leave raw packs in `01-source-bundles/`.
- Do not treat this as an Unreal/Unity engine-migration project.
- Registry identity for fleet discovery lives in Axiom `config/apps.registry.yaml` (`id: vellum`).
- Do not mutate Axiom/Praxis/Eidolon/LCARD runtime infra unless the operator explicitly asks.

### Aurora is the Unreal workhorse (binding)

- **Host:** `192.168.68.100` (`jaked`) — Windows. UE + Fab live here. Capture = Epic batch Cmd (binding: `docs/capture-hosting-decision.md`). Lookdev Worker frozen.
- **Project:** only `F:\Games\AuroraVellum\AuroraVellum.uproject` (not retired `C:\dev\…`).
- **Repo checkout on Aurora:** `E:\Dev\vellum` — run Unreal tools from there.
- **Do:** SSH + `pwsh` on Aurora; install tools with Chocolatey when missing (`choco install …`); use `tools/unreal/*.ps1` (agent, worker, **`reconcile-aurora-content.ps1`**).
- **Do not:** prove pack presence with ad-hoc Linux `scp` scrapes or argue with the operator that Content is empty when they just Fab’d into the project — **run the Aurora reconcile script first**, trust its report, then map folders.
- Operator report of Fab Add-to-Project is a **signal to verify on Aurora**, not a claim to dismiss.

## Provenance

Salvaged 2026-07-12 from closed Praxis PRs (#144 inventory, #145 import engine, #142 brand canon) via `ctrl-alt-axiom/docs/control-alt-games/`, then canonized here as **Vellum**.
