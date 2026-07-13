#Requires -Version 5.1
<#
.SYNOPSIS
  Unsupervised Fireworks scratch inspect + still capture → Vellum.

.DESCRIPTION
  1) Stages vellum_capture.py into the Unreal project (avoids \tools tab mangling)
  2) Launches UnrealEditor-Cmd with env-var config (no nested CLI quotes)
  3) Reads Saved/VellumCapture/manifest.json
  4) POSTs scratch/record + lookdev/ingest-render to Vellum

  One-time setup on the Windows box:
  - Enable Python Editor Script Plugin in the VellumImport project
  - Set VELLUM_UE_CMD if UnrealEditor-Cmd is not under a default path

.EXAMPLE
  pwsh -File tools/unreal/run_vellum_capture.ps1
#>
param(
  [string]$Project = "C:\epic\VellumImport\VellumImport.uproject",
  [string]$AssetId = "fireworks-vol-1-niagara",
  [string]$ContentRoot = "/Game/FireworksV1",
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$Lane = "slots",
  [string]$EngineVersion = "5.8",
  [string]$IntakeRunId = "intake-20260713-035932-40f887",
  [string]$UeCmd = $env:VELLUM_UE_CMD
)

$ErrorActionPreference = "Stop"

function Find-UeCmd {
  param([string]$Hint)
  if ($Hint -and (Test-Path $Hint)) { return (Resolve-Path $Hint).Path }
  $candidates = @(
    "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    "C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    "C:\Program Files\Epic Games\UE_5.6\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    "C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
  )
  foreach ($c in $candidates) {
    if (Test-Path $c) { return $c }
  }
  throw "UnrealEditor-Cmd.exe not found. Set VELLUM_UE_CMD to the full path."
}

function ConvertTo-UePath([string]$Path) {
  return (($Path -replace '\\', '/').TrimEnd('/'))
}

function Get-LogPythonSnippet([string]$LogText) {
  if (-not $LogText) { return "" }
  $lines = $LogText -split "`r?`n" | Where-Object {
    $_ -match "LogPython|ExecutePythonScript|vellum_capture|Vellum capture|Could not load Python"
  }
  if (-not $lines) { return "" }
  return (($lines | Select-Object -Last 40) -join "`n")
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$SourcePy = Join-Path $RepoRoot "tools\unreal\vellum_capture.py"
if (-not (Test-Path $SourcePy)) {
  $SourcePy = Join-Path $PSScriptRoot "vellum_capture.py"
}
if (-not (Test-Path $SourcePy)) {
  throw "vellum_capture.py not found next to runner or under tools/unreal"
}
if (-not (Test-Path $Project)) {
  throw "Project not found: $Project"
}

$Ue = Find-UeCmd -Hint $UeCmd
$ProjectDir = Split-Path $Project -Parent
$OutDir = Join-Path $ProjectDir "Saved\VellumCapture"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# Stage script INSIDE the project so ExecutePythonScript never sees \tools (tab).
$StagedPy = Join-Path $OutDir "vellum_capture.py"
Copy-Item -Force -Path $SourcePy -Destination $StagedPy

$CapturePyUe = ConvertTo-UePath $StagedPy
$OutDirUe = ConvertTo-UePath $OutDir
$ProjectUe = ConvertTo-UePath $Project
$UeLog = Join-Path $OutDir "ue-capture.log"
if (Test-Path $UeLog) { Remove-Item -Force $UeLog }

Write-Host "UE: $Ue"
Write-Host "Project: $ProjectUe"
Write-Host "Staged script: $CapturePyUe"

# Env vars — Unreal CLI quoting is unreliable for script arguments.
$env:VELLUM_ASSET_ID = $AssetId
$env:VELLUM_CONTENT_ROOT = $ContentRoot
$env:VELLUM_OUT_DIR = $OutDirUe
$env:VELLUM_MAX_SYSTEMS = "3"
# Default OFF: AutomationLibrary HighResShot AVs UnrealEditor-Cmd (FunctionalTesting).
# Inventory/manifest is the scratch_inspect success path; enable later when framed.
if (-not $env:VELLUM_CAPTURE_STILLS) {
  $env:VELLUM_CAPTURE_STILLS = "0"
}

# Path-only ExecutePythonScript (no trailing args / nested quotes).
$ExecFlag = "-ExecutePythonScript=$CapturePyUe"
Write-Host "ExecutePythonScript: $CapturePyUe"
Write-Host "VELLUM_OUT_DIR=$OutDirUe"
Write-Host "VELLUM_CAPTURE_STILLS=$($env:VELLUM_CAPTURE_STILLS)"
Write-Host "Runner version: stage-to-project + env-args + no-AutomationLibrary-shot (2026-07-13)"


$ueExit = 0
try {
  & $Ue $ProjectUe "-stdout" "-FullStdOutLogOutput" "-unattended" "-nop4" $ExecFlag 2>&1 |
    Tee-Object -FilePath $UeLog
  $ueExit = $LASTEXITCODE
} catch {
  $ueExit = 1
  $_ | Out-File -FilePath $UeLog -Append
}
Write-Host "Unreal exit code: $ueExit"

$Manifest = Join-Path $OutDir "manifest.json"
if (-not (Test-Path $Manifest)) {
  $logTail = ""
  if (Test-Path $UeLog) {
    $logTail = Get-LogPythonSnippet (Get-Content $UeLog -Raw -ErrorAction SilentlyContinue)
  }
  $msg = @"
Capture did not write manifest.json under $OutDir (runner=stage-to-project).
Unreal exit=$ueExit staged=$CapturePyUe

LogPython snippet:
$logTail
"@
  throw $msg
}

$man = Get-Content $Manifest -Raw | ConvertFrom-Json
$notes = "auto-capture systems=$($man.niagara_systems_found); stills=$($man.stills.Count); errors=$($man.errors -join ',')"

$scratchBody = @{
  asset_id             = $AssetId
  scratch_project_path = $ProjectDir
  engine_version       = $EngineVersion
  notes                = $notes
  intake_run_id        = $IntakeRunId
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "$VellumBase/api/scratch/record" `
  -ContentType "application/json" -Body $scratchBody | Out-Null
Write-Host "Recorded scratch inspect for $AssetId"

$uploaded = 0
foreach ($still in @($man.stills)) {
  $path = [string]$still.path
  if (-not (Test-Path $path)) { continue }
  & curl.exe -sS -X POST "$VellumBase/api/lookdev/ingest-render" `
    -F "asset_id=$AssetId" `
    -F "lane=$Lane" `
    -F "note=auto Niagara/HighResShot via vellum_capture" `
    -F "file=@$path"
  if ($LASTEXITCODE -ne 0) { throw "ingest-render failed for $path" }
  $uploaded++
  Write-Host "Ingested $path"
}

Write-Host "Done. systems=$($man.niagara_systems_found) uploaded_stills=$uploaded ok=$($man.ok)"
if (-not $man.ok) { exit 2 }
exit 0
