# Vellum machine roles

**Status:** binding operating assumption  
**Decision date:** 2026-07-14

## Current split

| Machine | Primary role | What it owns |
| --- | --- | --- |
| **Borealis** | Primary development workstation | Day-to-day coding, review, Design Foundation adoption, web/UI/product work, docs, normal Git flow |
| **Aurora** | Primary asset/factory workstation | Epic/Fab, `AuroraVellum`, Perforce Library state, reconcile, Unreal conversion, factory verification, host-local debugging |

This is not a migration away from Aurora. Borealis becoming the operator's
primary dev machine does **not** move the Unreal Library, Perforce workspace,
Epic/Fab state, scheduled reconcile task, or Conversion Factory.

## Agent routing

Use Borealis for normal development work when the task is code-first:

- product UI edits;
- Design Foundation implementation;
- backend/API changes that do not require local Unreal/Fab state;
- docs and tests;
- GitHub review/merge work.

Use Aurora when the task depends on the physical asset/factory machine:

- checking Epic/Fab launcher state;
- confirming `F:\Games\AuroraVellum` content;
- running or debugging `reconcile_aurora.ps1`;
- inspecting Unreal/factory worker processes;
- validating generated factory artifacts;
- diagnosing Perforce Library submits;
- measuring CPU/GPU/disk behavior during conversion.

It is valuable to keep agent execution available directly on Aurora for these
host-specific tasks. Do not retire that path just because Borealis is the
primary dev workstation.

## Non-goals

- Do not copy or move `AuroraVellum` to Borealis as a convenience step.
- Do not change `config/ue-hosts.json` `active` away from `aurora` unless the
  asset/factory host is intentionally migrated.
- Do not make Borealis the scheduled factory runner without migrating the
  Library, Perforce client, Epic/Fab state, local paths, and reconcile task.
- Do not treat "dev primary" as "factory primary".

## Git/source of truth

Code moves between machines through Git. Host-local asset state moves through
the Vellum reconcile/factory contracts, not ad-hoc file copies.

Related docs:

- [`factory-operations.md`](./factory-operations.md)
- [`asset-pipeline-product.md`](./asset-pipeline-product.md)
- [`intake-runbook.md`](./intake-runbook.md)
