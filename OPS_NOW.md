# OPS_NOW — Vellum (binding)

> Regenerated: `2026-07-15T02:00:18Z` via `tools/ops_now.py`
> API: `http://192.168.68.93:8770`
> **Agents must read this before inventing next work.** Refresh with `PYTHONPATH=. python3 tools/ops_now.py`.

## Mission (do not renegotiate in chat)

1. Preserve boring intake: after Fab puts content in AuroraVellum, reconcile owns register, stage, P4, validation, and conversion.
2. Never present `awaiting conversion (auto)` or lookdev as operator work.
3. Complete Project listings are deferred/non-blocking until a game needs them.
4. Build the missing product slice: execute Niagara bake plans into validated WebM/sprite-sheet artifacts and prove one in a Games runtime.
5. Keep Unity parked and the Capture agent / warm Lookdev Worker frozen.

## Scoreboard (Unreal)

| State | Count |
| --- | ---: |
| Ready | 39 |
| On disk (awaiting auto conversion) | 0 |
| Vault only | 0 |
| Installable (VaultCache) | 0 |
| Active acquisition blocked | 0 |
| Deferred Complete Projects | 3 |
| Coverage on_disk / staged | 39 / 39 |
| Game-ready elements listed | 1000+ (API cap 1000) |

## Intake closure (system truth — not chat)

- **Active intake closed:** `True`
- **Blocked / orphan / deferred:** `0` / `0` / `3`
- **Product complete:** `False` — playable Niagara media + runtime proof remain
- **Operator responsibility:** `none` · redeem `closed`
- **Watch:** http://192.168.68.93:8770/ — Live ops strip (poll /api/ops/pulse)

## Factory ownership and continuation

- Controller: `tools/pipeline/reconcile_aurora.ps1` (logon + hourly)
- Runtime: `factory-all`, one UE boot/pack, 3 isolated parallel workers
- Current evidence means catalog presence; a bake plan is not a playable VFX clip
- Next slice: MRQ/Niagara Baker → transparent WebM/sprite sheet → validation → game proof
- Contract: `docs/factory-operations.md`


## On disk — awaiting auto conversion (factory-owned)

- (none)

## Blocked acquisition (0 operator-visible)

- (none)

## Deferred Complete Projects (3; no work owed)

- Abandoned Cabin
- Loot Drops Vol.2 - Niagara
- The Count's Church

## Truth rules

- Process existence or a launch message is not progress evidence.
- Verify machine activity, fresh manifests/plausible counts, catalog rows, and reconcile exceptions.
- Do not count a Niagara bake plan as a playable game element.
- Do not revive retired capture/lookdev control planes.
- Do not turn deferred Complete Projects into operator homework.

## Health snapshot

- jobs_queued (health): `0`
- reconcile/import actionable: `0`
- acquisition blocked/deferred: `0` / `3`

## Refresh

```bash
PYTHONPATH=. python3 tools/ops_now.py --base http://192.168.68.93:8770
```
