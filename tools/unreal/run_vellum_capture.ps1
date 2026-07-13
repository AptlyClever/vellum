#Requires -Version 5.1
<#
.SYNOPSIS
  Unsupervised Fireworks scratch inspect + still capture → Vellum.

.DESCRIPTION
  1) Launches UnrealEditor-Cmd with tools/unreal/vellum_capture.py
  2) Reads Saved/VellumCapture/manifest.json
  3) POSTs scratch/record + lookdev/ingest-render to Vellum

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

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$CapturePy = Join-Path $RepoRoot "tools\unreal\vellum_capture.py"
if (-not (Test-Path $CapturePy)) {
  # Fallback: script may be copied next to the project
  $CapturePy = Join-Path (Split-Path $Project -Parent) "vellum_capture.py"
}
if (-not (Test-Path $CapturePy)) {
  throw "vellum_capture.py not found at $CapturePy"
}
if (-not (Test-Path $Project)) {
  throw "Project not found: $Project"
}

$Ue = Find-UeCmd -Hint $UeCmd
$ProjectDir = Split-Path $Project -Parent
$OutDir = Join-Path $ProjectDir "Saved\VellumCapture"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Write-Host "UE: $Ue"
Write-Host "Project: $Project"
Write-Host "Script: $CapturePy"

$pyArgs = "$CapturePy -- asset-id $AssetId -- content-root $ContentRoot -- out-dir `"$OutDir`""
& $Ue $Project "-stdout" "-FullStdOutLogOutput" "-unattended" "-ExecutePythonScript=$pyArgs"
$ueExit = $LASTEXITCODE
Write-Host "Unreal exit code: $ueExit"

$Manifest = Join-Path $OutDir "manifest.json"
if (-not (Test-Path $Manifest)) {
  throw "Capture did not write manifest.json under $OutDir (enable Python plugin / check UE log)."
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
