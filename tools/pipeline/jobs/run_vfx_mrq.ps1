#Requires -Version 7.0
<#
.SYNOPSIS
  Execute a bake-vfx plan through Vellum's MRQ/Sequencer authoring path.

.DESCRIPTION
  This is intentionally separate from the parallel factory-all worker path:
  it authors LevelSequence/MRQ assets under /Game/Vellum and renders frames,
  so callers should run it as an exclusive targeted VFX bake.
#>
param(
  [Parameter(Mandatory = $true)][string]$Pack,
  [Parameter(Mandatory = $true)][string]$Project,
  [Parameter(Mandatory = $true)][string]$UeCmd,
  [string]$WorkDir = "F:\Games\AuroraVellum\Saved\VellumPipeline",
  [string]$PlanPath = "",
  [int]$MaxSystems = $(if ($env:VELLUM_MAX_VFX_SYSTEMS) { [int]$env:VELLUM_MAX_VFX_SYSTEMS } else { 0 }),
  [int]$TimeoutSec = 0
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$AuthorScript = Join-Path $RepoRoot "tools\unreal\vellum_capture_mrq_author.py"
if (-not (Test-Path -LiteralPath $AuthorScript)) {
  throw "missing_author_script:$AuthorScript"
}

function ConvertTo-UePath([string]$Path) {
  return (($Path -replace '\\', '/').TrimEnd('/'))
}

function ConvertTo-UeSoftPath([string]$PackageOrSoft) {
  $p = ConvertTo-UePath $PackageOrSoft
  if (-not $p) { return $p }
  $leaf = ($p -split "/")[-1]
  if ($leaf -match "\.") { return $p }
  return "$p.$leaf"
}

function Find-UeEditor {
  param([string]$CmdPath)
  if ($CmdPath -and $CmdPath -match "UnrealEditor-Cmd\.exe$") {
    $gui = $CmdPath -replace "UnrealEditor-Cmd\.exe$", "UnrealEditor.exe"
    if (Test-Path -LiteralPath $gui) { return $gui }
  }
  return $CmdPath
}

function Get-ImageFiles {
  param([string]$Root)
  if (-not (Test-Path -LiteralPath $Root)) { return @() }
  $found = New-Object System.Collections.ArrayList
  foreach ($ext in @("*.png", "*.jpg", "*.jpeg", "*.bmp")) {
    Get-ChildItem -LiteralPath $Root -Recurse -File -Filter $ext -ErrorAction SilentlyContinue |
      ForEach-Object { [void]$found.Add($_) }
  }
  return @($found.ToArray())
}

function Wait-MrqOutputFrames {
  param(
    [string]$SeqOutDir,
    [int]$ExpectFrames = 1,
    [int]$TimeoutSec = 180,
    [int]$StableSeconds = 6,
    [int]$EmptyAbortSec = 25,
    [switch]$AcceptPartialStable,
    [string]$Phase = "MRQ"
  )
  if ($ExpectFrames -lt 1) { $ExpectFrames = 1 }
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  $lastCount = -1
  $stableSince = $null
  while ((Get-Date) -lt $deadline) {
    $n = @(Get-ImageFiles -Root $SeqOutDir).Count
    if ($n -ne $lastCount) {
      $lastCount = $n
      $stableSince = Get-Date
      Write-Host "$Phase frames=$n want>=$ExpectFrames"
    } elseif ($null -ne $stableSince) {
      $stableFor = ((Get-Date) - $stableSince).TotalSeconds
      if ($n -ge $ExpectFrames -and $stableFor -ge $StableSeconds) {
        Write-Host "$Phase ready frames=$n"
        return $n
      }
      if ($AcceptPartialStable -and $n -gt 0 -and $stableFor -ge $StableSeconds) {
        Write-Host "$Phase stable-partial frames=$n"
        return $n
      }
      if ($EmptyAbortSec -gt 0 -and $n -eq 0 -and $stableFor -ge $EmptyAbortSec) {
        Write-Host "$Phase empty-abort frames=0"
        return 0
      }
    }
    Start-Sleep -Seconds 3
  }
  return [Math]::Max(0, $lastCount)
}

function Invoke-UeLogged {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$ArgumentList,
    [Parameter(Mandatory = $true)][string]$LogPath,
    [Parameter(Mandatory = $true)][string]$Phase,
    [int]$HeartbeatSeconds = 10,
    [int]$TimeoutSec = 0
  )
  if (Test-Path -LiteralPath $LogPath) {
    Remove-Item -LiteralPath $LogPath -Force -ErrorAction SilentlyContinue
  }
  $args = [System.Collections.Generic.List[string]]::new()
  foreach ($a in @($ArgumentList)) { [void]$args.Add([string]$a) }
  if (-not ($args | Where-Object { $_ -like "-AbsLog=*" })) {
    [void]$args.Add("-AbsLog=$LogPath")
  }
  Write-Host "$Phase starting: $Exe"
  $proc = Start-Process -FilePath $Exe -ArgumentList $args.ToArray() -PassThru -WindowStyle Minimized
  $uePid = [int]$proc.Id
  $proc = $null
  Write-Host "$Phase pid=$uePid"
  $started = Get-Date
  while ($true) {
    Start-Sleep -Seconds $HeartbeatSeconds
    $alive = $null -ne (Get-Process -Id $uePid -ErrorAction SilentlyContinue)
    if (-not $alive) { break }
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    if ($TimeoutSec -gt 0 -and $elapsed -ge $TimeoutSec) {
      Write-Warning "$Phase timeout after ${elapsed}s; killing pid=$uePid"
      Stop-Process -Id $uePid -Force -ErrorAction SilentlyContinue
      break
    }
    Write-Host "$Phase still running (${elapsed}s)"
  }
  Write-Host "$Phase process gone"
}

