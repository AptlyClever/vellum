#Requires -Version 7.0
<#
.SYNOPSIS
  Inventory / quarantine AuroraVellum Content. Packs stay at Content root.

.DESCRIPTION
  NEVER moves pack folders. Unreal .uasset files store absolute package paths;
  moving them on the filesystem (outside the editor) breaks all references,
  including references inside the same pack. Asset moves happen only inside
  the Unreal editor. See docs/library-project.md.
#>
param(
  [string]$ProjectContent = "F:\Games\AuroraVellum\Content",
  [switch]$InventoryOnly,
  [switch]$QuarantineCorrupt,
  [string]$ReportOut = ""
)

$ErrorActionPreference = "Stop"
if (-not $ReportOut) {
  $ReportOut = Join-Path $PSScriptRoot "library_health_report.json"
}

$KeepAtRoot = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($name in @(
  "External", "_Quarantine", "Vellum", "Python", "Developers", "Collections",
  "Fab", "__ExternalActors__", "__ExternalObjects__"
)) {
  [void]$KeepAtRoot.Add($name)
}

function Test-CorruptUasset {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $false }
  $info = Get-Item -LiteralPath $Path
  if ($info.Length -lt 64) { return $true }
  $fs = [IO.File]::OpenRead($Path)
  try {
    $buf = New-Object byte[] 16
    [void]$fs.Read($buf, 0, 16)
  } finally {
    $fs.Dispose()
  }
  $sum = 0
  foreach ($b in $buf) { $sum += $b }
  return ($sum -eq 0)
}

if (-not (Test-Path -LiteralPath $ProjectContent)) {
  throw "Content root missing: $ProjectContent"
}

$dirs = @(Get-ChildItem -LiteralPath $ProjectContent -Directory | Sort-Object Name)
$packs = @()
foreach ($d in $dirs) {
  if (-not $KeepAtRoot.Contains($d.Name)) {
    $packs += $d
  }
}

$externalRoot = Join-Path $ProjectContent "External"
# Quarantine lives OUTSIDE Content so the asset registry stops scanning the files.
$quarantineRoot = Join-Path (Split-Path $ProjectContent -Parent) "Quarantine"
$packNames = @()
foreach ($p in $packs) { $packNames += $p.Name }

$knownBad = @(
  "Dungeon_Ruins\Assets\decor_07.uasset",
  "Dungeon_Ruins\Assets\Pillar_Base_02.uasset",
  "Dungeon_Ruins\Assets\Pillar_Base_03.uasset"
)

$corrupt = New-Object System.Collections.Generic.List[hashtable]
foreach ($rel in $knownBad) {
  $p = Join-Path $ProjectContent $rel
  if ((Test-Path -LiteralPath $p) -and (Test-CorruptUasset -Path $p)) {
    $corrupt.Add(@{ path = $p; reason = "known_bad_header"; size = (Get-Item -LiteralPath $p).Length })
  }
}

foreach ($pack in $packs) {
  $assets = Get-ChildItem -LiteralPath $pack.FullName -Recurse -Filter *.uasset -ErrorAction SilentlyContinue
  foreach ($a in $assets) {
    if ($a.Length -lt 64 -or (Test-CorruptUasset -Path $a.FullName)) {
      $corrupt.Add(@{ path = $a.FullName; reason = "zero_or_bad_header"; size = $a.Length })
      if ($corrupt.Count -gt 200) { break }
    }
  }
  if ($corrupt.Count -gt 200) { break }
}

$seen = @{}
$unloadableRows = @()
foreach ($c in $corrupt) {
  if ($seen.ContainsKey($c.path)) { continue }
  $seen[$c.path] = $true
  $unloadableRows += @{ path = $c.path; reason = $c.reason; size = $c.size }
}

$actions = New-Object System.Collections.Generic.List[string]
Write-Host "Packs at Content root: $($packs.Count)"
Write-Host "Unloadable/suspect packages: $($unloadableRows.Count)"

if ($QuarantineCorrupt) {
  New-Item -ItemType Directory -Force -Path $quarantineRoot | Out-Null
  foreach ($row in $unloadableRows) {
    $c = $row.path
    if (-not (Test-Path -LiteralPath $c)) { continue }
    $rel = $c.Substring($ProjectContent.Length).TrimStart('\', '/')
    $dest = Join-Path $quarantineRoot $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
    Move-Item -LiteralPath $c -Destination $dest -Force
    $actions.Add("quarantine:$rel")
    Write-Host "Quarantined $rel"
  }
}

$reportObj = @{
  schema_version = 1
  generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
  content_root = $ProjectContent
  pack_dirs_at_root = $packNames
  pack_count_at_root = $packs.Count
  external_exists = (Test-Path -LiteralPath $externalRoot)
  unloadable_packages = $unloadableRows
  unloadable_count = $unloadableRows.Count
  actions = @($actions)
}
$reportObj | ConvertTo-Json -Depth 8 | Set-Content -Path $ReportOut -Encoding utf8
Write-Host "Wrote $ReportOut"
if (-not ($InventoryOnly -or $QuarantineCorrupt)) {
  Write-Host "Tip: pass -InventoryOnly and/or -QuarantineCorrupt"
}
