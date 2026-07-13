#Requires -Version 5.1
<#
.SYNOPSIS
  Background Windows agent: claim Vellum ue_capture jobs and run Unreal capture.

.DESCRIPTION
  Keep this running on the UE workstation. Operator uses the Vellum UI button
  "Capture from Unreal" — this agent does the Unreal work and reports back.

  One-time:
  - Enable Python Editor Script Plugin in the scratch project
  - Optional: set VELLUM_UE_CMD

.EXAMPLE
  pwsh -File tools/unreal/vellum_ue_agent.ps1
#>
param(
  [string]$VellumBase = "http://192.168.68.93:8770",
  [int]$PollSeconds = 5,
  [string]$DefaultProject = "C:\epic\VellumImport\VellumImport.uproject",
  [string]$UeCmd = $env:VELLUM_UE_CMD
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$CapturePy = Join-Path $RepoRoot "tools\unreal\vellum_capture.py"
$Runner = Join-Path $PSScriptRoot "run_vellum_capture.ps1"

function Find-UeCmd {
  param([string]$Hint)
  if ($Hint -and (Test-Path $Hint)) { return (Resolve-Path $Hint).Path }
  foreach ($c in @(
      "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
      "C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
      "C:\Program Files\Epic Games\UE_5.6\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
    )) {
    if (Test-Path $c) { return $c }
  }
  throw "UnrealEditor-Cmd.exe not found. Set VELLUM_UE_CMD."
}

function Invoke-CaptureJob {
  param($Job)
  $payload = $Job.payload
  if (-not $payload) { $payload = @{} }
  $assetId = [string]$Job.asset_id
  $lane = if ($payload.lane) { [string]$payload.lane } else { "slots" }
  $projectPath = if ($payload.project_path) { [string]$payload.project_path } else { Split-Path $DefaultProject -Parent }
  $uproject = if (Test-Path (Join-Path $projectPath "VellumImport.uproject")) {
    Join-Path $projectPath "VellumImport.uproject"
  } else {
    $DefaultProject
  }
  $contentRoot = if ($payload.content_root) { [string]$payload.content_root } else { "/Game/FireworksV1" }
  $engineVersion = if ($payload.engine_version) { [string]$payload.engine_version } else { "5.8" }
  $intakeRunId = [string]$Job.intake_run_id
  $maxSystems = if ($payload.max_systems) { [int]$payload.max_systems } else { 3 }
  $width = if ($payload.width) { [int]$payload.width } else { 1920 }
  $height = if ($payload.height) { [int]$payload.height } else { 1080 }

  Write-Host "Running capture for $assetId ($($Job.job_id))"
  $env:VELLUM_JOB_ID = [string]$Job.job_id
  & $Runner `
    -Project $uproject `
    -AssetId $assetId `
    -ContentRoot $contentRoot `
    -VellumBase $VellumBase `
    -Lane $lane `
    -EngineVersion $engineVersion `
    -IntakeRunId $intakeRunId `
    -UeCmd (Find-UeCmd -Hint $UeCmd) `
    -MaxSystems $maxSystems `
    -Width $width `
    -Height $height `
    -JobId ([string]$Job.job_id)

  $outDir = Join-Path (Split-Path $uproject -Parent) "Saved\VellumCapture"
  $manifestPath = Join-Path $outDir "manifest.json"
  $man = $null
  if (Test-Path $manifestPath) {
    $man = Get-Content $manifestPath -Raw | ConvertFrom-Json
  }

  $errs = @()
  if ($man -and $man.errors) { $errs = @($man.errors) }
  $result = @{
    project_path       = (Split-Path $uproject -Parent)
    engine_version     = $engineVersion
    notes              = "ue_agent capture"
    niagara_systems    = if ($man) { $man.niagara_systems_found } else { 0 }
    stills             = if ($man) { @($man.stills).Count } else { 0 }
    manifest_ok        = [bool]$man.ok
    stills_attempted   = if ($man) { [bool]$man.stills_attempted } else { $false }
    mode               = if ($man) { [string]$man.mode } else { "" }
    errors             = $errs
  }
  Write-Host "Report stills=$($result.stills) attempted=$($result.stills_attempted) errors=$($errs -join '; ')"

  if ([int]$result.stills -le 0) {
    $failMsg = "no_stills"
    if ($errs.Count -gt 0) {
      $failMsg = ([string]($errs | Select-Object -First 1))
      if ($failMsg.Length -gt 500) { $failMsg = $failMsg.Substring(0, 500) }
    }
    $fail = @{
      error                = $failMsg
      result               = $result
      scratch_project_path = (Split-Path $uproject -Parent)
      engine_version       = $engineVersion
    } | ConvertTo-Json -Depth 6
    Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$($Job.job_id)/report" `
      -ContentType "application/json" -Body $fail | Out-Null
    throw $failMsg
  }

  $report = @{
    result               = $result
    scratch_project_path = (Split-Path $uproject -Parent)
    engine_version       = $engineVersion
  } | ConvertTo-Json -Depth 6

  Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$($Job.job_id)/report" `
    -ContentType "application/json" -Body $report | Out-Null
}

Write-Host "Vellum UE agent polling $VellumBase every ${PollSeconds}s"
Write-Host "UI trigger: asset detail → Capture from Unreal"
Write-Host "Agent scripts: $Runner"
Write-Host "Repo root: $RepoRoot"
Write-Host "Agent fingerprint: editor-scenecapture-noblack (2026-07-13)"
# Fingerprint so we can tell if Windows is still on an old pull. Search the
# whole file instead of a fixed line number so this survives runner edits.
$runnerVersionLine = (Get-Content $Runner | Where-Object { $_ -match "Runner version:" } | Select-Object -First 1)
if (-not $runnerVersionLine) { $runnerVersionLine = "(no 'Runner version:' line found — old pull?)" }
Write-Host "Runner fingerprint: $($runnerVersionLine.Trim())"

while ($true) {
  try {
    $claimBody = @{ kinds = @("ue_capture") } | ConvertTo-Json
    $claimed = Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/claim" `
      -ContentType "application/json" -Body $claimBody
    if ($null -eq $claimed.job) {
      Start-Sleep -Seconds $PollSeconds
      continue
    }
    $job = $claimed.job
    try {
      Invoke-CaptureJob -Job $job
      Write-Host "Completed $($job.job_id)"
    } catch {
      $err = $_.Exception.Message
      Write-Host "Failed $($job.job_id): $err"
      $fail = @{ error = $err } | ConvertTo-Json
      try {
        Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$($job.job_id)/report" `
          -ContentType "application/json" -Body $fail | Out-Null
      } catch {
        Write-Host "Could not report failure: $($_.Exception.Message)"
      }
    }
  } catch {
    Write-Host "Poll error: $($_.Exception.Message)"
    Start-Sleep -Seconds $PollSeconds
  }
}
