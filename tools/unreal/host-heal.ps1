#Requires -Version 5.1
<#
.SYNOPSIS
  Self-heal the Aurora Vellum UE host so Capture does not depend on human ritual.

.DESCRIPTION
  1) git pull --ff-only (repo from ue-hosts.json)
  2) Restage Lookdev Worker scripts
  3) Ensure warm worker + studio_build current
  4) Optionally bounce the agent Windows service if code changed

  Called by the agent on startup / before Capture, and by the logon watchdog.
#>
param(
  [string]$HostName = "aurora",
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$RepoRoot = "",
  [switch]$RestartAgentService,
  [switch]$SkipGitPull
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $RepoRoot) {
  $RepoRoot = (Resolve-Path (Join-Path $Here "..\..")).Path
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
. (Join-Path $Here "ue-hosts.ps1")
$UeHost = Get-UeHostProfile -RepoRoot $RepoRoot -HostName $HostName
$WorkerPs1 = Join-Path $Here "vellum_ue_worker.ps1"
$Port = if ($UeHost.worker_port) { [int]$UeHost.worker_port } else { 8771 }

Write-Host "=== Vellum host-heal ==="
Write-Host "RepoRoot=$RepoRoot Host=$($UeHost.id) Port=$Port"

$beforeSha = ""
$afterSha = ""
try {
  Push-Location $RepoRoot
  $beforeSha = (git rev-parse HEAD 2>$null)
  if (-not $SkipGitPull) {
    Write-Host "git fetch/pull --ff-only…"
    git fetch --quiet origin 2>$null
    git pull --ff-only --quiet origin HEAD 2>$null
    if ($LASTEXITCODE -ne 0) {
      Write-Host "WARNING: git pull --ff-only failed (local changes?). Continuing with current tree."
    }
  }
  $afterSha = (git rev-parse HEAD 2>$null)
} catch {
  Write-Host "WARNING: git heal skipped: $($_.Exception.Message)"
} finally {
  Pop-Location
}
Write-Host "git HEAD before=$beforeSha after=$afterSha"

if (-not (Test-Path $WorkerPs1)) { throw "Missing $WorkerPs1" }
Write-Host "Ensure Lookdev Worker (auto rebuilds stale studio)…"
& $WorkerPs1 -Ensure -HostName $UeHost.id -Port $Port
$ensureCode = $LASTEXITCODE

$health = $null
try {
  $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
  Write-Host ("Worker health ok={0} version={1} studio_build={2}/{3}" -f `
    $health.ok, $health.version, $health.studio_build, $health.studio_build_required)
} catch {
  Write-Host "WARNING: worker health not reachable yet: $($_.Exception.Message)"
}

# Old worker builds blocked the editor (serve_forever on main). Hard-restart Unreal
# when version is stale so Capture does not sit forever on a frozen session.
$needWorkerRestart = $false
if (-not $health -or -not $health.ok) { $needWorkerRestart = $true }
elseif ("$($health.version)" -notmatch "lookdev-worker-2") { $needWorkerRestart = $true }
if ($needWorkerRestart) {
  Write-Host "Restarting UnrealEditor to load lookdev-worker-2…"
  Get-Process -Name "UnrealEditor","UnrealEditor-Cmd" -ErrorAction SilentlyContinue | ForEach-Object {
    try { Stop-Process -Id $_.Id -Force -ErrorAction Stop } catch { }
  }
  Start-Sleep -Seconds 3
  & $WorkerPs1 -Ensure -HostName $UeHost.id -Port $Port
  $ensureCode = $LASTEXITCODE
  try {
    $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
  } catch { $health = $null }
}

# Publish heal status into host_specs.lookdev_worker (merge — do not wipe hardware).
try {
  $healBlob = @{
    healed_at             = (Get-Date).ToUniversalTime().ToString("o")
    git_sha               = "$afterSha"
    worker_ok             = [bool]($health -and $health.ok)
    worker_version        = if ($health) { [string]$health.version } else { "" }
    studio_build          = if ($health) { [int]$health.studio_build } else { 0 }
    studio_build_required = if ($health) { [int]$health.studio_build_required } else { 3 }
    ensure_exit           = [int]$ensureCode
  }
  $statusDir = Join-Path $RepoRoot "tools\unreal\host-install\runtime"
  New-Item -ItemType Directory -Force -Path $statusDir | Out-Null
  Set-Content -Path (Join-Path $statusDir "last-heal.json") -Value ($healBlob | ConvertTo-Json -Depth 5) -Encoding UTF8

  $merged = @{}
  try {
    $hostsPayload = Invoke-RestMethod -Method Get -Uri "$VellumBase/api/ue/hosts" -TimeoutSec 10
    foreach ($h in @($hostsPayload.hosts)) {
      if ([string]$h.id -eq $UeHost.id -and $h.host_specs) {
        $merged = @{}
        $h.host_specs.PSObject.Properties | ForEach-Object { $merged[$_.Name] = $_.Value }
        break
      }
    }
  } catch { }
  $merged["lookdev_worker"] = $healBlob
  $merged["collected_by"] = if ($merged["collected_by"]) { $merged["collected_by"] } else { "host-heal.ps1" }
  $body = @{ host_id = $UeHost.id; specs = $merged } | ConvertTo-Json -Depth 8
  Invoke-RestMethod -Method Post -Uri "$VellumBase/api/ue/hosts/specs" `
    -ContentType "application/json" -Body $body -TimeoutSec 15 | Out-Null
} catch {
  Write-Host "WARNING: could not publish heal status: $($_.Exception.Message)"
}

$codeChanged = ($beforeSha -and $afterSha -and ($beforeSha -ne $afterSha))
if ($RestartAgentService -or $codeChanged) {
  $svc = Get-Service -Name "VellumUeAgent" -ErrorAction SilentlyContinue
  if ($svc) {
    Write-Host "Restarting Windows Service VellumUeAgent (code_changed=$codeChanged)…"
    try {
      Restart-Service -Name "VellumUeAgent" -Force -ErrorAction Stop
    } catch {
      # WinSW path
      $exe = Join-Path $RepoRoot "tools\unreal\host-install\runtime\VellumUeAgent.exe"
      if (Test-Path $exe) {
        Push-Location (Split-Path $exe -Parent)
        try { & .\VellumUeAgent.exe restart | Out-Host } catch { Write-Host $_ }
        Pop-Location
      } else {
        Write-Host "WARNING: could not restart agent service: $($_.Exception.Message)"
      }
    }
  }
}

if ($ensureCode -ne 0) {
  throw "host-heal: Lookdev Worker Ensure failed exit=$ensureCode"
}
Write-Host "=== host-heal OK ==="
exit 0
