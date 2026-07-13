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
  [string]$UeCmd = $env:VELLUM_UE_CMD,
  [switch]$RecoverOnly,
  [switch]$ReportHostSpecs,
  # Disaster / debug only — cold-starts UnrealEditor-Cmd per phase.
  [switch]$LegacyCmdRunner
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Heal = Join-Path $PSScriptRoot "host-heal.ps1"
$Runner = Join-Path $PSScriptRoot "run_vellum_capture.ps1"
$WorkerSupervisor = Join-Path $PSScriptRoot "vellum_ue_worker.ps1"
$Recover = Join-Path $PSScriptRoot "recover_vellum_capture.ps1"
. (Join-Path $PSScriptRoot "ue-hosts.ps1")

$UeHost = Get-UeHostProfile -RepoRoot $RepoRoot -HostName $HostName
if (-not $DefaultProject) { $DefaultProject = $UeHost.project }
$WorkerPort = if ($UeHost.worker_port) { [int]$UeHost.worker_port } else { 8771 }
$WorkerUrl = "http://127.0.0.1:$WorkerPort"

function Get-CaptureJobContext {
  param($Job)
  $payload = $Job.payload
  if (-not $payload) { $payload = @{} }
  $projectPath = if ($payload.project_path) { [string]$payload.project_path } else { "" }
  $uproject = Resolve-UprojectFromHost -HostProfile $UeHost `
    -PayloadProjectPath $projectPath -FallbackUproject $DefaultProject
  $forceCapture = $false
  if ($null -ne $payload.force -and "$($payload.force)" -match '^(1|True|true|yes)$') {
    $forceCapture = $true
  }
  $maxSystems = 0
  if ($null -ne $payload.max_systems -and "$($payload.max_systems)" -ne "") {
    $maxSystems = [int]$payload.max_systems
  }
  return @{
    Job            = $Job
    Payload        = $payload
    AssetId        = [string]$Job.asset_id
    Lane           = $(if ($payload.lane) { [string]$payload.lane } else { "slots" })
    Uproject       = $uproject
    ProjectDir     = (Split-Path $uproject -Parent)
    ContentRoot    = $(if ($payload.content_root) { [string]$payload.content_root } elseif ($UeHost.content_root) { [string]$UeHost.content_root } else { "/Game/FireworksV1" })
    EngineVersion  = $(if ($payload.engine_version) { [string]$payload.engine_version } elseif ($UeHost.engine_version) { [string]$UeHost.engine_version } else { "5.8" })
    IntakeRunId    = [string]$Job.intake_run_id
    MaxSystems     = $maxSystems
    Width          = $(if ($payload.width) { [int]$payload.width } else { 1920 })
    Height         = $(if ($payload.height) { [int]$payload.height } else { 1080 })
    ForceCapture   = $forceCapture
    JobId          = [string]$Job.job_id
  }
}

function Send-JobReport {
  param($Ctx, $Man, [string]$Notes)
  $errs = @()
  if ($Man -and $Man.errors) { $errs = @($Man.errors) }
  $stillsCount = 0
  if ($Man -and $Man.stills) { $stillsCount = @($Man.stills).Count }
  if ($Man -and $Man.frame_total) { $stillsCount = [Math]::Max($stillsCount, [int]$Man.frame_total) }
  $result = @{
    project_path       = $Ctx.ProjectDir
    engine_version     = $Ctx.EngineVersion
    notes              = $Notes
    ue_host            = $UeHost.id
    niagara_systems    = if ($Man) { $Man.niagara_systems_found } else { 0 }
    stills             = $stillsCount
    skipped_vault      = if ($Man -and $Man.skipped_vault) { @($Man.skipped_vault).Count } else { 0 }
    manifest_ok        = [bool]($Man.ok)
    stills_attempted   = if ($Man) { [bool]$Man.stills_attempted } else { $false }
    mode               = if ($Man) { [string]$Man.mode } else { "" }
    errors             = $errs
  }
  Write-Host "Report stills=$($result.stills) vault_skip=$($result.skipped_vault) ok=$($result.manifest_ok) errors=$($errs -join '; ')"
  if (-not $Man -or -not [bool]$Man.ok) {
    $failMsg = "no_stills"
    if ($errs.Count -gt 0) {
      $failMsg = ([string]($errs | Select-Object -First 1))
      if ($failMsg.Length -gt 500) { $failMsg = $failMsg.Substring(0, 500) }
    }
    $fail = @{
      error                = $failMsg
      result               = $result
      scratch_project_path = $Ctx.ProjectDir
      engine_version       = $Ctx.EngineVersion
    } | ConvertTo-Json -Depth 6
    Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$($Ctx.JobId)/report" `
      -ContentType "application/json" -Body $fail | Out-Null
    Write-Host "Reported failure $failMsg"
    return
  }
  $report = @{
    result               = $result
    scratch_project_path = $Ctx.ProjectDir
    engine_version       = $Ctx.EngineVersion
  } | ConvertTo-Json -Depth 6
  Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$($Ctx.JobId)/report" `
    -ContentType "application/json" -Body $report | Out-Null
}

