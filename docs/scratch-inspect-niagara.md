# Unreal capture — host runbook (Fireworks)

You stay in **Vellum**. Unreal runs on the Windows host agent.

**Capability SoT (what we’re building):** [`docs/ue-mrq-capture.md`](./ue-mrq-capture.md) —
Movie Render Queue + Sequencer lookdev capture (full fidelity).

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

## Agent (host plumbing)

```powershell
cd E:\Dev\vellum
git pull
pwsh -ExecutionPolicy Bypass -File .\tools\unreal\vellum_ue_agent.ps1
```

Preflight should resolve Aurora UE Cmd + `AuroraVellum.uproject`. Until MRQ lands,
do not expect usable Niagara lookdev from the retired SceneCapture runner.

## What stays human

Humble → Epic redeem / first Add to Project only.
