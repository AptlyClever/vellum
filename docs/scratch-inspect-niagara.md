# Unreal scratch inspect + Niagara renders (Fireworks) — automation-first

Unity tier reconcile is **parked**. Manual UI clicks are the fallback; prefer the Windows capture runner.

## What stays human (for now)

- Humble → Epic **redeem** / first **Add to Project** (Epic has no download button for UE packs).
- Enabling the **Python Editor Script Plugin** once in the scratch project.

## Automated path (preferred)

On the Windows machine that has UE 5.8 + `C:\epic\VellumImport`:

```powershell
# One-time: clone/sync vellum repo OR copy tools/unreal/* next to the project
# One-time: enable Edit → Plugins → "Python Editor Script Plugin" in VellumImport

$env:VELLUM_UE_CMD = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"  # if needed

pwsh -File \\192.168.68.93\…\vellum\tools\unreal\run_vellum_capture.ps1
# or from a local checkout:
pwsh -File C:\path\to\vellum\tools\unreal\run_vellum_capture.ps1
```

That script:

1. Runs `UnrealEditor-Cmd` with `vellum_capture.py` (unattended)
2. Inventories Niagara systems under `/Game/FireworksV1`
3. Attempts a HighResShot still
4. POSTs ` /api/scratch/record` + `/api/lookdev/ingest-render` to Vellum (`:8770`)

No Vellum UI clicking required when it succeeds.

### Outputs

- Manifest: `C:\epic\VellumImport\Saved\VellumCapture\manifest.json`
- Stills: `…\Saved\VellumCapture\stills\`
- Register: `scratch_project_status=inspected`
- DerivedOutput kind: `niagara-render` (when a still file is produced)

## Fallback (manual)

If Python plugin / HighResShot fails: open the project, capture one still yourself, use **Upload Niagara render** in Vellum — see older checklist below.

<details>
<summary>Manual checklist</summary>

1. Open `C:\epic\VellumImport`
2. Confirm Fireworks Niagara systems simulate
3. Vellum → Record scratch inspect
4. HighResShot / screenshot → Upload Niagara render

</details>

## Boundaries

- Does not automate Epic Launcher redeem/download.
- Does not copy `.uasset` packs into product git repos.
- Capture quality will improve once we add pack-specific Niagara framing (next iteration).
