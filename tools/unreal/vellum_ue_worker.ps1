#Requires -Version 5.1
<#
.SYNOPSIS
  Supervisor for the warm Vellum UE Lookdev Worker on Aurora.

.DESCRIPTION
  Ensures one UnrealEditor is running on Lookdev Studio with the in-UE HTTP
  worker listening on 127.0.0.1:8771. This is Option 1 - GPU printer, not
  Cmd-per-phase E2E.

.EXAMPLE
  pwsh -File tools/unreal/vellum_ue_worker.ps1 -Ensure
  pwsh -File tools/unreal/vellum_ue_worker.ps1 -Status
#>
param(
  [string]$HostName = "",
  [string]$VellumBase = "http://192.168.68.93:8770",
  [int]$Port = 0,
  [string]$MapPath = "/Game/Vellum/Maps/VellumLookdevStudio",
  [int]$ReadyTimeoutSec = 180,
  [switch]$Ensure,
  [switch]$Status,
  [switch]$StopHttp,
  [switch]$ForceStudio,
  # Set by Interactive scheduled task so Ensure launches UE even when UserInteractive/SESSIONNAME look wrong.
  [switch]$LaunchGui
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
. (Join-Path $PSScriptRoot "ue-hosts.ps1")
$UeHost = Get-UeHostProfile -RepoRoot $RepoRoot -HostName $HostName
if ($Port -le 0) {
  if ($UeHost.worker_port) { $Port = [int]$UeHost.worker_port } else { $Port = 8771 }
}
$WorkerUrl = "http://127.0.0.1:$Port"
$BootPySource = Join-Path $PSScriptRoot "vellum_ue_worker_boot.py"
$InitPySource = Join-Path $PSScriptRoot "init_unreal.py"
$StudioPySource = Join-Path $PSScriptRoot "vellum_lookdev_studio_author.py"
$AuthorPySource = Join-Path $PSScriptRoot "vellum_capture_mrq_author.py"
$InventoryPySource = Join-Path $PSScriptRoot "vellum_capture.py"

function ConvertTo-UePath([string]$Path) {
  if (-not $Path) { return $Path }
  return ($Path -replace '\\', '/')
}

function Get-WorkerHealth {
  try {
    return Invoke-RestMethod -Method Get -Uri "$WorkerUrl/health" -TimeoutSec 3
  } catch {
    return $null
  }
}

$script:StudioBuildRequired = 3

function Test-StudioBuildCurrent {
  param($Health)
  if (-not $Health -or -not $Health.ok) { return $false }
  $build = 0
  if ($null -ne $Health.studio_build) { $build = [int]$Health.studio_build }
  return ($build -ge $script:StudioBuildRequired)
}

function Request-StudioRebuild {
  Write-Host "Studio build stale/missing - requesting /v1/ensure_studio force..."
  $body = @{ force = $true } | ConvertTo-Json
  $kick = Invoke-RestMethod -Method Post -Uri "$WorkerUrl/v1/ensure_studio" `
    -ContentType "application/json" -Body $body -TimeoutSec 15
  if (-not $kick.ok -and $kick.error -ne "worker_busy") {
    throw "ensure_studio kick failed: $($kick | ConvertTo-Json -Compress)"
  }
  $deadline = (Get-Date).AddSeconds(180)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $health = Get-WorkerHealth
    if (Test-StudioBuildCurrent -Health $health) { return $health }
  }
  throw "ensure_studio did not reach required studio_build in time"
}

function Get-ProjectPaths {
  $uproject = Resolve-UprojectFromHost -HostProfile $UeHost
  $projectDir = Split-Path $uproject -Parent
  $outDir = Join-Path $projectDir "Saved\VellumCapture"
  $pythonDir = Join-Path $projectDir "Content\Python"
  New-Item -ItemType Directory -Force -Path $outDir | Out-Null
  New-Item -ItemType Directory -Force -Path $pythonDir | Out-Null
  return @{
    Uproject   = $uproject
    ProjectDir = $projectDir
    OutDir     = $outDir
    PythonDir  = $pythonDir
  }
}

function Stage-WorkerScripts {
  param($OutDir, $PythonDir)
  foreach ($pair in @(
      @{ Src = $BootPySource; Name = "vellum_ue_worker_boot.py"; DestDir = $OutDir },
      @{ Src = $StudioPySource; Name = "vellum_lookdev_studio_author.py"; DestDir = $OutDir },
      @{ Src = $AuthorPySource; Name = "vellum_capture_mrq_author.py"; DestDir = $OutDir },
      @{ Src = $InventoryPySource; Name = "vellum_capture.py"; DestDir = $OutDir },
      @{ Src = $InitPySource; Name = "init_unreal.py"; DestDir = $PythonDir }
    )) {
    if (-not (Test-Path $pair.Src)) { throw "Missing $($pair.Src)" }
    New-Item -ItemType Directory -Force -Path $pair.DestDir | Out-Null
    Copy-Item -Force -Path $pair.Src -Destination (Join-Path $pair.DestDir $pair.Name)
  }
  Write-Host "Staged Lookdev Worker boot + Content/Python/init_unreal.py"
}

function Find-UeEditorBinary {
  if ($UeHost.ue_editor -and (Test-Path $UeHost.ue_editor)) { return $UeHost.ue_editor }
  $cmd = Find-UeCmdFromHost -HostProfile $UeHost -Hint $env:VELLUM_UE_CMD
  $gui = $cmd -replace "UnrealEditor-Cmd\.exe$", "UnrealEditor.exe"
  if (Test-Path $gui) { return $gui }
  throw "UnrealEditor.exe not found from host profile"
}

function Test-UeEditorRunning {
  param([string]$ProjectDir)
  $procs = @(Get-Process -Name "UnrealEditor" -ErrorAction SilentlyContinue)
  foreach ($p in $procs) {
    try {
      $path = $p.Path
      if ($path -and $path -match "UnrealEditor") { return $true }
    } catch { }
  }
  return ($procs.Count -gt 0)
}

function Test-WorkerPumpAlive {
  param($Health)
  if (-not $Health -or -not $Health.ok) { return $false }
  # Sticky pump proof: slate ticks must advance after init_unreal owns the callback.
  $ticks = 0
  if ($null -ne $Health.tick_count) { $ticks = [int]$Health.tick_count }
  return ($ticks -ge 5)
}

function Start-LookdevWorker {
  $paths = Get-ProjectPaths
  Stage-WorkerScripts -OutDir $paths.OutDir -PythonDir $paths.PythonDir
  $health = Get-WorkerHealth
  if ($health -and $health.ok -and (Test-WorkerPumpAlive -Health $health)) {
    if (Test-StudioBuildCurrent -Health $health) {
      Write-Host "Worker already healthy version=$($health.version) studio_build=$($health.studio_build) ticks=$($health.tick_count) map=$($health.map)"
      return $health
    }
    try {
      $rebuild = Request-StudioRebuild
      Write-Host "Studio rebuild ok=$($rebuild.ok) build=$($rebuild.studio_build) ticks=$($rebuild.tick_count)"
      if (Test-StudioBuildCurrent -Health $rebuild) { return $rebuild }
    } catch {
      Write-Host "Studio rebuild via HTTP failed: $($_.Exception.Message) - will restart editor"
    }
  }

  # GPU editor needs an interactive desktop (jaked console/RDP).
  # SSH Start-Process hits DXGI_ERROR_NOT_CURRENTLY_AVAILABLE.
  # Interactive Ensure task passes -LaunchGui so it can Start-Process even when SESSIONNAME is blank.
  $canLaunchGui = [bool]$LaunchGui
  try {
    if ($env:SESSIONNAME -match '^(Console|RDP-Tcp)') { $canLaunchGui = $true }
    elseif ([Environment]::UserInteractive -and $env:SESSIONNAME -and $env:SESSIONNAME -ne 'Services') {
      $canLaunchGui = $true
    }
  } catch { }

  if (-not $canLaunchGui) {
    Write-Host "No interactive desktop here (SESSIONNAME='$($env:SESSIONNAME)' UserInteractive=$([Environment]::UserInteractive)) - starting scheduled task VellumLookdevWorkerEnsure..."
    try {
      Start-ScheduledTask -TaskName "VellumLookdevWorkerEnsure" -ErrorAction Stop
    } catch {
      Write-Host "Start-ScheduledTask failed: $($_.Exception.Message)"
    }
    $deadline = (Get-Date).AddSeconds([Math]::Max($ReadyTimeoutSec, 180))
    while ((Get-Date) -lt $deadline) {
      Start-Sleep -Seconds 3
      $health = Get-WorkerHealth
      if ($health -and $health.ok -and (Test-WorkerPumpAlive -Health $health)) {
        Write-Host "Worker ready version=$($health.version) ticks=$($health.tick_count) map=$($health.map)"
        return $health
      }
    }
    throw "Lookdev Worker not healthy at $WorkerUrl/health after kicking VellumLookdevWorkerEnsure. Confirm jaked is logged into Aurora's console."
  }

  if (Test-UeEditorRunning -ProjectDir $paths.ProjectDir) {
    Write-Host "Stopping existing UnrealEditor so init_unreal can load staged worker..."
    Get-Process -Name "UnrealEditor" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 4
  }

  $editor = Find-UeEditorBinary
  $projUe = ConvertTo-UePath $paths.Uproject
  $mapSoft = $MapPath
  if ($mapSoft -notmatch '\.') {
    $leaf = ($mapSoft.TrimEnd('/') -split '/')[-1]
    $mapSoft = "$mapSoft.$leaf"
  }

  $env:VELLUM_OUT_DIR = (ConvertTo-UePath $paths.OutDir)
  $env:VELLUM_WORKER_PORT = "$Port"
  $env:VELLUM_STUDIO_MAP = $MapPath

  Write-Host "Starting Lookdev Worker (Content/Python/init_unreal.py owns the pump):"
  Write-Host "  Editor: $editor"
  Write-Host "  Project: $projUe"
  Write-Host "  Map: $mapSoft"
  Write-Host "  Init: $(Join-Path $paths.PythonDir 'init_unreal.py')"
  Write-Host "  Health: $WorkerUrl/health"

  # Sticky hosting = project Python init. Do not rely on -ExecutePythonScript lifetime.
  $argList = @(
    $projUe,
    $mapSoft,
    "-nosplash",
    "-nop4",
    "-log"
  )
  Start-Process -FilePath $editor -ArgumentList $argList -WorkingDirectory $paths.ProjectDir | Out-Null

  $deadline = (Get-Date).AddSeconds($ReadyTimeoutSec)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $health = Get-WorkerHealth
    if ($health -and $health.ok -and (Test-WorkerPumpAlive -Health $health)) {
      Write-Host "Worker ready version=$($health.version) ticks=$($health.tick_count) map=$($health.map)"
      return $health
    }
    $tickNote = if ($health) { "ticks=$($health.tick_count)" } else { "down" }
    Write-Host "Waiting for worker pump ($tickNote)..."
  }
  throw "Worker did not become healthy within ${ReadyTimeoutSec}s ($WorkerUrl/health) — tick pump never advanced"
}

Write-Host "Vellum UE Lookdev Worker supervisor"
Write-Host "Host: $($UeHost.id) ($($UeHost.label)) port=$Port"

if ($Status -or (-not $Ensure -and -not $StopHttp)) {
  $h = Get-WorkerHealth
  if ($h) {
    $h | ConvertTo-Json -Depth 5
    if (-not $Ensure -and -not $StopHttp) { exit 0 }
  } else {
    Write-Host "Worker not healthy at $WorkerUrl/health"
    if (-not $Ensure -and -not $StopHttp) { exit 1 }
  }
}

if ($StopHttp) {
  try {
    Invoke-RestMethod -Method Post -Uri "$WorkerUrl/v1/shutdown" -ContentType "application/json" -Body "{}" | Out-Null
    Write-Host "Shutdown requested"
  } catch {
    Write-Host "Shutdown failed (already down?): $($_.Exception.Message)"
  }
}

if ($Ensure) {
  if ($ForceStudio) {
    $paths = Get-ProjectPaths
    $ready = Join-Path $paths.OutDir "studio-ready.json"
    if (Test-Path $ready) { Remove-Item -Force $ready }
    Write-Host "ForceStudio: removed $ready"
  }
  $h = Start-LookdevWorker
  $h | ConvertTo-Json -Depth 5
  if ($ForceStudio -and $h -and $h.ok) {
    try {
      $body = @{ force = $true } | ConvertTo-Json
      Invoke-RestMethod -Method Post -Uri "$WorkerUrl/v1/ensure_studio" `
        -ContentType "application/json" -Body $body -TimeoutSec 180 | Out-Null
      Write-Host "ForceStudio: /v1/ensure_studio requested"
    } catch {
      Write-Host "ForceStudio ensure_studio call: $($_.Exception.Message)"
    }
  }
}
