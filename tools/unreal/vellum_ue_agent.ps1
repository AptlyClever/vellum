#Requires -Version 5.1
<#
.SYNOPSIS
  RETIRED Capture agent (prototype-v0). Do not run as product control plane.

.DESCRIPTION
  Frozen 2026-07-14. Product SoT: docs/asset-pipeline-product.md
  Unpark phrase (operator only): Unpark: Capture Agent

  Historical: claimed Vellum ue_capture jobs and drove Unreal capture.
  Hosts (profiles): config/ue-hosts.json - Aurora (primary) / Borealis (secondary).

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
  # Opt-in only (FROZEN): warm Lookdev Worker on :8771. Default is Epic batch Cmd.
  [switch]$UseLookdevWorker,
  # Alias kept for old scripts — forces Epic batch Cmd (same as default).
  [switch]$LegacyCmdRunner,
  # Parallel Windows worker: Fab/scan/stage while primary owns ue_capture.
  [switch]$SidecarOnly,
  # Restart without host-heal (do not bounce UE/agent task mid-capture).
  [switch]$SkipHostHeal
)
# RETIRED 2026-07-14 — see docs/asset-pipeline-product.md
if ($env:VELLUM_ALLOW_RETIRED_CAPTURE_AGENT -ne "1") {
  Write-Error @"
vellum_ue_agent.ps1 is RETIRED (prototype-v0).
Product path: docs/asset-pipeline-product.md + tools/pipeline/
To run anyway (archaeology only): `$env:VELLUM_ALLOW_RETIRED_CAPTURE_AGENT = '1'
"@
  exit 2
}
if ($LegacyCmdRunner) {
  $UseLookdevWorker = $false
}

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Heal = Join-Path $PSScriptRoot "host-heal.ps1"
$Runner = Join-Path $PSScriptRoot "run_vellum_capture.ps1"
$StagePy = Join-Path $PSScriptRoot "stage_pack_to_vellum.py"
$WorkerSupervisor = Join-Path $PSScriptRoot "vellum_ue_worker.ps1"
$Recover = Join-Path $PSScriptRoot "recover_vellum_capture.ps1"
. (Join-Path $PSScriptRoot "ue-hosts.ps1")
. (Join-Path $PSScriptRoot "ps-native.ps1")

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
  param($Ctx, [switch]$AttachOnly)
  $progressUri = "$VellumBase/api/jobs/$($Ctx.JobId)/progress"
  $outDir = Join-Path $Ctx.ProjectDir "Saved\VellumCapture"
  $inboxDir = Join-Path $outDir "worker-inbox"
  $outboxDir = Join-Path $outDir "worker-outbox"
  New-Item -ItemType Directory -Force -Path $inboxDir | Out-Null
  New-Item -ItemType Directory -Force -Path $outboxDir | Out-Null
  $outboxResult = Join-Path $outboxDir "result.json"

  if (-not $AttachOnly) {
    # Heartbeat BEFORE Ensure — Ensure can exceed the hub stale silence window.
    try {
      $prog = @{ message = "Ensure Lookdev Worker..." } | ConvertTo-Json
      Invoke-RestMethod -Method Post -Uri $progressUri -ContentType "application/json" -Body $prog | Out-Null
    } catch { }

    # Do NOT run host-heal (git pull) mid-Capture — that blows away scp'd hotfixes and
    # can silence progress long enough for the hub to fail the job as stale.
    Write-Host "Ensure Lookdev Worker on $WorkerUrl ..."
    & $WorkerSupervisor -Ensure -HostName $UeHost.id -Port $WorkerPort
    if ($LASTEXITCODE -ne 0) { throw "worker_ensure_failed" }

    try {
      $prog = @{ message = "Lookdev Worker capture starting..." } | ConvertTo-Json
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

    # Fresh start only — AttachOnly must not wipe a finishing outbox.
    if (Test-Path $outboxResult) { Remove-Item -Force $outboxResult }
    $inboxJob = Join-Path $inboxDir "job.json"
    Set-Content -Path $inboxJob -Value $body -Encoding UTF8
    Write-Host "Wrote worker inbox $inboxJob"

    try {
      Invoke-RestMethod -Method Post -Uri "$WorkerUrl/v1/capture" `
        -ContentType "application/json" -Body $body -TimeoutSec 5 | Out-Null
    } catch {
      Write-Host "HTTP kick skipped/busy (inbox still queued): $($_.Exception.Message)"
    }
  } else {
    Write-Host "ATTACH to in-flight capture job=$($Ctx.JobId) asset=$($Ctx.AssetId) (no inbox rewrite)"
    try {
      $prog = @{ message = "Agent reattached — waiting for Lookdev Worker outbox..." } | ConvertTo-Json
      Invoke-RestMethod -Method Post -Uri $progressUri -ContentType "application/json" -Body $prog | Out-Null
    } catch { }
  }

  $deadline = (Get-Date).AddHours(6)
  $lastNote = ""
  $pollStarted = Get-Date
  $lastProgressAt = (Get-Date).AddSeconds(-60)
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
    $note = "Waiting for Lookdev Worker..."
    try {
      $h = Invoke-RestMethod -Method Get -Uri "$WorkerUrl/health" -TimeoutSec 3
      $note = "Worker busy=$($h.busy) studio_build=$($h.studio_build) version=$($h.version)"
    } catch { }
    $elapsed = [int]((Get-Date) - $pollStarted).TotalSeconds
    $dueHeartbeat = ((Get-Date) - $lastProgressAt).TotalSeconds -ge 30
    if ($note -ne $lastNote -or $dueHeartbeat) {
      try {
        $prog = @{ message = "$note · elapsed ${elapsed}s" } | ConvertTo-Json
        Invoke-RestMethod -Method Post -Uri $progressUri -ContentType "application/json" -Body $prog | Out-Null
      } catch { }
      $lastNote = $note
      $lastProgressAt = Get-Date
      Write-Host $note
    }
    # Publish util while MRQ runs (sidecar is a parallel process — do not block outbox poll).
    if (($elapsed % 60) -lt 6) {
      try {
        $u = Publish-VellumHostUtilization
        if ($u -and $null -ne $u.gpu_util_pct) {
          Write-Host ("Host util gpu={0}% mem={1}/{2}MB editor={3}MB idle_tax={4}" -f `
            $u.gpu_util_pct, $u.gpu_mem_used_mb, $u.gpu_mem_total_mb, $u.editor_rss_mb, $u.idle_tax)
        }
      } catch { }
    }
    Start-Sleep -Seconds 5
  }
  if (-not $capture) {
    throw "worker_timeout: no outbox result under $outboxResult"
  }

  # Do not Recover leftover Fireworks frames after a failed author — that hangs
  # the agent for hours while the hub still shows the capture as running.
  $captureOk = $false
  try { $captureOk = [bool]$capture.ok } catch { $captureOk = $false }
  $frameTotal = 0
  try { $frameTotal = [int]$capture.frame_total } catch { $frameTotal = 0 }
  if ($captureOk -and $frameTotal -le 0) {
    Write-Host "Worker claimed ok but frame_total=$frameTotal - treating as failure"
    $captureOk = $false
    try {
      if (-not $capture.error) { $capture | Add-Member -NotePropertyName error -NotePropertyValue "mrq_zero_frames" -Force }
      $capture.ok = $false
      $capture.error = "mrq_zero_frames"
    } catch { }
  }
  if ($captureOk -and (Test-Path $Recover)) {
    Write-Host "Worker capture returned ok - ingesting MRQ dirs"
    if ($Ctx.ForceCapture) {
      & $Recover -VellumBase $VellumBase -HostName $UeHost.id -AssetId $Ctx.AssetId -Force
    } else {
      & $Recover -VellumBase $VellumBase -HostName $UeHost.id -AssetId $Ctx.AssetId
    }
  } elseif (-not $captureOk) {
    Write-Host "Worker capture failed ($($capture.error)) - skip Recover ingest"
  }

  $outDir = Join-Path $Ctx.ProjectDir "Saved\VellumCapture"
  $manifestPath = Join-Path $outDir "manifest.json"
  $man = $null
  if ($captureOk -and (Test-Path $manifestPath)) {
    $man = Get-Content $manifestPath -Raw | ConvertFrom-Json
  } elseif ($capture) {
    $man = $capture
  }
  Send-JobReport -Ctx $Ctx -Man $man -Notes "ue_agent lookdev-worker host=$($UeHost.id) force=$($Ctx.ForceCapture)"
}

function Invoke-CaptureViaEpicBatchCmd {
  param($Ctx)
  $resolvedUe = Find-UeCmdFromHost -HostProfile $UeHost -Hint $UeCmd
  Write-Host "Using UnrealEditor-Cmd (Epic batch MRQ): $resolvedUe"
  Write-Host "Running Epic batch capture for $($Ctx.AssetId) ($($Ctx.JobId)) force=$($Ctx.ForceCapture)"
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
  Send-JobReport -Ctx $Ctx -Man $man -Notes "ue_agent epic_batch_cmd host=$($UeHost.id) force=$($Ctx.ForceCapture)"
}

function Invoke-HostScanJob {
  param($Job)
  $ReportSpecs = Join-Path $PSScriptRoot "report_host_specs.ps1"
  if (-not (Test-Path $ReportSpecs)) { throw "report_host_specs.ps1 missing" }
  Write-Host "host_scan: refreshing Content folders via report_host_specs"
  & $ReportSpecs -VellumBase $VellumBase -HostName $UeHost.id | Out-Null
  $ok = @{
    result = @{
      ok    = $true
      notes = "host_scan host=$($UeHost.id)"
    }
  } | ConvertTo-Json -Depth 5
  Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$($Job.job_id)/report" `
    -ContentType "application/json" -Body $ok | Out-Null
}

function Invoke-OpenEditorJob {
  param($Job)
  $OpenPy = Join-Path $PSScriptRoot "open_aurora_vellum.ps1"
  if (-not (Test-Path $OpenPy)) { throw "open_aurora_vellum.ps1 missing" }
  $proj = [string]$Job.payload.project
  if (-not $proj) { $proj = [string]$UeHost.project }
  $editor = [string]$UeHost.ue_editor
  Write-Host "host_open_editor: $editor $proj"
  & $OpenPy -Project $proj -UeEditor $editor
  $ok = @{
    result = @{
      ok      = $true
      project = $proj
      notes   = "host_open_editor host=$($UeHost.id)"
    }
  } | ConvertTo-Json -Depth 5
  Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$($Job.job_id)/report" `
    -ContentType "application/json" -Body $ok | Out-Null
}

function Invoke-StageJob {
  param($Job)
  $payload = $Job.payload
  if (-not $payload) { $payload = @{} }
  $assetId = [string]$Job.asset_id
  $hostPath = [string]$payload.host_content_path
  $folder = [string]$payload.content_folder_name
  if (-not $hostPath) { throw "host_stage missing host_content_path" }
  if (-not (Test-Path $StagePy)) { throw "stage_pack_to_vellum.py missing" }
  $py = Find-VellumPython
  $uproject = Resolve-UprojectFromHost -HostProfile $UeHost -FallbackUproject $DefaultProject
  $projDir = Split-Path $uproject -Parent
  $work = Join-Path $projDir "Saved\VellumStage"
  New-Item -ItemType Directory -Force -Path $work | Out-Null
  $progressUri = "$VellumBase/api/jobs/$($Job.job_id)/progress"
  try {
    $prog = @{ message = "Staging $assetId from $hostPath" } | ConvertTo-Json -Compress
    Invoke-RestMethod -Method Post -Uri $progressUri -ContentType "application/json" -Body $prog -TimeoutSec 5 | Out-Null
  } catch {}
  $stageArgs = @(
    $StagePy,
    "--vellum-base", $VellumBase,
    "--asset-id", $assetId,
    "--host-content-path", $hostPath,
    "--job-id", [string]$Job.job_id,
    "--work-dir", $work
  )
  if ($folder) { $stageArgs += @("--content-folder-name", $folder) }
  Write-Host "Stage via $py"
  $ec = Invoke-ExeQuiet -FilePath $py -ArgumentList $stageArgs -TimeoutSec 14400
  # stage_pack_to_vellum.py reports the job itself; agent report is best-effort.
  $already = $null
  try {
    $already = Invoke-RestMethod -Method Get -Uri "$VellumBase/api/jobs/$($Job.job_id)" -TimeoutSec 15
  } catch {}
  if ($already -and $already.status -in @("succeeded", "failed", "cancelled")) {
    if ($already.status -ne "succeeded" -and $ec -ne 0) {
      throw "stage_pack_failed exit=$ec status=$($already.status)"
    }
    Write-Host "Stage job already $($already.status) (python reported)"
    return
  }
  if ($ec -ne 0) { throw "stage_pack_failed exit=$ec" }
  $ok = @{
    result = @{
      ok                = $true
      host_content_path = $hostPath
      notes             = "host_stage host=$($UeHost.id)"
    }
  } | ConvertTo-Json -Depth 5
  Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$($Job.job_id)/report" `
    -ContentType "application/json" -Body $ok -TimeoutSec 60 | Out-Null
}

function Invoke-FabInstallJob {
  param($Job)
  $payload = $Job.payload
  if (-not $payload) { $payload = @{} }
  $assetId = [string]$Job.asset_id
  $InstallPs1 = Join-Path $PSScriptRoot "install_fab_pack_from_vault_cache.ps1"
  if (-not (Test-Path $InstallPs1)) { throw "install_fab_pack_from_vault_cache.ps1 missing" }

  $relPaths = @()
  if ($payload.content_rel_paths) {
    foreach ($p in @($payload.content_rel_paths)) {
      if ($p) { $relPaths += [string]$p }
    }
  }
  if ($relPaths.Count -eq 0) { throw "host_fab_install missing content_rel_paths" }

  $uproject = Resolve-UprojectFromHost -HostProfile $UeHost -FallbackUproject $DefaultProject
  $projDir = Split-Path $uproject -Parent
  $projectContent = [string]$payload.project_content
  if (-not $projectContent) {
    $projectContent = Join-Path $projDir "Content"
  }
  $outJson = Join-Path $projDir "Saved\VellumFabInstall\$assetId.json"
  New-Item -ItemType Directory -Force -Path (Split-Path $outJson -Parent) | Out-Null

  $progressUri = "$VellumBase/api/jobs/$($Job.job_id)/progress"
  try {
    $prog = @{ message = "Fab install $assetId from VaultCache → $projectContent" } | ConvertTo-Json -Compress
    Invoke-RestMethod -Method Post -Uri $progressUri -ContentType "application/json" -Body $prog -TimeoutSec 5 | Out-Null
  } catch {}

  Write-Host "host_fab_install: $assetId paths=$($relPaths -join ';')"
  & $InstallPs1 -ProjectContent $projectContent -ContentRelPaths $relPaths -OutJson $outJson
  $ec = $LASTEXITCODE
  $installResult = $null
  if (Test-Path -LiteralPath $outJson) {
    $installResult = Get-Content -LiteralPath $outJson -Raw | ConvertFrom-Json
  }
  if ($ec -ne 0 -or -not $installResult -or -not $installResult.ok) {
    $err = if ($installResult -and $installResult.error) { [string]$installResult.error } else { "fab_install_failed exit=$ec" }
    throw $err
  }

  $hostPath = [string]$installResult.host_content_path
  $folder = [string]$installResult.content_folder_name
  $ReportSpecs = Join-Path $PSScriptRoot "report_host_specs.ps1"
  if (Test-Path $ReportSpecs) {
    try {
      & $ReportSpecs -VellumBase $VellumBase -HostName $UeHost.id -ExtraContentPaths @($hostPath) | Out-Null
    } catch {
      Write-Host "WARNING: post-install host_scan failed: $($_.Exception.Message)"
    }
  }

  # Mark in_project via asset patch.
  try {
    $contentRoot = if ($folder) { "/Game/$folder" } else { $null }
    $patch = @{
      host_content_path = $hostPath
      ue_in_project     = "in_project"
      content_root      = $contentRoot
      redemption_status = "redeemed"
    } | ConvertTo-Json -Compress
    Invoke-RestMethod -Method Patch -Uri "$VellumBase/api/assets/$assetId" `
      -ContentType "application/json" -Body $patch | Out-Null
  } catch {
    Write-Host "WARNING: asset patch failed: $($_.Exception.Message)"
  }

  $autoStage = $true
  if ($null -ne $payload.auto_stage -and "$($payload.auto_stage)" -match '^(0|False|false|no)$') {
    $autoStage = $false
  }
  $stageJobId = $null
  if ($autoStage -and $hostPath) {
    try {
      $stageBody = @{
        host_content_path   = $hostPath
        content_folder_name = $folder
        ue_host             = $UeHost.id
      } | ConvertTo-Json -Compress
      $staged = Invoke-RestMethod -Method Post -Uri "$VellumBase/api/assets/$assetId/import/stage" `
        -ContentType "application/json" -Body $stageBody
      if ($staged.job) { $stageJobId = [string]$staged.job.job_id }
      Write-Host "auto-stage queued: $stageJobId"
    } catch {
      Write-Host "WARNING: auto-stage enqueue failed: $($_.Exception.Message)"
    }
  }

  $ok = @{
    result = @{
      ok                 = $true
      host_content_path  = $hostPath
      content_folder_name = $folder
      source_path        = [string]$installResult.source_path
      bytes              = [int64]$installResult.bytes
      stage_job_id       = $stageJobId
      notes              = "host_fab_install host=$($UeHost.id)"
    }
  } | ConvertTo-Json -Depth 6
  Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$($Job.job_id)/report" `
    -ContentType "application/json" -Body $ok | Out-Null
}


function Get-VellumHostUtilization {
  $util = [ordered]@{
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
  }
  try {
    $row = & nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1
    if ($row) {
      $parts = @($row -split ",") | ForEach-Object { $_.Trim() }
      if ($parts.Count -ge 4) {
        $util.gpu_name = $parts[0]
        $util.gpu_util_pct = [int]$parts[1]
        $util.gpu_mem_used_mb = [int]$parts[2]
        $util.gpu_mem_total_mb = [int]$parts[3]
      }
    }
  } catch { }
  try {
    $ue = Get-Process UnrealEditor -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($ue) { $util.editor_rss_mb = [int]($ue.WorkingSet64 / 1MB) }
  } catch { }
  try {
    $h = Invoke-RestMethod -Method Get -Uri "$WorkerUrl/health" -TimeoutSec 2
    $util.worker_busy = [bool]$h.busy
    $util.worker_version = [string]$h.version
    $util.idle_tax = (-not [bool]$h.busy) -and (($util.gpu_util_pct -as [int]) -lt 5)
  } catch { }
  return $util
}

function Publish-VellumHostUtilization {
  try {
    $util = Get-VellumHostUtilization
    $body = @{ host_id = $UeHost.id; specs = @{ utilization = $util } } | ConvertTo-Json -Depth 6
    Invoke-RestMethod -Method Post -Uri "$VellumBase/api/ue/hosts/util" -ContentType "application/json" -Body $body -TimeoutSec 10 | Out-Null
    return $util
  } catch {
    return $null
  }
}

function Invoke-VellumSidecarClaimOnce {
  # While MRQ owns the editor, keep the rest of Aurora busy (Fab install / scan / stage).
  $claimBody = @{ kinds = @("ue_stage", "host_stage", "host_scan", "host_fab_install") } | ConvertTo-Json
  try {
    $claimed = Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/claim" `
      -ContentType "application/json" -Body $claimBody -TimeoutSec 30
  } catch {
    return $false
  }
  if ($null -eq $claimed.job) { return $false }
  $job = $claimed.job
  Write-Host "Sidecar claimed $($job.job_id) kind=$($job.kind) asset=$($job.asset_id)"
  try {
    Invoke-CaptureJob -Job $job
    Write-Host "Sidecar completed $($job.job_id)"
  } catch {
    $err = $_.Exception.Message
    Write-Host "Sidecar failed $($job.job_id): $err"
    try {
      $fail = @{ error = $err } | ConvertTo-Json
      Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$($job.job_id)/report" `
        -ContentType "application/json" -Body $fail | Out-Null
    } catch { }
  }
  return $true
}


function Resume-OrphanedCaptureIfNeeded {
  # After agent death/restart: hub still has running ue_capture and UE may still be busy.
  # Reattach to outbox instead of idling (that orphans the job + wastes the GPU).
  try {
    $listed = Invoke-RestMethod -Method Get -Uri "$VellumBase/api/jobs?status=running&limit=20" -TimeoutSec 30
  } catch {
    return $false
  }
  $job = $null
  foreach ($j in @($listed.jobs)) {
    if ([string]$j.kind -eq "ue_capture") { $job = $j; break }
  }
  if ($null -eq $job) { return $false }
  Write-Host "Found orphaned running capture $($job.job_id) asset=$($job.asset_id) — attaching"
  $ctx = Get-CaptureJobContext -Job $job
  Invoke-CaptureViaWorker -Ctx $ctx -AttachOnly
  return $true
}

function Invoke-CaptureJob {
  param($Job)
  if ([string]$Job.kind -eq "ue_stage" -or [string]$Job.kind -eq "host_stage") {
    Invoke-StageJob -Job $Job
    return
  }
  if ([string]$Job.kind -eq "host_scan") {
    Invoke-HostScanJob -Job $Job
    return
  }
  if ([string]$Job.kind -eq "host_open_editor") {
    Invoke-OpenEditorJob -Job $Job
    return
  }
  if ([string]$Job.kind -eq "host_fab_install") {
    Invoke-FabInstallJob -Job $Job
    return
  }
  $ctx = Get-CaptureJobContext -Job $Job
  Write-Host "Using project: $($ctx.Uproject)"
  if ($UseLookdevWorker) {
    Invoke-CaptureViaWorker -Ctx $ctx
    return
  }
  # Default (binding docs/capture-hosting-decision.md): Epic batch Cmd.
  Invoke-CaptureViaEpicBatchCmd -Ctx $ctx
}

Write-Host "Vellum UE agent polling $VellumBase every ${PollSeconds}s"
Write-Host "UI trigger: asset detail → Capture from Unreal"
Write-Host "Host profile: $($UeHost.id) ($($UeHost.label), $($UeHost.role)) - config active=$($UeHost.active_in_config)"
Write-Host "Agent scripts: $Runner"
Write-Host "Repo root: $RepoRoot"
Write-Host "Agent fingerprint: epic-batch-mrq-cmd (2026-07-14)"
Write-Host "Capture mode: $(if ($UseLookdevWorker) { "Lookdev Worker $WorkerUrl (FROZEN opt-in)" } else { "Epic batch Cmd — run_vellum_capture.ps1" })"
$runnerVersionLine = (Get-Content $Runner | Where-Object { $_ -match "Runner version:" } | Select-Object -First 1)
if (-not $runnerVersionLine) { $runnerVersionLine = "(no Runner version line found - old pull?)" }
Write-Host "Epic batch runner fingerprint: $($runnerVersionLine.Trim())"

# Startup: always git-pull + restart service if SHA moved (never kill Unreal for worker).
if ((Test-Path $Heal) -and (-not $RecoverOnly) -and (-not $ReportHostSpecs) -and (-not $SidecarOnly) -and (-not $SkipHostHeal)) {
  try {
    Write-Host "Startup host-heal (git + agent bounce if needed)..."
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
if ((Test-Path $ReportSpecs) -and (-not $SidecarOnly)) {
  try {
    Write-Host "Reporting host specs for $($UeHost.id)..."
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


if ($SidecarOnly) {
  Write-Host "Vellum sidecar agent (Fab/scan/stage) polling $VellumBase host=$($UeHost.id)"
  while ($true) {
    try {
      try { [void](Publish-VellumHostUtilization) } catch { }
      $did = $false
      try { $did = [bool](Invoke-VellumSidecarClaimOnce) } catch { $did = $false }
      if (-not $did) { Start-Sleep -Seconds $PollSeconds }
    } catch {
      Write-Host "Sidecar poll error: $($_.Exception.Message)"
      Start-Sleep -Seconds $PollSeconds
    }
  }
  exit 0
}

# Ensure a sidecar process is alive so Fab/scan overlap ue_capture (uses the rest of Aurora).
try {
  $marker = "vellum_ue_agent.ps1*SidecarOnly"
  $alive = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'SidecarOnly' -and $_.CommandLine -match 'vellum_ue_agent' }
  if (-not $alive) {
    $args = @(
      "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath,
      "-VellumBase", $VellumBase, "-HostName", $UeHost.id, "-SidecarOnly"
    )
    Start-Process -FilePath "pwsh" -ArgumentList $args -WindowStyle Hidden | Out-Null
    Write-Host "Started sidecar agent (host_fab_install / scan / stage)"
  } else {
    Write-Host "Sidecar agent already running"
  }
} catch {
  Write-Host "WARNING: could not start sidecar: $($_.Exception.Message)"
}

# Sweep orphaned claims from prior agent deaths before the poll loop.
try {
  Write-Host "Sweeping stale UE-agent jobs..."
  $swept = Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/sweep-stale" -TimeoutSec 30
  if ($swept.failed_count -gt 0) {
    Write-Host "Stale jobs failed: $($swept.failed_count)"
  }
} catch {
  Write-Host "WARNING: sweep-stale failed: $($_.Exception.Message)"
}

while ($true) {
  try {
    $claimBody = @{ kinds = @("ue_capture", "host_open_editor") } | ConvertTo-Json
    $claimed = Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/claim" `
      -ContentType "application/json" -Body $claimBody
    if ($claimed.stale_failed -and @($claimed.stale_failed).Count -gt 0) {
      Write-Host "Claim cleared stale runners: $(@($claimed.stale_failed).Count)"
    }
    if ($null -eq $claimed.job) {
      try {
        if (Resume-OrphanedCaptureIfNeeded) { continue }
      } catch {
        Write-Host "WARNING: attach orphaned capture failed: $($_.Exception.Message)"
        $fail = @{ error = $_.Exception.Message } | ConvertTo-Json
        try {
          $listed = Invoke-RestMethod -Method Get -Uri "$VellumBase/api/jobs?status=running&limit=5" -TimeoutSec 20
          foreach ($j in @($listed.jobs)) {
            if ([string]$j.kind -eq "ue_capture") {
              Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$($j.job_id)/report" -ContentType "application/json" -Body $fail | Out-Null
              break
            }
          }
        } catch { }
      }
      # Do not leave a warm 4070 idle while on-disk packs need MRQ.
      try {
        $drain = Invoke-RestMethod -Method Post -Uri "$VellumBase/api/ops/drain?engine=unreal&limit=2" -TimeoutSec 60
        if ($drain.enqueued -and @($drain.enqueued).Count -gt 0) {
          Write-Host ("Auto-drain enqueued {0}: {1}" -f @($drain.enqueued).Count, (($drain.enqueued | ForEach-Object { $_.asset_id }) -join ","))
          continue
        }
      } catch {
        Write-Host "WARNING: ops/drain failed: $($_.Exception.Message)"
      }
      try { [void](Publish-VellumHostUtilization) } catch { }
      Start-Sleep -Seconds $PollSeconds
      continue
    }
    $job = $claimed.job
    try {
      Invoke-CaptureJob -Job $job
      Write-Host "Completed $($job.job_id) kind=$($job.kind)"
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
