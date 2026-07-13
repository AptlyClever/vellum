# Vellum

**Vellum** is the Control Alt Games asset vault and visual prototyping accelerator.

It owns ingest, catalog, and reuse of purchased Unreal/Unity game-dev assets (starting with the Humble All-in-One Unreal & Unity GameDev bundle) for Threshold Affairs, Field Command, Hail, LCARD, Slots/Bandit, and Dobsonian work — without dumping raw marketplace packs into product repos or migrating engines.

| Fact | Value |
| --- | --- |
| Canonical home | **Control Alt Games** (creative label under Control Alt) |
| Project root | `/mnt/temp/config/vellum` |
| Private vault (data) | `/mnt/data/vault/vellum` |
| Axiom registry id | `vellum` |
| Not | Control Alt core (that family includes Axiom, Praxis, Eidolon, …) |

## Start here

| Doc | What it is |
| --- | --- |
| **[docs/humble-asset-vault-inventory.md](./docs/humble-asset-vault-inventory.md)** | Authoritative **37-item** Humble key-list inventory (keys excluded) |
| **[docs/asset-import-engine.md](./docs/asset-import-engine.md)** | Intake / catalog / utilize plan — first slice is a local intake runner |
| **[docs/brand-canon.md](./docs/brand-canon.md)** | Control Alt vs Control Alt Games classification |

## Bundle facts (quick)

- Humble **All-in-One Unreal & Unity GameDev** software bundle.
- **36** Epic / Unreal items — redeem-by **2027-07-06 11:00 AM PDT**.
- **1** Unity tier — redeem-by **2027-06-30 11:00 AM PDT**.
- Framing: private vault + prototyping accelerator, not engine migration.

## Suggested first slice

Local intake runner that keeps the vault skeleton honest and writes a register entry for each of the 37 Humble key-list items — **no** keys stored, **no** raw assets in git.

## Boundaries

- Raw assets and keys stay under `/mnt/data/vault/vellum` (private data), never in this repo.
- Product repos consume derived lookdev / stills / clips from vault lookdev lanes, not source packs.
- Axiom is the runtime **app registry** home (`config/apps.registry.yaml`); Vellum is a registered Control Alt Games app/project, not an Axiom subsystem.
