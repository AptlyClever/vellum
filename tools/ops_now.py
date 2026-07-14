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
import json
import urllib.request
from collections import Counter
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
    jobs = _get(base, "/api/jobs?limit=100").get("jobs") or []

    counts = av.get("counts") or {}
    finish = ops.get("finish") or {}
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

    caps = [j for j in jobs if j.get("kind") == "ue_capture"]
    running = [j for j in caps if j.get("status") == "running"]
    queued = [j for j in caps if j.get("status") == "queued"]
    queued = sorted(queued, key=lambda j: j.get("created_at") or "")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# OPS_NOW — Vellum (binding)",
        "",
        f"> Regenerated: `{now}` via `tools/ops_now.py`  ",
        f"> API: `{base}`  ",
        "> **Agents must read this before inventing next work.** Refresh with "
        "`PYTHONPATH=. python3 tools/ops_now.py`.",
        "",
        "## Mission (do not renegotiate in chat)",
        "",
        "1. Finish lookdev for every pack **already on F: / vault-staged** "
        "(texture → derive; Niagara/VFX → single-flight `ue_capture` MRQ).",
        "2. Do **not** wait on the operator for agent-owned steps.",
        "3. **Need download** is unfinished inventory. Close it with agent-owned "
        "VaultCache fill + `host_fab_install` — not parking, not 'hand-click 19×'.",
        "4. Unity stays parked.",
        "5. CFD A–F is already met; this is post-CFD finish-line ops.",
        "",
        "## Scoreboard (Unreal)",
        "",
        f"| State | Count |",
        f"| --- | ---: |",
        f"| Ready | {counts.get('ready', 0)} |",
        f"| On disk (awaiting auto conversion) | {counts.get('on_disk', 0)} |",
        f"| Vault only | {counts.get('vault', 0)} |",
        f"| Installable (VaultCache) | {counts.get('installable', 0)} |",
        f"| Need download | {counts.get('need_download', 0)} |",
        f"| Coverage on_disk / staged | {cov.get('on_disk_count')} / {cov.get('vault_staged_count')} |",
        "",
        "## Finish (system truth — not chat)",
        "",
        f"- **Inventory Ready:** `{finish.get('percent_complete')}%` "
        f"({finish.get('ready')}/{finish.get('total')}; remaining {finish.get('remaining')})",
        f"- **Done:** `{finish.get('done')}`",
        f"- **Operator responsibility:** `{op.get('responsibility')}` · redeem `{op.get('redeem')}`",
        f"- **Watch:** {op.get('how_to_watch')}",
        "",
        "## Active capture pipeline (single-flight)",
        "",
    ]
    if running:
        run_prog = {
            str(r.get("job_id")): r
            for r in ((ops.get("capture") or {}).get("running") or [])
        }
        for j in running:
            info = run_prog.get(str(j.get("job_id"))) or {}
            stall = " STALLED" if info.get("stalled") else ""
            pct = info.get("percent")
            phase = info.get("phase") or ""
            extra = f" · {pct}% · {phase}{stall}" if phase or pct is not None else stall
            lines.append(
                f"- **RUNNING:** `{j.get('asset_id')}` (`{j.get('job_id')}`){extra}"
            )
    else:
        lines.append("- **RUNNING:** none — agent idle or stuck; check Aurora `VellumUeAgent`")
    lines.append("")
    lines.append(f"- **Queued ({len(queued)}):**")
    if queued:
        for j in queued:
            lines.append(f"  - `{j.get('asset_id')}`")
    else:
        lines.append("  - (empty)")
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
            "## Need download (unfinished — agent must close VaultCache → install)",
            "",
        ]
    )
    for n in names("need_download"):
        lines.append(f"- {n}")
    lines.extend(
        [
            "",
            "## Forbidden excuses",
            "",
            "- \"when the agent can\" / optional MRQ for Niagara",
            "- Fab catalog thumbs counting as Niagara lookdev done",
            "- Asking the operator before derive/capture for staged packs",
            "- Treating Need download as a mystery after seed+install coverage already said it",
            "- Parking / relabeling unfinished Fab downloads as 'not operator homework'",
            "- Asking the operator to hand-click Add-to-Project N times after assuring Fab was done",
            "",
            "## Health snapshot",
            "",
            f"- jobs_queued (health): `{health.get('jobs_queued')}`",
            f"- capture status mix: `{dict(Counter(j.get('status') for j in caps))}`",
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
