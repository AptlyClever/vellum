# OPS_NOW — Vellum (binding)

> Regenerated: `2026-07-14T18:19:07Z` via `tools/ops_now.py`  
> API: `http://192.168.68.93:8770`  
> **Agents must read this before inventing next work.** Refresh with `PYTHONPATH=. python3 tools/ops_now.py`.

## Mission (do not renegotiate in chat)

1. Finish lookdev for every pack **already on F: / vault-staged** (texture → derive; Niagara/VFX → single-flight `ue_capture` MRQ).
2. Do **not** wait on the operator for agent-owned steps.
3. **Need download** is unfinished inventory. Close it with agent-owned VaultCache fill + `host_fab_install` — not parking, not 'hand-click 19×'.
4. Unity stays parked.
5. CFD A–F is already met; this is post-CFD finish-line ops.

## Scoreboard (Unreal)

| State | Count |
| --- | ---: |
| Ready | 23 |
| On disk (need lookdev) | 12 |
| Vault only | 0 |
| Installable (VaultCache) | 0 |
| Need download | 7 |
| Coverage on_disk / staged | 35 / 25 |

## Finish (system truth — not chat)

- **Inventory Ready:** `55%` (23/42; remaining 19)
- **Done:** `False`
- **Operator responsibility:** `none` · redeem `closed`
- **Watch:** http://192.168.68.93:8770/ — Live ops strip (poll /api/ops/pulse)

## Active capture pipeline (single-flight)

- **RUNNING:** `slash-trail-fx-elemental` (`job-20260714-181802-c5eb61`) · 5% · Phase B batch author still running (57s)

- **Queued (0):**
  - (empty)

## On disk — still need lookdev

- Arabic Dock
- Glass Bundle Material
- Magic Abilities Vol. 3 Niagara
- Magic Projectiles Vol.3 - Niagara
- Master Mega Dirty Wall Pack Material 4K
- Middle Eastern Town
- Motel Reception Interior Environment
- Niagara Mega Pack Vol. 3
- Oil Rig Liope
- Slash Trail FX Elemental
- Stylized VFX - Water
- Vertical Warehouse

## Need download (unfinished — agent must close VaultCache → install)

- Abandoned Cabin
- Arabic Fortress
- Ice Fortress
- Loot Drops Vol.2 - Niagara
- Mega Marble Material 4K
- The Count's Church
- The Lords' Mansion

## Forbidden excuses

- "when the agent can" / optional MRQ for Niagara
- Fab catalog thumbs counting as Niagara lookdev done
- Asking the operator before derive/capture for staged packs
- Treating Need download as a mystery after seed+install coverage already said it
- Parking / relabeling unfinished Fab downloads as 'not operator homework'
- Asking the operator to hand-click Add-to-Project N times after assuring Fab was done

## Health snapshot

- jobs_queued (health): `11`
- capture status mix: `{'running': 1, 'failed': 28, 'succeeded': 2, 'cancelled': 12}`

## Refresh

```bash
PYTHONPATH=. python3 tools/ops_now.py --base http://192.168.68.93:8770
```