if (-not $PlanPath) {
  $PlanPath = Join-Path $WorkDir "$Pack\vfx\bake-plan.json"
}
if (-not (Test-Path -LiteralPath $PlanPath)) {
  throw "missing_bake_plan:$PlanPath"
}

$plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
$systems = @($plan.systems)
if ($MaxSystems -gt 0) {
  $systems = @($systems | Select-Object -First $MaxSystems)
}
if ($systems.Count -eq 0) {
  Write-Host "No Niagara systems in bake plan; MRQ nothing to do."
  exit 0
}

$mrqRoot = Join-Path $WorkDir "$Pack\vfx\mrq"
$runDir = Join-Path $WorkDir "$Pack\vfx\mrq-run"
New-Item -ItemType Directory -Force -Path $mrqRoot, $runDir | Out-Null
# A targeted bake is authoritative for this packing run. Remove stale frames
# from previously selected systems so the packer cannot republish old clips.
Get-ChildItem -LiteralPath $mrqRoot -Recurse -File -Filter "*.png" -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue
$runStamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")
$scratchPackage = "/Game/Vellum/PipelineScratch/$Pack/$runStamp"

$authorSystems = @()
foreach ($sys in $systems) {
  $name = [string]$sys.asset_name
  $outDir = [string]$sys.output_dir
  if (-not $outDir) {
    $safe = -join ($name.ToCharArray() | ForEach-Object { if ($_ -match "[A-Za-z0-9_-]") { $_ } else { "_" } })
    $outDir = Join-Path $mrqRoot $safe
  }
  New-Item -ItemType Directory -Force -Path $outDir | Out-Null
  Get-ChildItem -LiteralPath $outDir -Recurse -File -Filter "*.png" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
  $authorSystems += @{
    object_path = [string]$sys.object_path
    asset_name = $name
    output_dir = ConvertTo-UePath $outDir
  }
}

$frameCount = [int]($plan.frame_count ?? 60)
$frameRate = [int]($plan.frame_rate ?? 30)
$width = [int]($plan.width ?? 1920)
$height = [int]($plan.height ?? 1080)
$mapPath = [string]($plan.map_path ?? "/Game/Vellum/Maps/VellumLookdevStudio")

