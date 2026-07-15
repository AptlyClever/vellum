#Requires -Version 7.0
<#
.SYNOPSIS
  Run a Conversion Factory job against AuroraVellum via UnrealEditor-Cmd.
#>
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("inventory-pack", "export-models", "bake-vfx", "export-media", "factory-all")]
  [string]$Job,
  [string]$Pack = "FireworksV1",
  [string]$ContentRoot = "",
  [string]$UeCmd = "",
  [string]$Project = "",
  [string]$VaultGameReady = "",
  [string]$WorkDir = "",
  [switch]$AllowGpu,
  [int]$TimeoutSec = 7200
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
. (Join-Path $RepoRoot "tools\unreal\ue-hosts.ps1")

$hostProf = Get-UeHostProfile -RepoRoot $RepoRoot -HostName "aurora"
if (-not $UeCmd) { $UeCmd = $hostProf.ue_cmd }
if (-not $Project) { $Project = $hostProf.project }
if (-not $ContentRoot) { $ContentRoot = "/Game/$Pack" }
if (-not $WorkDir) {
  $WorkDir = "F:\Games\AuroraVellum\Saved\VellumPipeline"
}
if (-not $VaultGameReady) {
  $VaultGameReady = Join-Path $WorkDir "game-ready-out"
  foreach ($cand in @(
    "\\wsl$\Ubuntu\mnt\data\vault\vellum\05-derived-renders\game-ready",
    "F:\Games\AuroraVellum\Saved\VellumPipeline\game-ready-out"
  )) {
    if (Test-Path (Split-Path $cand -Parent)) {
      # Prefer shared staging when not under a worker-isolated WorkDir
      if ($WorkDir -eq "F:\Games\AuroraVellum\Saved\VellumPipeline") {
        $VaultGameReady = $cand
        break
      }
    }
  }
}

New-Item -ItemType Directory -Force -Path $WorkDir, $VaultGameReady | Out-Null

$jobMap = @{
  "inventory-pack" = "inventory_pack.py"
  "export-models"  = "export_models.py"
  "bake-vfx"       = "bake_vfx.py"
  "export-media"   = "export_media.py"
  "factory-all"    = "factory_all.py"
}
$pyRunDir = Join-Path $WorkDir "scripts"
New-Item -ItemType Directory -Force -Path $pyRunDir | Out-Null
$jobsSrc = Join-Path $RepoRoot "tools\pipeline\jobs"
# factory-all imports sibling job modules; stage the whole set for that job.
if ($Job -eq "factory-all") {
  Copy-Item -Force (Join-Path $jobsSrc "*.py") $pyRunDir
} else {
  Copy-Item -Force (Join-Path $jobsSrc $jobMap[$Job]), (Join-Path $jobsSrc "_common.py") $pyRunDir
}
$pyExec = Join-Path $pyRunDir ($jobMap[$Job])

$env:VELLUM_PACK = $Pack
$env:VELLUM_CONTENT_ROOT = $ContentRoot
$env:VELLUM_PIPELINE_WORK = $WorkDir
$env:VELLUM_VAULT_GAME_READY = $VaultGameReady

$log = Join-Path $WorkDir "$Job-$Pack.log"
$argList = @(
  "`"$Project`"",
  "-unattended", "-nopause", "-nosplash",
  "-ExecutePythonScript=`"$pyExec`"",
  "-AbsLog=`"$log`""
)
# CPU-only export jobs prefer NullRHI; bake-vfx needs GPU unless forced off
if ($Job -ne "bake-vfx" -and -not $AllowGpu) {
  $argList = @("-NullRHI") + $argList
}

Write-Host "Runner: Conversion Factory job=$Job pack=$Pack"
Write-Host "UE: $UeCmd"
Write-Host "ContentRoot: $ContentRoot"
Write-Host "Work: $WorkDir"
Write-Host "Out: $VaultGameReady"

$startedAt = Get-Date
$p = Start-Process -FilePath $UeCmd -ArgumentList $argList -PassThru -WindowStyle Hidden
$ok = $p.WaitForExit($TimeoutSec * 1000)
if (-not $ok) {
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  throw "timeout_${TimeoutSec}s job=$Job"
}
Write-Host "UE exit=$($p.ExitCode) log=$log"
if ($p.ExitCode -ne 0) {
  # UE sometimes access-violates during process teardown after the job already
  # finished. Trust a fresh ok manifest over the exit code.
  $jobManifest = Join-Path $WorkDir "$Pack\$Job.manifest.json"
  $fresh = (Test-Path $jobManifest) -and ((Get-Item $jobManifest).LastWriteTime -ge $startedAt)
  $manifestOk = $false
  if ($fresh) {
    try { $manifestOk = [bool](Get-Content $jobManifest -Raw | ConvertFrom-Json).ok } catch { }
  }
  if ($manifestOk) {
    Write-Warning "UE exited $($p.ExitCode) (shutdown crash) but manifest is fresh and ok; treating job as succeeded."
  } else {
    throw "ue_failed exit=$($p.ExitCode) job=$Job pack=$Pack log=$log"
  }
}

if ($Job -eq "bake-vfx" -or $Job -eq "factory-all") {
  $packScript = Join-Path $PSScriptRoot "jobs\pack_vfx_media.ps1"
  if (Test-Path $packScript) {
    & $packScript -Pack $Pack -WorkDir $WorkDir -OutDir (Join-Path $VaultGameReady "vfx\$Pack")
  }
}

$manifestCandidates = @(
  (Join-Path $WorkDir "$Pack\$Job.manifest.json"),
  (Join-Path $WorkDir "$Pack\factory-all.manifest.json"),
  (Join-Path $WorkDir "$Pack\inventory-pack.manifest.json"),
  (Join-Path $WorkDir "$Pack\export-models.manifest.json"),
  (Join-Path $WorkDir "$Pack\export-media.manifest.json"),
  (Join-Path $WorkDir "$Pack\vfx\bake-vfx.manifest.json")
)
$found = $manifestCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $found) {
  Write-Warning "No manifest found yet (job may need plugins/content)."
  exit 1
}
Write-Host "Manifest: $found"
Get-Content $found -Raw
exit 0
