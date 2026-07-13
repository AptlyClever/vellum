# Control Alt Games — brand / label canon

**Status:** salvaged related context  
**Salvaged:** 2026-07-12  
**Provenance:** closed [praxis#142](https://github.com/AptlyClever/praxis/pull/142) (`mara/control-alt-games-brand-canon-signal`), formerly `objects/signals/control-alt-brand-architecture-games-label-canon.md`. Closed 2026-07-07 with the ledger-archive batch.  
**Related:** [humble vault inventory](./humble-asset-vault-inventory.md) · [asset import engine](./asset-import-engine.md) · [handoff index](./README.md)

---

## Metadata

| Field | Value |
| --- | --- |
| id | `signal-control-alt-brand-architecture-games-label-canon` |
| type | `praxis.signal` |
| status | `captured` |
| revision | `1` |
| created | `2026-07-01` |
| updated | `2026-07-01` |
| product_area | `Control Alt / Control Alt Games / Praxis / Brand architecture` |
| possible_destinations | `response`, `doctrine`, `protocol`, `registry`, `fiber`, `directive`, `readout` |
| related_doctrine | `doctrine-control-alt-project-repo-registry-v1` |
| related_campaign | `campaign-control-alt-games-slots` |
| related_strand | `strand-slots-playable-proof` |
| related_projects | `Axiom`, `Praxis`, `Eidolon`, `Poiesis`, `Conduit`, `LCARD`, `Hail Platform`, `Slots v0`, `Dobsonian Universe`, `Threshold Affairs`, `Field Command` |
| supersedes | none |
| superseded_by | none |

## Captured idea

Canonize the Control Alt project family at a higher level than the current repo registry or individual product notes.

The operator's current framing:

> Every project is a Control Alt project. Control Alt should do boring but necessary work, and do it well. Axiom, Praxis, Eidolon, Poiesis, Conduit — they solve problems. Control Alt Games is going to do the fun stuff: LCARD, Hail Platform, Slots, Dobsonian Universe games, etc.

The problem is not just naming. The durable need is a Praxis-owned brand architecture and portfolio canon so the operator and agentic assistants do not forget what goes where, why it belongs there, and how shared systems should be classified.

## Current operator intent

Control Alt core should hold the practical/tooling/operations side:

- practical software,
- quality assurance,
- workflows,
- infrastructure,
- automation,
- owner-facing tools,
- evidence and governance systems,
- deployment and operating surfaces.

Control Alt Games should hold the creative/play/experience side:

- games,
- fictional universes,
- Arcade experiences,
- Hail/LCARD show surfaces,
- playful interactive systems,
- slots and other internal game-like proofs,
- Dobsonian Universe games and related experiences.

This does not mean Control Alt Games is a separate legal entity. The current working model is:

| Layer | Proposed meaning |
| --- | --- |
| `Control Alt, LLC` | Legal owner / company / IP owner |
| `Control Alt` | Master operating brand / core brand |
| `Control Alt Games` | Creative label / game studio label under Control Alt |
| `Dobsonian Universe` | Franchise / fictional universe under Control Alt Games |
| `Threshold Affairs`, `Field Command`, `Slots v0` | Game titles, modes, or product lines under Control Alt Games |
| `Axiom`, `Praxis`, `Eidolon`, `Poiesis`, `Conduit` | Core Control Alt platform/tool products |

## External reference patterns checked

A short web research pass found four relevant public patterns:

1. **Studio group / umbrella:** PlayStation Studios presents itself as a collective of studios and teams, with a shared identity binding many creator teams and game worlds. This is useful as a reference for umbrella/studio-family language, but Control Alt Games does not currently need a large studio-group structure.
   - Source: `https://www.playstation.com/en-us/corporate/playstation-studios/`

2. **Creative label:** Big Fan Games presents itself as "A Devolver Digital Label" with a focused creative mandate. This is the closest terminology fit for Control Alt Games today: a distinct creative label under a parent/master brand, without implying a separate company.
   - Source: `https://www.bigfangames.com/`

3. **Publishing imprint:** Penguin Random House uses imprints for editorially and creatively independent publishing lines. This is structurally useful, but "imprint" reads more publishing/literary than game/platform.
   - Source: `https://www.penguinrandomhouse.com/imprints/`

4. **Separate company / holding structure:** Alphabet is the heavier corporate separation pattern for businesses far afield from the core product. This is useful as a warning, not the recommended current step for Control Alt.
   - Source: `https://abc.xyz/`

## Proposed canonical terminology

Use **creative label** or **game studio label** for Control Alt Games.

Avoid these as the primary term for now:

| Term | Reason to avoid as primary canon |
| --- | --- |
| `subsidiary` | Implies a separate legal/company structure that does not exist and is too heavy right now. |
| `division` | Acceptable later, but currently feels more corporate/operational than needed. |
| `imprint` | Structurally useful, but publishing-coded and less natural for games. |
| `department` | Too internal and small; does not carry creative/public identity well. |
| `folder` / `bucket` | Too weak; does not create durable canon. |

Recommended phrase:

> Control Alt Games is the creative game label of Control Alt, LLC.

## Proposed canon rule

Control Alt is the master operating brand for practical software, systems, workflows, QA, infrastructure, automation, and owner-facing tools.

Control Alt Games is the creative label under Control Alt for playful, experiential, fictional, arcade, game, overlay, room-experience, and universe-driven work.

Control Alt builds the boring machinery well.

Control Alt Games uses that machinery to make the fun things happen.

A project belongs under Control Alt core when its primary purpose is operational leverage, workflow reliability, infrastructure, QA, automation, documentation, deployment, evidence, governance, or toolmaking.

A project belongs under Control Alt Games when its primary purpose is play, narrative, fictional setting, arcade experience, game mechanics, visual spectacle, room/TV interaction, or entertainment-facing presentation.

Shared systems may serve both families. When a shared system exists primarily to enable playful or experiential surfaces, its canonical home is Control Alt Games, with Control Alt core recorded as a dependency or provider. When a shared system exists primarily to solve operational work, its canonical home is Control Alt core, even if Games consumes it.

## Initial classification proposal

| Project | Canon home | Role |
| --- | --- | --- |
| Control Alt, LLC | Legal owner | Company / IP owner / records owner |
| Control Alt | Core brand | Practical systems, QA, workflows, infrastructure |
| Praxis | Control Alt core | Authority/evidence/workflow ledger |
| Axiom | Control Alt core | Owner-facing operating surface / control center |
| Poiesis | Control Alt core | Compose/app orchestration/tooling |
| Conduit | Control Alt core | Media/workflow automation |
| Eidolon | Control Alt core | Image generation/gallery tooling |
| Control Alt Games | Creative label | Fun/experiential/game/Arcade work |
| LCARD | Control Alt Games, with core dependencies | Arcade/control surface; may consume Axiom, Home Assistant, Hail |
| Hail Platform | Control Alt Games, with core dependencies | TV/overlay/presentation/show layer |
| Slots v0 | Control Alt Games | Internal fake-credit slot proof |
| Dobsonian Universe | Control Alt Games | Fictional franchise/universe |
| Threshold Affairs | Control Alt Games / Dobsonian Universe | Narrative management RPG |
| Field Command | Control Alt Games / Dobsonian Universe | Tactical/combat mode inside Threshold Affairs; asset vault separate |
| Vellum | Control Alt Games | Private asset vault + visual prototyping accelerator (`/mnt/temp/config/vellum`, data `/mnt/data/vault/vellum`) |

## Recommended implementation plan

This Signal should be promoted into a small, durable Praxis canon chain. Suggested sequence:

### Step 1 — Doctrine: Control Alt brand architecture

Create `objects/doctrines/control-alt-brand-architecture.md`.

Purpose:

- Define `Control Alt, LLC`, `Control Alt`, `Control Alt Games`, `Dobsonian Universe`, and current project roles.
- Establish the core-vs-Games classification rule.
- Record that Control Alt Games is a creative label / game studio label, not a separate legal entity.
- Record which terms are accepted and which are intentionally avoided.
- Define how shared systems are classified.

### Step 2 — Portfolio registry v1

Create a Praxis-owned portfolio registry object, likely a Doctrine or future Registry-shaped object.

Do not overload `doctrine-control-alt-project-repo-registry-v1`. That existing Doctrine answers repo identity and access eligibility. The new registry should answer product identity and brand-family classification.

Suggested responsibilities:

- stable `project_id`,
- display name,
- legal owner,
- brand family,
- brand role,
- canonical home,
- parent universe/label if applicable,
- repo references,
- public/private status,
- purpose statement,
- dependency/consumer/provider relationships.

### Step 3 — Classification protocol

Create `objects/protocols/classify-new-control-alt-project.md`.

The protocol should require any new project, game, tool, platform, overlay, or universe to answer:

1. Is the primary promise utility or experience?
2. Is the user-facing emotional contract "this solves work" or "this creates play/fiction/spectacle"?
3. Is it a platform provider, consumer, game title, franchise, label, asset vault, or core product?
4. Does it belong to Control Alt core, Control Alt Games, or both with one canonical home?
5. Which repo(s), docs, Praxis objects, and public names should point to it?

### Step 4 — Agent-facing startup/context line

Add a compact rule to Praxis startup context, AGENTS instructions, or Axiom Work Compass once the Doctrine exists:

> Agents must not classify all Control Alt work as one undifferentiated project family. Before creating, updating, or summarizing a project, identify whether its canonical home is Control Alt core or Control Alt Games. If a project crosses the boundary, preserve one canonical home and record the other side as a dependency, consumer, or provider.

### Step 5 — Axiom mirror later, not first

Only after the Doctrine/registry is stable, consider an Axiom mirror so UI surfaces can show Core vs Games cleanly.

This should be a later implementation Directive because it touches application behavior. The first pass should be Praxis-only canon.

## Boundary and non-actions

This Signal does not authorize:

- app implementation,
- Axiom mirror generation,
- repo registry promotion,
- legal filings,
- DBA/trade-name registration,
- trademark work,
- public website changes,
- renaming existing repos,
- moving LCARD/Hail code,
- merging Slots or Dobsonian work into any new umbrella repo.

It only captures the operator's intent, the researched terminology direction, and the recommended Praxis implementation plan.

## Open questions

1. Should the durable object be a `Doctrine` only, or a Doctrine plus separate portfolio registry file?
2. Should `Control Alt Games` be described publicly as a `creative label`, `game label`, or `studio label`?
3. Should LCARD and Hail be classified as Games-primary immediately, or recorded as shared platforms with Games canonical home and Control Alt core dependencies?
4. Should Dobsonian Universe get its own Campaign/Strand later, or stay as a franchise entry until active game work resumes?
5. Should the existing project/repo registry be cross-linked from the new portfolio registry, or should repo identity remain completely separate?
6. What is the smallest Axiom surface that would benefit from this after Praxis canon exists?

## Disposition

Captured with attached implementation-plan response.

## Authority boundary

This Signal does not authorize implementation or follow-up execution.

It does not authorize changes to Axiom, LCARD, Hail, public websites, legal/business records, repositories outside this Signal, or any runtime infrastructure.

It only preserves the brand-architecture decision direction and recommends a Praxis-only canonization path for operator approval.