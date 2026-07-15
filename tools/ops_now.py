#!/usr/bin/env python3
"""Regenerate OPS_NOW.md — binding live ops SoT for agents.

Usage:
  PYTHONPATH=. python3 tools/ops_now.py
  PYTHONPATH=. python3 tools/ops_now.py --base http://192.168.68.93:8770

Agents: read OPS_NOW.md at session start and after any status question.
Do not invent next work from chat memory when this file exists.
"""

from __future__ import annotations

import argparse
import urllib.request
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "OPS_NOW.md"


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base.rstrip('/')}{path}", timeout=60) as resp:
        return json.load(resp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://192.168.68.93:8770")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    base = args.base

    health = _get(base, "/api/health")
    ops = _get(base, "/api/ops/now?engine=unreal")
    av = _get(base, "/api/import/availability?engine=unreal")
    cov = _get(base, "/api/import/coverage?engine=unreal")
    queue = _get(base, "/api/import/queue?engine=unreal&limit=100")
    game_ready = _get(base, "/api/game-ready/elements?limit=1000")

    counts = av.get("counts") or {}
    op = ops.get("operator") or {}
    by = av.get("by_asset_id") or {}
    assets = {
        a["id"]: a
        for a in (_get(base, "/api/assets?engine=unreal").get("assets") or [])
    }

    def names(state: str) -> list[str]:
        out = []
        for aid, row in by.items():
            if row.get("state") != state:
                continue
            a = assets.get(aid) or {}
            out.append(str(a.get("display_name") or aid))
        return sorted(out)

    deferred = queue.get("deferred_epic") or []
    blocked = queue.get("blocked_epic") or []
    game_ready_count = int(game_ready.get("count") or 0)
    game_ready_label = f"{game_ready_count}+" if game_ready_count >= 1000 else str(
        game_ready_count
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# OPS_NOW — Vellum (binding)",
        "",
        f"> Regenerated: `{now}` via `tools/ops_now.py`",
        f"> API: `{base}`",
        "> **Agents must read this before inventing next work.** Refresh with "
        "`PYTHONPATH=. python3 tools/ops_now.py`.",
        "",
        "## Mission (do not renegotiate in chat)",
        "",
        "1. Preserve boring intake: after Fab puts content in AuroraVellum, "
        "reconcile owns register, stage, P4, validation, and conversion.",
        "2. Never present `awaiting conversion (auto)` or lookdev as operator work.",
        "3. Complete Project listings are deferred/non-blocking until a game needs them.",
        "4. Build the missing product slice: execute Niagara bake plans into validated "
        "WebM/sprite-sheet artifacts and prove one in a Games runtime.",
        "5. Keep Unity parked and the Capture agent / warm Lookdev Worker frozen.",
        "",
        "## Scoreboard (Unreal)",
        "",
        f"| State | Count |",
        f"| --- | ---: |",
        f"| Ready | {counts.get('ready', 0)} |",
        f"| On disk (awaiting auto conversion) | {counts.get('on_disk', 0)} |",
        f"| Vault only | {counts.get('vault', 0)} |",
        f"| Installable (VaultCache) | {counts.get('installable', 0)} |",
        f"| Active acquisition blocked | {len(blocked)} |",
        f"| Deferred Complete Projects | {len(deferred)} |",
        f"| Coverage on_disk / staged | {cov.get('on_disk_count')} / {cov.get('vault_staged_count')} |",
        f"| Game-ready elements listed | {game_ready_label} (API cap 1000) |",
        "",
        "## Intake closure (system truth — not chat)",
        "",
        f"- **Active intake closed:** `{len(blocked) == 0 and cov.get('orphan_count', 0) == 0}`",
        f"- **Blocked / orphan / deferred:** `{len(blocked)}` / "
        f"`{cov.get('orphan_count', 0)}` / `{len(deferred)}`",
        "- **Product complete:** `False` — playable Niagara media + runtime proof remain",
        f"- **Operator responsibility:** `{op.get('responsibility')}` · redeem `{op.get('redeem')}`",
        f"- **Watch:** {op.get('how_to_watch')}",
        "",
        "## Factory ownership and continuation",
        "",
        "- Controller: `tools/pipeline/reconcile_aurora.ps1` (logon + hourly)",
        "- Runtime: `factory-all`, one UE boot/pack, 3 isolated parallel workers",
        "- Current evidence means catalog presence; a bake plan is not a playable VFX clip",
        "- Next slice: MRQ/Niagara Baker → transparent WebM/sprite sheet → validation → game proof",
        "- Contract: `docs/factory-operations.md`",
        "",
    ]
    lines.extend(
        [
            "",
            "## On disk — awaiting auto conversion (factory-owned)",
            "",
        ]
    )
    od = names("on_disk")
    if od:
        for n in od:
            lines.append(f"- {n}")
    else:
        lines.append("- (none)")
    lines.extend(
        [
            "",
            f"## Blocked acquisition ({len(blocked)} operator-visible)",
            "",
        ]
    )
    if blocked:
        for row in blocked:
            lines.append(
                f"- {row.get('display_name') or row.get('asset_id')}: "
                f"{(row.get('acquisition') or {}).get('operator_hint') or row.get('detail')}"
            )
    else:
        lines.append("- (none)")
    lines.extend(
        [
            "",
            f"## Deferred Complete Projects ({len(deferred)}; no work owed)",
            "",
        ]
    )
    if deferred:
        for row in deferred:
            lines.append(f"- {row.get('display_name') or row.get('asset_id')}")
    else:
        lines.append("- (none)")
    lines.extend(
        [
            "",
            "## Truth rules",
            "",
            "- Process existence or a launch message is not progress evidence.",
            "- Verify machine activity, fresh manifests/plausible counts, catalog rows, "
            "and reconcile exceptions.",
            "- Do not count a Niagara bake plan as a playable game element.",
            "- Do not revive retired capture/lookdev control planes.",
            "- Do not turn deferred Complete Projects into operator homework.",
            "",
            "## Health snapshot",
            "",
            f"- jobs_queued (health): `{health.get('jobs_queued')}`",
            f"- reconcile/import actionable: `{queue.get('count', 0)}`",
            f"- acquisition blocked/deferred: `{len(blocked)}` / `{len(deferred)}`",
            "",
            "## Refresh",
            "",
            "```bash",
            f"PYTHONPATH=. python3 tools/ops_now.py --base {base}",
            "```",
            "",
        ]
    )
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
