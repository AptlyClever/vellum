#Requires -Version 5.1
<#
.SYNOPSIS
  Supervisor for the warm Vellum UE Lookdev Worker on Aurora.

.DESCRIPTION
  Ensures one UnrealEditor is running on Lookdev Studio with the in-UE HTTP
  worker listening on 127.0.0.1:8771. This is Option 1 — GPU printer, not
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
  [switch]$StopHttp
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

function Get-ProjectPaths {
  $uproject = Resolve-UprojectFromHost -HostProfile $UeHost
  $projectDir = Split-Path $uproject -Parent
  $outDir = Join-Path $projectDir "Saved\VellumCapture"
  New-Item -ItemType Directory -Force -Path $outDir | Out-Null
  return @{
    Uproject   = $uproject
    ProjectDir = $projectDir
    OutDir     = $outDir
  }
}

function Stage-WorkerScripts {
  param($OutDir)
  foreach ($pair in @(
      @{ Src = $BootPySource; Name = "vellum_ue_worker_boot.py" },
      @{ Src = $StudioPySource; Name = "vellum_lookdev_studio_author.py" },
      @{ Src = $AuthorPySource; Name = "vellum_capture_mrq_author.py" },
      @{ Src = $InventoryPySource; Name = "vellum_capture.py" }
    )) {
    if (-not (Test-Path $pair.Src)) { throw "Missing $($pair.Src)" }
    Copy-Item -Force -Path $pair.Src -Destination (Join-Path $OutDir $pair.Name)
  }
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

function Start-LookdevWorker {
  $paths = Get-ProjectPaths
  Stage-WorkerScripts -OutDir $paths.OutDir
  $health = Get-WorkerHealth
  if ($health -and $health.ok) {
    Write-Host "Worker already healthy version=$($health.version) map=$($health.map) busy=$($health.busy)"
    return $health
  }

  # Session 0 / Windows Service must not launch UnrealEditor (GPU GUI).
  # Logon task VellumLookdevWorkerEnsure owns warming the editor.
  $inServiceSession = $false
  try {
    if ($env:SESSIONNAME -eq "Services") { $inServiceSession = $true }
    if (-not [Environment]::UserInteractive) { $inServiceSession = $true }
  } catch { }

  if ($inServiceSession) {
    Write-Host "Non-interactive session: waiting for Lookdev Worker health (logon task should start UE)…"
    $deadline = (Get-Date).AddSeconds([Math]::Min($ReadyTimeoutSec, 120))
    while ((Get-Date) -lt $deadline) {
      Start-Sleep -Seconds 3
      $health = Get-WorkerHealth
      if ($health -and $health.ok) {
        Write-Host "Worker ready version=$($health.version) map=$($health.map)"
        return $health
      }
    }
    throw "Lookdev Worker not healthy at $WorkerUrl/health. Log into Aurora (or run host-install logon task) so Unreal can warm — services cannot start the GPU editor."
  }

  $editor = Find-UeEditorBinary
  $bootPy = Join-Path $paths.OutDir "vellum_ue_worker_boot.py"
  $bootUe = ConvertTo-UePath $bootPy
  $projUe = ConvertTo-UePath $paths.Uproject
  $mapSoft = $MapPath
  if ($mapSoft -notmatch '\.') {
    $leaf = ($mapSoft.TrimEnd('/') -split '/')[-1]
    $mapSoft = "$mapSoft.$leaf"
  }

  $env:VELLUM_OUT_DIR = (ConvertTo-UePath $paths.OutDir)
  $env:VELLUM_WORKER_PORT = "$Port"
  $env:VELLUM_STUDIO_MAP = $MapPath

  Write-Host "Starting Lookdev Worker:"
  Write-Host "  Editor: $editor"
  Write-Host "  Project: $projUe"
  Write-Host "  Map: $mapSoft"
  Write-Host "  Boot: $bootUe"
  Write-Host "  Health: $WorkerUrl/health"

  $argList = @(
    $projUe,
    $mapSoft,
    "-nosplash",
    "-nop4",
    "-log",
    "-ExecutePythonScript=$bootUe"
  )
  Start-Process -FilePath $editor -ArgumentList $argList -WorkingDirectory $paths.ProjectDir | Out-Null

  $deadline = (Get-Date).AddSeconds($ReadyTimeoutSec)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $health = Get-WorkerHealth
    if ($health -and $health.ok) {
      Write-Host "Worker ready version=$($health.version) map=$($health.map)"
      return $health
    }
    Write-Host "Waiting for worker health…"
  }
  throw "Worker did not become healthy within ${ReadyTimeoutSec}s ($WorkerUrl/health)"
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
  $h = Start-LookdevWorker
  $h | ConvertTo-Json -Depth 5
}
