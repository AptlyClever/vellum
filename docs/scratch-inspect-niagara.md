# Unreal capture via Vellum UI (Fireworks)

You stay in **Vellum**. Unreal runs unattended on the Windows box.

## Operator flow

1. On the UE workstation, leave this running in the background (one-time setup below):

```powershell
pwsh -File tools\unreal\vellum_ue_agent.ps1
```

2. In Vellum → Fireworks → **Capture from Unreal**
3. Watch **Jobs** on the detail page (`ue_capture` → succeeded)
4. Lookdev grid gains `niagara-render` stills when capture produces files

No navigating Unreal for screenshots. No PowerShell per asset.

## One-time Windows setup

1. Enable **Python Editor Script Plugin** in `C:\epic\VellumImport`
2. Have this repo (or `tools/unreal/*`) available on that machine
3. Optional: `$env:VELLUM_UE_CMD = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"`
4. Start `vellum_ue_agent.ps1` (Task Scheduler / always-on terminal)

## What stays human

Humble → Epic redeem / first Add to Project only.

## APIs (UI uses these)

- `POST /api/ue/capture` — enqueue from UI
- `POST /api/jobs/claim` — agent claims `ue_capture`
- `POST /api/jobs/{id}/report` — agent reports result
- `POST /api/lookdev/ingest-render` — still upload (agent/runner)

## Troubleshooting

1. **Old scripts still running** — job error mentions `enable Python plugin` → Windows
   did not `git pull` / restart the agent. After a good pull, errors say
   `runner=stage-to-project` and include a LogPython snippet.
2. **`\tools` → tab** — path like `vellum       ools` means Unreal ate `\t`.
   Current runner stages the script into `Saved/VellumCapture/vellum_capture.py`
   and passes config via `VELLUM_*` env vars (no `\tools` on the UE command line).
3. Restart the agent after every pull:
   `pwsh -ExecutionPolicy Bypass -File .\tools\unreal\vellum_ue_agent.ps1`