$authorJob = @{
  asset_id = $Pack
  map_path = $mapPath
  width = $width
  height = $height
  frame_count = $frameCount
  frame_rate = $frameRate
  sequence_package = "$scratchPackage/Sequences"
  config_package = "$scratchPackage/MRQ"
  queue_name = "VellumBatchQueue_$Pack"
  systems = $authorSystems
}
$jobPath = Join-Path $runDir "job.json"
($authorJob | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $jobPath -Encoding utf8
$env:VELLUM_JOB_JSON = ConvertTo-UePath $jobPath
$env:VELLUM_OUT_DIR = ConvertTo-UePath $runDir

$authorLog = Join-Path $runDir "ue-author.log"
$authorExec = "-ExecutePythonScript=$(ConvertTo-UePath $AuthorScript)"
Invoke-UeLogged -Exe $UeCmd -ArgumentList @(
  $Project, "-stdout", "-FullStdOutLogOutput", "-unattended", "-nop4", $authorExec
) -LogPath $authorLog -Phase "VFX MRQ author" -TimeoutSec $(if ($TimeoutSec -gt 0) { [Math]::Min($TimeoutSec, 900) } else { 900 })

$authorResultPath = Join-Path $runDir "author-result.json"
if (-not (Test-Path -LiteralPath $authorResultPath)) {
  throw "author_no_result:$authorResultPath"
}
$author = Get-Content -LiteralPath $authorResultPath -Raw | ConvertFrom-Json
if (-not [bool]$author.ok) {
  $err = (@($author.errors) | Select-Object -First 4) -join ";"
  throw "author_failed:$err"
}
$authored = @($author.jobs)
if ($authored.Count -eq 0 -and $author.system_name) { $authored = @($author) }
if ($authored.Count -eq 0) { throw "author_empty" }

$mapSoft = ConvertTo-UeSoftPath ([string]$author.map_path)
$queueSoft = ""
if ($author.queue_path) { $queueSoft = ConvertTo-UeSoftPath ([string]$author.queue_path) }
$UeEditor = Find-UeEditor -CmdPath $UeCmd
$errors = New-Object System.Collections.ArrayList
$renderStart = Get-Date

if ($queueSoft) {
  $mrqLog = Join-Path $runDir "ue-mrq-batch.log"
  $mrqArgs = @(
    $Project,
    $mapSoft,
    "-game",
    "-windowed",
    "-ResX=$width",
    "-ResY=$height",
    "-nosplash",
    "-nop4",
    "-log",
    "-Unattended",
    "-MoviePipelineConfig=$queueSoft"
  )
  $batchTimeout = if ($TimeoutSec -gt 0) { $TimeoutSec } else { 300 + (60 * [Math]::Max(1, $authored.Count)) }
  Invoke-UeLogged -Exe $UeEditor -ArgumentList $mrqArgs -LogPath $mrqLog -Phase "VFX MRQ batch" -HeartbeatSeconds 20 -TimeoutSec $batchTimeout
}

$rendered = @()
$slot = 0
foreach ($item in $authored) {
  $systemName = [string]$item.system_name
  $outDir = ([string]$item.output_dir) -replace '/', '\'
  $expect = [int]($item.frame_count ?? $frameCount)
  $n = if ($queueSoft) {
    Wait-MrqOutputFrames -SeqOutDir $outDir -ExpectFrames $expect -TimeoutSec 120 -AcceptPartialStable -Phase "VFX MRQ[$slot] $systemName"
  } else {
    0
  }
  if ($n -eq 0) {
    $seqSoft = ConvertTo-UeSoftPath ([string]($item.sequence_path ?? $item.sequence_asset))
    $cfgSoft = ConvertTo-UeSoftPath ([string]($item.config_path ?? $item.config_asset))
    $mrqLog = Join-Path $runDir "ue-mrq-$slot.log"
    Invoke-UeLogged -Exe $UeEditor -ArgumentList @(
      $Project,
      $mapSoft,
      "-game",
      "-windowed",
      "-ResX=$width",
      "-ResY=$height",
      "-nosplash",
      "-nop4",
      "-log",
      "-Unattended",
      "-LevelSequence=$seqSoft",
      "-MoviePipelineConfig=$cfgSoft"
    ) -LogPath $mrqLog -Phase "VFX MRQ[$slot] $systemName" -HeartbeatSeconds 20 -TimeoutSec $(if ($TimeoutSec -gt 0) { $TimeoutSec } else { 420 })
    $n = Wait-MrqOutputFrames -SeqOutDir $outDir -ExpectFrames $expect -TimeoutSec 180 -AcceptPartialStable -Phase "VFX MRQ[$slot] retry $systemName"
  }
  if ($n -eq 0) {
    [void]$errors.Add("mrq_no_frames:$systemName")
  }
  $rendered += @{
    system = $systemName
    object_path = [string]$item.system_object_path
    output_dir = ConvertTo-UePath $outDir
    frames = $n
  }
  $slot++
}

$manifest = @{
  schema_version = 1
  job = "run-vfx-mrq"
  pack = $Pack
  ok = ($errors.Count -eq 0)
  rendered = $rendered
  authored = $authored.Count
  queue_path = $queueSoft
  scratch_package = $scratchPackage
  errors = @($errors)
  render_started_at = $renderStart.ToUniversalTime().ToString("o")
  generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
}
($manifest | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath (Join-Path $runDir "mrq-run-manifest.json") -Encoding utf8
if ($errors.Count -gt 0) {
  throw "mrq_failed:$((@($errors) | Select-Object -First 4) -join ';')"
}
Write-Host "VFX MRQ rendered systems=$($rendered.Count)"
