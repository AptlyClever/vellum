#Requires -Version 5.1
<#
.SYNOPSIS
  Background Windows agent: claim Vellum ue_capture jobs and run Unreal capture.

.DESCRIPTION
  Keep this running on the UE workstation. Operator uses the Vellum UI button
  "Capture from Unreal" — this agent does the Unreal work and reports back.

  Hosts (profiles): config/ue-hosts.json — Aurora (primary) / Borealis (secondary).
  Only one agent should poll at a time. Active host defaults from that file.

.EXAMPLE
  pwsh -File tools/unreal/vellum_ue_agent.ps1
  pwsh -File tools/unreal/vellum_ue_agent.ps1 -HostName aurora
  $env:VELLUM_UE_HOST = "borealis"; pwsh -File tools/unreal/vellum_ue_agent.ps1
#>
param(
  [string]$VellumBase = "http://192.168.68.93:8770",
  [int]$PollSeconds = 5,
  [string]$HostName = "",
  [string]$DefaultProject = $(if ($env:VELLUM_UE_PROJECT) { $env:VELLUM_UE_PROJECT } else { "" }),
  [string]$UeCmd = $env:VELLUM_UE_CMD
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Runner = Join-Path $PSScriptRoot "run_vellum_capture.ps1"
. (Join-Path $PSScriptRoot "ue-hosts.ps1")

$UeHost = Get-UeHostProfile -RepoRoot $RepoRoot -HostName $HostName
if (-not $DefaultProject) { $DefaultProject = $UeHost.project }

function Invoke-CaptureJob {
  param($Job)
  $payload = $Job.payload
  if (-not $payload) { $payload = @{} }
  $assetId = [string]$Job.asset_id
  $lane = if ($payload.lane) { [string]$payload.lane } else { "slots" }
  $projectPath = if ($payload.project_path) { [string]$payload.project_path } else { "" }
  $uproject = Resolve-UprojectFromHost -HostProfile $UeHost `
    -PayloadProjectPath $projectPath -FallbackUproject $DefaultProject
  Write-Host "Using project: $uproject"
  $contentRoot = if ($payload.content_root) {
    [string]$payload.content_root
  } elseif ($UeHost.content_root) {
    [string]$UeHost.content_root
  } else {
    "/Game/FireworksV1"
  }
  $engineVersion = if ($payload.engine_version) {
    [string]$payload.engine_version
  } elseif ($UeHost.engine_version) {
    [string]$UeHost.engine_version
  } else {
    "5.8"
  }
  $intakeRunId = [string]$Job.intake_run_id
  $maxSystems = if ($payload.max_systems) { [int]$payload.max_systems } else { 3 }
  $width = if ($payload.width) { [int]$payload.width } else { 1920 }
  $height = if ($payload.height) { [int]$payload.height } else { 1080 }

  $resolvedUe = Find-UeCmdFromHost -HostProfile $UeHost -Hint $UeCmd
  Write-Host "Using UE Cmd: $resolvedUe"
  Write-Host "Running capture for $assetId ($($Job.job_id)) on host $($UeHost.id)"
  $env:VELLUM_JOB_ID = [string]$Job.job_id
  & $Runner `
    -Project $uproject `
    -AssetId $assetId `
    -ContentRoot $contentRoot `
    -VellumBase $VellumBase `
    -Lane $lane `
    -EngineVersion $engineVersion `
    -IntakeRunId $intakeRunId `
    -UeCmd $resolvedUe `
    -MaxSystems $maxSystems `
    -Width $width `
    -Height $height `
    -JobId ([string]$Job.job_id) `
    -HostName $UeHost.id

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
    notes              = "ue_agent capture host=$($UeHost.id)"
    ue_host            = $UeHost.id
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
    # Do not throw — already reported; avoids 409 double-report in the outer catch.
    Write-Host "Reported failure $failMsg"
    return
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
Write-Host "Host profile: $($UeHost.id) ($($UeHost.label), $($UeHost.role)) — config active=$($UeHost.active_in_config)"
Write-Host "Agent scripts: $Runner"
Write-Host "Repo root: $RepoRoot"
Write-Host "Agent fingerprint: mrq-niagara-lifecycle (2026-07-13)"
$runnerVersionLine = (Get-Content $Runner | Where-Object { $_ -match "Runner version:" } | Select-Object -First 1)
if (-not $runnerVersionLine) { $runnerVersionLine = "(no 'Runner version:' line found — old pull?)" }
Write-Host "Runner fingerprint: $($runnerVersionLine.Trim())"
try {
  Write-Host "Resolved UE Cmd (preflight): $(Find-UeCmdFromHost -HostProfile $UeHost -Hint $UeCmd)"
} catch {
  Write-Host "WARNING: $($_.Exception.Message)"
}
try {
  Write-Host "Resolved project (preflight): $(Resolve-UprojectFromHost -HostProfile $UeHost -FallbackUproject $DefaultProject)"
} catch {
  Write-Host "WARNING: $($_.Exception.Message)"
}

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