function Invoke-CaptureViaWorker {
  param($Ctx)
  # Pull + restage + Ensure before every Capture so the operator never babysits.
  if (Test-Path $Heal) {
    Write-Host "Host self-heal before Capture…"
    & $Heal -HostName $UeHost.id -VellumBase $VellumBase
    if ($LASTEXITCODE -ne 0) { throw "host_heal_failed" }
  } else {
    Write-Host "Ensure Lookdev Worker on $WorkerUrl …"
    & $WorkerSupervisor -Ensure -HostName $UeHost.id -Port $WorkerPort
    if ($LASTEXITCODE -ne 0) { throw "worker_ensure_failed" }
  }

  $progressUri = "$VellumBase/api/jobs/$($Ctx.JobId)/progress"
  try {
    $prog = @{ message = "Lookdev Worker capture starting…" } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri $progressUri -ContentType "application/json" -Body $prog | Out-Null
  } catch { }

  $bodyObj = @{
    job_id         = $Ctx.JobId
    asset_id       = $Ctx.AssetId
    content_root   = $Ctx.ContentRoot
    max_systems    = $Ctx.MaxSystems
    width          = $Ctx.Width
    height         = $Ctx.Height
    frame_count    = 120
    frame_rate     = 30
    map_path       = "/Game/Vellum/Maps/VellumLookdevStudio"
    force          = [bool]$Ctx.ForceCapture
    force_studio   = [bool]$Ctx.ForceCapture
    vellum_base    = $VellumBase
  }
  $body = $bodyObj | ConvertTo-Json -Depth 6

  # Inbox + poll outbox — do not use a multi-hour blocking HTTP POST (that hung forever
  # while the old worker froze the editor with serve_forever on the main script thread).
  $outDir = Join-Path $Ctx.ProjectDir "Saved\VellumCapture"
  $inboxDir = Join-Path $outDir "worker-inbox"
  $outboxDir = Join-Path $outDir "worker-outbox"
  New-Item -ItemType Directory -Force -Path $inboxDir | Out-Null
  New-Item -ItemType Directory -Force -Path $outboxDir | Out-Null
  $inboxJob = Join-Path $inboxDir "job.json"
  $outboxResult = Join-Path $outboxDir "result.json"
  if (Test-Path $outboxResult) { Remove-Item -Force $outboxResult }
  Set-Content -Path $inboxJob -Value $body -Encoding UTF8
  Write-Host "Wrote worker inbox $inboxJob"

  # Kick the in-UE queue if HTTP is up (best-effort; inbox is the source of truth).
  try {
    Invoke-RestMethod -Method Post -Uri "$WorkerUrl/v1/capture" `
      -ContentType "application/json" -Body $body -TimeoutSec 5 | Out-Null
  } catch {
    Write-Host "HTTP kick skipped/busy (inbox still queued): $($_.Exception.Message)"
  }

  $deadline = (Get-Date).AddHours(6)
  $lastNote = ""
  $capture = $null
  while ((Get-Date) -lt $deadline) {
    if (Test-Path $outboxResult) {
      try {
        $capture = Get-Content $outboxResult -Raw | ConvertFrom-Json
        Write-Host "Worker outbox ready ok=$($capture.ok)"
        break
      } catch {
        Start-Sleep -Seconds 2
        continue
      }
    }
    $note = "Waiting for Lookdev Worker…"
    try {
      $h = Invoke-RestMethod -Method Get -Uri "$WorkerUrl/health" -TimeoutSec 3
      $note = "Worker busy=$($h.busy) studio_build=$($h.studio_build) version=$($h.version)"
    } catch { }
    if ($note -ne $lastNote) {
      try {
        $prog = @{ message = $note } | ConvertTo-Json
        Invoke-RestMethod -Method Post -Uri $progressUri -ContentType "application/json" -Body $prog | Out-Null
      } catch { }
      $lastNote = $note
      Write-Host $note
    }
    Start-Sleep -Seconds 5
  }
  if (-not $capture) {
    throw "worker_timeout: no outbox result under $outboxResult"
  }

  # Ingest heroes/sequences from MRQ dirs the worker wrote.
  if (Test-Path $Recover) {
    Write-Host "Worker capture returned — ingesting MRQ dirs"
    if ($Ctx.ForceCapture) {
      & $Recover -VellumBase $VellumBase -HostName $UeHost.id -AssetId $Ctx.AssetId -Force
    } else {
      & $Recover -VellumBase $VellumBase -HostName $UeHost.id -AssetId $Ctx.AssetId
    }
  }

  $outDir = Join-Path $Ctx.ProjectDir "Saved\VellumCapture"
  $manifestPath = Join-Path $outDir "manifest.json"
  $man = $null
  if (Test-Path $manifestPath) {
    $man = Get-Content $manifestPath -Raw | ConvertFrom-Json
  } elseif ($capture) {
    $man = $capture
  }
  Send-JobReport -Ctx $Ctx -Man $man -Notes "ue_agent lookdev-worker host=$($UeHost.id) force=$($Ctx.ForceCapture)"
}

function Invoke-CaptureViaLegacyRunner {
  param($Ctx)
  $resolvedUe = Find-UeCmdFromHost -HostProfile $UeHost -Hint $UeCmd
  Write-Host "Using UE Cmd (legacy): $resolvedUe"
  Write-Host "Running legacy capture for $($Ctx.AssetId) ($($Ctx.JobId)) force=$($Ctx.ForceCapture)"
  $env:VELLUM_JOB_ID = $Ctx.JobId
  $runnerArgs = @{
    Project        = $Ctx.Uproject
    AssetId        = $Ctx.AssetId
    ContentRoot    = $Ctx.ContentRoot
    VellumBase     = $VellumBase
    Lane           = $Ctx.Lane
    EngineVersion  = $Ctx.EngineVersion
    IntakeRunId    = $Ctx.IntakeRunId
    UeCmd          = $resolvedUe
    MaxSystems     = $Ctx.MaxSystems
    Width          = $Ctx.Width
    Height         = $Ctx.Height
    JobId          = $Ctx.JobId
    HostName       = $UeHost.id
  }
  if ($Ctx.ForceCapture) {
    & $Runner @runnerArgs -ForceCapture
  } else {
    & $Runner @runnerArgs
  }
  $outDir = Join-Path $Ctx.ProjectDir "Saved\VellumCapture"
  $manifestPath = Join-Path $outDir "manifest.json"
  $man = $null
  if (Test-Path $manifestPath) {
    $man = Get-Content $manifestPath -Raw | ConvertFrom-Json
  }
  Send-JobReport -Ctx $Ctx -Man $man -Notes "ue_agent legacy_cmd host=$($UeHost.id) force=$($Ctx.ForceCapture)"
}

function Invoke-CaptureJob {
  param($Job)
  $ctx = Get-CaptureJobContext -Job $Job
  Write-Host "Using project: $($ctx.Uproject)"
  if (-not $LegacyCmdRunner) {
    # Primary path: warm Lookdev Worker. Do NOT silently fall back to Cmd-per-phase —
    # that reopens desert-map E2E and hides real worker failures from Vellum.
    Invoke-CaptureViaWorker -Ctx $ctx
    return
  }
  Invoke-CaptureViaLegacyRunner -Ctx $ctx
}

Write-Host "Vellum UE agent polling $VellumBase every ${PollSeconds}s"
Write-Host "UI trigger: asset detail → Capture from Unreal"
Write-Host "Host profile: $($UeHost.id) ($($UeHost.label), $($UeHost.role)) — config active=$($UeHost.active_in_config)"
Write-Host "Agent scripts: $Runner"
Write-Host "Repo root: $RepoRoot"
Write-Host "Agent fingerprint: lookdev-worker (2026-07-13)"
Write-Host "Capture mode: $(if ($LegacyCmdRunner) { 'legacy Cmd-per-phase' } else { "Lookdev Worker $WorkerUrl (self-heal on each job)" })"
$runnerVersionLine = (Get-Content $Runner | Where-Object { $_ -match "Runner version:" } | Select-Object -First 1)
if (-not $runnerVersionLine) { $runnerVersionLine = "(no 'Runner version:' line found — old pull?)" }
Write-Host "Legacy runner fingerprint: $($runnerVersionLine.Trim())"

# Startup heal once (git pull + Ensure). Watchdog may restart this service afterward.
if ((-not $LegacyCmdRunner) -and (Test-Path $Heal) -and (-not $RecoverOnly) -and (-not $ReportHostSpecs)) {
  try {
    Write-Host "Startup host-heal…"
    & $Heal -HostName $UeHost.id -VellumBase $VellumBase
  } catch {
    Write-Host "WARNING: startup host-heal failed: $($_.Exception.Message)"
  }
}
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

$ReportSpecs = Join-Path $PSScriptRoot "report_host_specs.ps1"
if ($ReportHostSpecs) {
  if (-not (Test-Path $ReportSpecs)) { throw "report_host_specs.ps1 missing" }
  & $ReportSpecs -VellumBase $VellumBase -HostName $UeHost.id
  exit $LASTEXITCODE
}

# Best-effort hardware snapshot so Vellum can size work to this workstation.
if (Test-Path $ReportSpecs) {
  try {
    Write-Host "Reporting host specs for $($UeHost.id)…"
    & $ReportSpecs -VellumBase $VellumBase -HostName $UeHost.id | Out-Null
  } catch {
    Write-Host "WARNING: host specs report failed: $($_.Exception.Message)"
  }
}

if ($RecoverOnly) {
  $Recover = Join-Path $PSScriptRoot "recover_vellum_capture.ps1"
  if (-not (Test-Path $Recover)) { throw "recover_vellum_capture.ps1 missing" }
  Write-Host "RecoverOnly: ingesting finished MRQ dirs under Saved/VellumCapture/mrq (no UE launch, no job claim)"
  if ($env:VELLUM_FORCE_CAPTURE -match '^(1|true|yes)$') {
    & $Recover -VellumBase $VellumBase -HostName $UeHost.id -AssetId "fireworks-vol-1-niagara" -Force
  } else {
    & $Recover -VellumBase $VellumBase -HostName $UeHost.id -AssetId "fireworks-vol-1-niagara"
  }
  exit $LASTEXITCODE
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
