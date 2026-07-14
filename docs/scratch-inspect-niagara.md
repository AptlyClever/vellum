# Unreal capture — host runbook (Fireworks)

You stay in **Vellum**. Unreal runs on the Windows host agent.

**Product SoT:** [`docs/asset-pipeline-product.md`](./asset-pipeline-product.md) —
Library + Conversion Factory + game-ready delivery.

**Historical Capture notes:** [`docs/ue-mrq-capture.md`](./ue-mrq-capture.md) (MRQ tech retained inside `bake-vfx` only).

## STOP — retired capture backends

**Do not use / do not extend:**

- `-game` + `HighResShot`
- Editor `SceneCapture2D` → `export_render_target` (`vellum_capture_bake_map.py`)

## Hosts (profiles)

| Host | Role | UE | Scratch project (default) |
| --- | --- | --- | --- |
| **aurora** | primary (active) | `F:\Games\UE_5.8\…\UnrealEditor.exe` | `F:\Games\AuroraVellum` |
| **borealis** | secondary | `C:\Program Files\Epic Games\UE_5.8\…` | `C:\epic\VellumImport` |

Config: [`config/ue-hosts.json`](../config/ue-hosts.json). API: `GET /api/ue/hosts`.

Only **one** agent should poll at a time.

## Prerequisite (Aurora)

Fireworks Vol. 1 must be **Add to Project** → `F:\Games\AuroraVellum` before
inventory can find Niagara systems. `job-20260713-181144-c1ce27` failed with
`systems_found=0` for this reason.

Also enable **Movie Render Queue** (+ Python Editor Script Plugin) in that project
before the new capture backend can run.

## Agent (your only Unreal-side step)

```powershell
cd E:\Dev\vellum
git pull
# Optional first proof: fewer systems
$env:VELLUM_MAX_SYSTEMS = "1"
# pick_heroes.py needs python/py on PATH
pwsh -ExecutionPolicy Bypass -File .\tools\unreal\vellum_ue_agent.ps1
```

Expect fingerprint **`epic-batch-mrq-cmd`**. Then Vellum → asset detail → **Capture**; the agent launches `run_vellum_capture.ps1` / `UnrealEditor-Cmd` for MRQ.

If the agent says `lookdev-worker`, the scheduled task was installed with the frozen opt-in flag and must be reinstalled.

## What stays human

Humble → Epic redeem / first Add to Project only.
