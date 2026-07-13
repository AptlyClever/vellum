#Requires -Version 5.1
<#
.SYNOPSIS
  Recover interrupted MRQ captures: pick heroes from on-disk sequences and ingest.

.DESCRIPTION
  Reads F:\Games\AuroraVellum\Saved\VellumCapture\mrq\<system>\ (via host profile),
  rejects pure-black sequences, copies heroes to stills\, POSTs ingest-render +
  ingest-sequence to slots + hail-overlay. No Unreal launch.

.EXAMPLE
  pwsh -File tools/unreal/recover_vellum_capture.ps1
#>
param(
  [string]$AssetId = "fireworks-vol-1-niagara",
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$HostName = "",
  [string]$Project = "",
  [int]$MinFrames = 30,
  [int]$MinRgb = 8,
  [string[]]$Systems = @(),  # empty = all dirs under mrq/ with enough PNGs
  [switch]$Force = $(
    if ($env:VELLUM_FORCE_CAPTURE -match '^(1|true|yes)$') { $true } else { $false }
  )
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "ue-hosts.ps1")
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$UeHost = Get-UeHostProfile -RepoRoot $RepoRoot -HostName $HostName
if (-not $Project) { $Project = Resolve-UprojectFromHost -HostProfile $UeHost }
if (-not (Test-Path $Project)) { throw "Project not found: $Project" }

$PickHeroesPy = Join-Path $PSScriptRoot "pick_heroes.py"
if (-not (Test-Path $PickHeroesPy)) { throw "pick_heroes.py missing" }

$ProjectDir = Split-Path $Project -Parent
$OutDir = Join-Path $ProjectDir "Saved\VellumCapture"
$MrqRoot = Join-Path $OutDir "mrq"
$StillsDir = Join-Path $OutDir "stills"
New-Item -ItemType Directory -Force -Path $StillsDir | Out-Null

function Safe-Name([string]$Name) {
  return -join ($Name.ToCharArray() | ForEach-Object { if ($_ -match "[A-Za-z0-9_-]") { $_ } else { "_" } })
}

function Get-ImageCount([string]$Root) {
  if (-not (Test-Path $Root)) { return 0 }
  return @(Get-ChildItem -Path $Root -Recurse -File -Filter "*.png" -ErrorAction SilentlyContinue).Count
}

function Get-LookdevOutputs {
  param([string]$VellumBase, [string]$AssetId)
  try {
    $r = Invoke-RestMethod -Method Get -Uri "$VellumBase/api/lookdev/outputs?asset_id=$AssetId" -TimeoutSec 45
    if ($r.outputs) { return @($r.outputs) }
  } catch {
    Write-Host "WARNING: lookdev outputs fetch failed: $($_.Exception.Message)"
  }
  return @()
}

function Test-VaultHasSystemLookdev {
  param(
    [object[]]$Outputs,
    [string]$SystemName,
    [string[]]$Lanes
  )
  foreach ($laneName in $Lanes) {
    $hits = @($Outputs | Where-Object {
        $_.kind -eq "niagara-render" -and
        [string]$_.lane -eq $laneName -and (
          ([string]$_.path -like "*$SystemName*") -or
          ([string]$_.note -like "*$SystemName*")
        )
      })
    if ($hits.Count -eq 0) { return $false }
  }
  return $true
}

$IngestLanes = @("slots", "hail-overlay")
$vaultOutputs = @()
if (-not $Force) {
  $vaultOutputs = Get-LookdevOutputs -VellumBase $VellumBase -AssetId $AssetId
  Write-Host "Recover skip check: vault outputs=$(@($vaultOutputs).Count) force=$Force"
}

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { throw "python/py not found on PATH" }

if (-not (Test-Path $MrqRoot)) {
  throw "No MRQ output root at $MrqRoot — nothing to recover"
}

$dirs = @()
if ($Systems.Count -gt 0) {
  foreach ($s in $Systems) {
    $d = Join-Path $MrqRoot (Safe-Name $s)
    if (Test-Path $d) { $dirs += Get-Item $d }
  }
} else {
  $dirs = @(Get-ChildItem -Path $MrqRoot -Directory -ErrorAction SilentlyContinue)
}

# Prefer freshest _Single shells; skip stale _Loop dirs when a Single sibling exists.
# Alphabetical listing hit old pure-black Loop first and looked like a total failure.
$singleNames = @{}
foreach ($d in $dirs) {
  if ($d.Name -match '_Single$') { $singleNames[$d.Name] = $true }
}
$filtered = New-Object System.Collections.ArrayList
foreach ($d in $dirs) {
  if ($d.Name -match '^(.*)_Loop$' ) {
    $singleSibling = $Matches[1] + "_Single"
    if ($singleNames.ContainsKey($singleSibling)) {
      Write-Host "IGNORE $($d.Name) (stale loop; sibling $singleSibling present)"
      continue
    }
  }
  [void]$filtered.Add($d)
}
$dirs = @($filtered | Sort-Object {
    $n = $_.Name
    $pri = if ($n -match '_Single$') { 0 } else { 1 }
    "{0}-{1:yyyyMMddHHmmss}-{2}" -f $pri, $_.LastWriteTimeUtc, $n
  })

$report = [ordered]@{
  schema_version = 1
  tool           = "recover_vellum_capture"
  asset_id       = $AssetId
  project_dir    = $ProjectDir
  mrq_root       = $MrqRoot
  systems        = (New-Object System.Collections.ArrayList)
  ingested       = (New-Object System.Collections.ArrayList)
  skipped        = (New-Object System.Collections.ArrayList)
  errors         = (New-Object System.Collections.ArrayList)
  ok             = $false
}

