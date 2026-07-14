# Native Unreal titles — consuming the Library

**Product SoT:** [`asset-pipeline-product.md`](./asset-pipeline-product.md)  
**Library:** `F:\Games\AuroraVellum` under Perforce (`docs/p4-library.md`)

This is the low-cost Phase 4 path: when Control Alt Games green-lights a native Unreal title, **do not re-buy or re-Add packs**. Consume the versioned Library.

## Pattern

1. Create the new game project (`MyTitle.uproject`) on the same engine version (or migrate carefully).
2. Sync Library workspace from P4 (`//vellum_library/AuroraVellum/...`).
3. In the **game** project Content Browser: **Migrate** only the packs/features you need from `Content/<Pack>` into `Content/MyTitle/...`.
4. Fix Up Redirectors in the destination.
5. Keep marketplace originals only in the Library depot — game project holds migrated copies + game-specific work.

## Do not

- Point two shipped titles at one shared live Content folder (recipe for depot fights)
- Commit Library binaries into the game’s git remote
- Skip P4 for Library edits

## Relationship to web conversion

Web titles keep using Conversion Factory outputs via Vellum game-ready lanes. Native titles use `.uasset` via Migrate. **Same Library, two consumers.**
