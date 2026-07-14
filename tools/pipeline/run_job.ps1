#Requires -Version 7.0
<#
.SYNOPSIS
  Run a Conversion Factory job against AuroraVellum via UnrealEditor-Cmd.
#>
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("export-models", "bake-vfx", "export-media")]
  [string]$Job,
  [string]$Pack = "FireworksV1",
  [string]$ContentRoot = "",
  [string]$UeCmd = "",
  [string]$Project = "",
  [string]$VaultGameReady = "",
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
if (-not $VaultGameReady) {
  $VaultGameReady = Join-Path $env:TEMP "vellum-game-ready"
  # Prefer vault mount if present (WSL/hub bind); else local staging
  foreach ($cand in @(
    "\\wsl$\Ubuntu\mnt\data\vault\vellum\05-derived-renders\game-ready",
    "F:\Games\AuroraVellum\Saved\VellumPipeline\game-ready-out"
  )) {
    if (Test-Path (Split-Path $cand -Parent)) { $VaultGameReady = $cand; break }
  }
}

$work = "F:\Games\AuroraVellum\Saved\VellumPipeline"
New-Item -ItemType Directory -Force -Path $work, $VaultGameReady | Out-Null

$jobMap = @{
  "export-models" = "export_models.py"
  "bake-vfx"      = "bake_vfx.py"
  "export-media"  = "export_media.py"
}
$pySrc = Join-Path $RepoRoot "tools\pipeline\jobs\$($jobMap[$Job])"
$pyCommon = Join-Path $RepoRoot "tools\pipeline\jobs\_common.py"
$pyRunDir = Join-Path $work "scripts"
New-Item -ItemType Directory -Force -Path $pyRunDir | Out-Null
Copy-Item -Force $pySrc, $pyCommon $pyRunDir
$pyExec = Join-Path $pyRunDir ($jobMap[$Job])

$env:VELLUM_PACK = $Pack
$env:VELLUM_CONTENT_ROOT = $ContentRoot
$env:VELLUM_PIPELINE_WORK = $work
$env:VELLUM_VAULT_GAME_READY = $VaultGameReady

$log = Join-Path $work "$Job-$Pack.log"
$args = @(
  "`"$Project`"",
  "-unattended", "-nopause", "-nosplash",
  "-ExecutePythonScript=`"$pyExec`"",
  "-AbsLog=`"$log`""
)
# CPU-only export jobs prefer NullRHI; bake-vfx needs GPU unless forced off
if ($Job -ne "bake-vfx" -and -not $AllowGpu) {
  $args = @("-NullRHI") + $args
}

Write-Host "Runner: Conversion Factory job=$Job pack=$Pack"
Write-Host "UE: $UeCmd"
Write-Host "ContentRoot: $ContentRoot"
Write-Host "Out: $VaultGameReady"

$p = Start-Process -FilePath $UeCmd -ArgumentList $args -PassThru -WindowStyle Hidden
$ok = $p.WaitForExit($TimeoutSec * 1000)
if (-not $ok) {
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  throw "timeout_${TimeoutSec}s job=$Job"
}
Write-Host "UE exit=$($p.ExitCode) log=$log"

if ($Job -eq "bake-vfx") {
  $packScript = Join-Path $PSScriptRoot "jobs\pack_vfx_media.ps1"
  if (Test-Path $packScript) {
    & $packScript -Pack $Pack -WorkDir $work -OutDir (Join-Path $VaultGameReady "vfx\$Pack")
  }
}

$manifestCandidates = @(
  (Join-Path $work "$Pack\$Job.manifest.json"),
  (Join-Path $work "$Pack\export-models.manifest.json"),
  (Join-Path $work "$Pack\export-media.manifest.json"),
  (Join-Path $work "$Pack\vfx\bake-vfx.manifest.json")
)
$found = $manifestCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $found) {
  Write-Warning "No manifest found yet (job may need plugins/content)."
  exit 1
}
Write-Host "Manifest: $found"
Get-Content $found -Raw
exit 0