Write-Host "Recover MRQ capture under $MrqRoot"
Write-Host "Candidate systems (after loop filter): $($dirs.Count)"
foreach ($d in $dirs) {
  Write-Host "  - $($d.Name)  frames=$(Get-ImageCount $d.FullName)  mtime=$($d.LastWriteTime)"
}

foreach ($dir in $dirs) {
  $systemName = $dir.Name
  $frames = Get-ImageCount $dir.FullName
  $entry = [ordered]@{
    system = $systemName
    path   = $dir.FullName
    frames = $frames
  }
  if (-not $Force -and (Test-VaultHasSystemLookdev -Outputs $vaultOutputs -SystemName $systemName -Lanes $IngestLanes)) {
    $entry.skip = "vault_covered"
    [void]$report.skipped.Add($entry)
    Write-Host "SKIP $systemName vault already has lookdev on $($IngestLanes -join '+')"
    continue
  }
  if ($frames -lt $MinFrames) {
    $entry.skip = "too_few_frames:$frames"
    [void]$report.skipped.Add($entry)
    Write-Host "SKIP $systemName frames=$frames (need >= $MinFrames)"
    continue
  }

  $HeroJson = Join-Path $OutDir "heroes-recover-$systemName.json"
  # Quiet stdout — pick_heroes JSON dump looked like a hard failure mid-run.
  & $py.Source $PickHeroesPy $dir.FullName --min-rgb $MinRgb --json-out $HeroJson *> $null
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $HeroJson)) {
    $entry.skip = "hero_pick_failed"
    [void]$report.skipped.Add($entry)
    Write-Host "SKIP $systemName hero_pick_failed"
    continue
  }
  $heroDoc = Get-Content $HeroJson -Raw | ConvertFrom-Json
  $entry.peak_rgb = [int]$heroDoc.peak_rgb
  $entry.hero_ok = [bool]$heroDoc.ok
  if (-not [bool]$heroDoc.ok) {
    $entry.skip = [string]$heroDoc.error
    [void]$report.skipped.Add($entry)
    # Black / rejected sequences are expected for pre-fix MRQ folders — not a hard error.
    Write-Host "SKIP $systemName $($heroDoc.error) (not an ingest error)"
    continue
  }
  $safeHint = Safe-Name $systemName
  $heroPaths = @()
  foreach ($h in @($heroDoc.heroes)) {
    $src = [string]$h.path
    if (-not (Test-Path $src)) { continue }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $dest = Join-Path $StillsDir "$AssetId-$safeHint-$($h.role)-recover-$stamp.png"
    Copy-Item -Force -Path $src -Destination $dest
    $heroPaths += @{
      role     = [string]$h.role
      path     = $dest
      max_rgb  = [int]$h.max_rgb
    }
    Write-Host "Hero $($h.role) -> $dest (max_rgb=$($h.max_rgb))"
  }
  $entry.heroes = $heroPaths
  [void]$report.systems.Add($entry)

  foreach ($hp in $heroPaths) {
    foreach ($laneName in @("slots", "hail-overlay")) {
      $out = & curl.exe -sS -X POST "$VellumBase/api/lookdev/ingest-render" `
        -F "asset_id=$AssetId" `
        -F "lane=$laneName" `
        -F "note=recover MRQ $($hp.role) $systemName via mrq-sequencer" `
        -F "file=@$($hp.path)"
      if ($LASTEXITCODE -ne 0) {
        [void]$report.errors.Add("ingest_render_failed:$systemName`:$laneName")
        throw "ingest-render failed system=$systemName lane=$laneName"
      }
      [void]$report.ingested.Add(@{ kind = "render"; system = $systemName; lane = $laneName; role = $hp.role; response = $out })
      Write-Host "Ingested hero $($hp.role) -> $laneName"
    }
  }

  $zipPath = Join-Path $OutDir ("seq-recover-" + $safeHint + ".zip")
  if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
  Compress-Archive -Path (Join-Path $dir.FullName "*") -DestinationPath $zipPath -Force
  foreach ($laneName in @("slots", "hail-overlay")) {
    $out = & curl.exe -sS -X POST "$VellumBase/api/lookdev/ingest-sequence" `
      -F "asset_id=$AssetId" `
      -F "lane=$laneName" `
      -F "system_name=$systemName" `
      -F "note=recover MRQ sequence $systemName via mrq-sequencer" `
      -F "archive=@$zipPath"
    if ($LASTEXITCODE -ne 0) {
      [void]$report.errors.Add("ingest_sequence_failed:$systemName`:$laneName")
      throw "ingest-sequence failed system=$systemName lane=$laneName"
    }
    [void]$report.ingested.Add(@{ kind = "sequence"; system = $systemName; lane = $laneName; response = $out })
    Write-Host "Ingested sequence $systemName -> $laneName"
  }
}

$okSystems = @($report.systems).Count
$report.ok = ($okSystems -gt 0 -and $report.errors.Count -eq 0)
$notes = "recover(mrq-sequencer) systems_ok=$okSystems skipped=$(@($report.skipped).Count) ingested=$(@($report.ingested).Count)"
$scratchBody = @{
  asset_id             = $AssetId
  scratch_project_path = $ProjectDir
  engine_version       = $(if ($UeHost.engine_version) { $UeHost.engine_version } else { "5.8" })
  notes                = $notes
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$VellumBase/api/scratch/record" `
  -ContentType "application/json" -Body $scratchBody | Out-Null

$ReportPath = Join-Path $OutDir "recover-report.json"
($report | ConvertTo-Json -Depth 8) | Set-Content -Path $ReportPath -Encoding utf8
Write-Host "Wrote $ReportPath"
Write-Host "Recover done ok=$($report.ok) systems=$okSystems ingested=$(@($report.ingested).Count) skipped=$(@($report.skipped).Count)"
if (-not $report.ok) { exit 2 }
exit 0
