<#
.SYNOPSIS
  Aurora workhorse — reconcile F:\Games\AuroraVellum\Content + Fab VaultCache
  against what Vellum claims is on-disk vs missing.

.DESCRIPTION
  Run THIS on Aurora (Windows). Do not invent pack presence from Linux SSH
  one-liners or scp theatre.

  Examples:
    pwsh -File tools/unreal/reconcile-aurora-content.ps1
    pwsh -File tools/unreal/reconcile-aurora-content.ps1 -VellumBase http://192.168.68.93:8770

  Exit codes:
    0 — ran; see report
    1 — fatal (paths missing / API down)
#>
[CmdletBinding()]
param(
  [string]$ProjectContent = "F:\Games\AuroraVellum\Content",
  [string]$FabLibrary = "C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\FabLibrary",
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$OutJson = ""
)

$ErrorActionPreference = "Stop"

function Get-TopDirs([string]$root) {
  if (-not (Test-Path -LiteralPath $root)) { return @() }
  Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { $_.Name } |
    Sort-Object
}

function Get-DeepDirNames([string]$root, [int]$depth = 3) {
  if (-not (Test-Path -LiteralPath $root)) { return @() }
  Get-ChildItem -LiteralPath $root -Directory -Recurse -Depth $depth -ErrorAction SilentlyContinue |
    ForEach-Object { $_.Name } |
    Sort-Object -Unique
}

Write-Host "=== Aurora content reconcile (workhorse) ==="
Write-Host "Content: $ProjectContent"
Write-Host "FabLibrary: $FabLibrary"
Write-Host "Vellum: $VellumBase"

if (-not (Test-Path -LiteralPath $ProjectContent)) {
  Write-Error "Project Content missing: $ProjectContent"
  exit 1
}

$contentTop = @(Get-TopDirs $ProjectContent)
$fabTop = @(Get-TopDirs $FabLibrary)
$contentDeep = @(Get-DeepDirNames $ProjectContent 4)

Write-Host "`nContent top-level ($($contentTop.Count)):"
$contentTop | ForEach-Object { Write-Host "  $_" }

Write-Host "`nFabLibrary entries ($($fabTop.Count)):"
$fabTop | ForEach-Object { Write-Host "  $_" }

$needDownload = @()
$onDisk = @()
$apiOk = $false
try {
  $av = Invoke-RestMethod -Uri "$VellumBase/api/import/availability?engine=unreal" -TimeoutSec 60
  $assets = Invoke-RestMethod -Uri "$VellumBase/api/assets?engine=unreal&limit=200" -TimeoutSec 60
  $by = $av.by_asset_id
  $apiOk = $true
  foreach ($a in $assets.assets) {
    $st = $by.($a.id)
    if (-not $st) { continue }
    $row = [pscustomobject]@{
      asset_id     = $a.id
      display_name = $a.display_name
      state        = $st.state
      detail       = $st.detail
      host_path    = $a.host_content_path
      content_root = $a.content_root
    }
    if ($st.state -eq "need_download") { $needDownload += $row }
    elseif ($st.state -in @("ready", "on_disk")) { $onDisk += $row }
  }
} catch {
  Write-Warning "Vellum API unreachable: $($_.Exception.Message)"
}

Write-Host "`nVellum on-disk/ready count: $($onDisk.Count)"
Write-Host "Vellum need_download (not on Aurora per API): $($needDownload.Count)"

# Known display/folder patterns per missing Humble Epic id (strict).
$exactById = @{
  "mega-marble-material-4k" = @("MegaMarble", "Mega_Marble", "MarbleMaterial")
  "magic-projectiles-vol-3-niagara" = @("MagicProjectiles", "Magic_Projectiles")
  "stylized-vfx-water" = @("StylizedVFX", "Stylized_VFX_Water", "StylizedWater")
  "cappadocia-anatolian-cave-hotel-environment" = @("Cappadocia")
  "motel-reception-interior-environment" = @("MotelReception", "Motel_Reception")
  "arabic-fortress" = @("ArabicFortress", "Arabic_Fortress")
  "ice-fortress" = @("IceFortress", "Ice_Fortress")
  "the-lords-mansion" = @("LordsMansion", "Lords_Mansion", "LordMansion")
  "arabic-dock" = @("ArabicDock", "Arabic_Dock")
  "vertical-warehouse" = @("VerticalWarehouse", "Vertical_Warehouse")
  "the-count-s-church" = @("CountsChurch", "Count_s_Church", "Counts_Church")
  "abandoned-cabin" = @("AbandonedCabin", "Abandoned_Cabin")
  "oil-rig-liope" = @("OilRig", "Oil_Rig", "Liope")
  "middle-eastern-town" = @("MiddleEastern", "Middle_Eastern")
  "master-mega-dirty-wall-pack-material-4k" = @("DirtyWall", "Dirty_Wall", "MegaDirty")
  "glass-bundle-material" = @("GlassBundle", "Glass_Bundle")
  "loot-drops-vol-2-niagara" = @("LootDrops", "Loot_Drops")
  "magic-abilities-vol-3-niagara" = @("MagicAbilities", "Magic_Abilities")
  "niagara-mega-pack-vol-3" = @("NiagaraMega", "Niagara_Mega_Pack")
}

$hits = @()
$misses = @()
foreach ($row in $needDownload) {
  $name = [string]$row.display_name
  $aid = [string]$row.asset_id
  $patterns = @($exactById[$aid])
  if (-not $patterns -or $patterns.Count -eq 0) {
    $misses += $row
    continue
  }
  $found = $false
  $where = @()
  foreach ($pat in $patterns) {
    foreach ($d in $contentDeep) {
      if ($d -like "*$pat*") { $found = $true; $where += "Content:$d" }
    }
    foreach ($d in $fabTop) {
      if ($d -like "*$pat*") { $found = $true; $where += "FabLibrary:$d" }
    }
  }
  if ($found) {
    $hits += [pscustomobject]@{ asset_id = $aid; display_name = $name; where = ($where | Select-Object -Unique) }
  } else {
    $misses += $row
  }
}

Write-Host "`n=== need_download but ALSO found on disk/Fab (mapping bug if any) ==="
if ($hits.Count -eq 0) { Write-Host "(none — no false negatives from name search)" }
else { $hits | Format-List }

Write-Host "`n=== need_download with NO Content/FabLibrary name hit (really missing) ==="
foreach ($m in $misses) {
  Write-Host ("  {0}  ({1})" -f $m.display_name, $m.asset_id)
}

$report = [ordered]@{
  schema_version     = 1
  generated_at       = (Get-Date).ToUniversalTime().ToString("o")
  project_content    = $ProjectContent
  fab_library        = $FabLibrary
  content_top        = $contentTop
  fab_library_entries= $fabTop
  vellum_api_ok      = $apiOk
  vellum_on_disk     = $onDisk.Count
  vellum_need_download = $needDownload.Count
  false_negative_hits  = $hits
  really_missing       = @($misses | ForEach-Object { $_.asset_id })
  really_missing_names = @($misses | ForEach-Object { $_.display_name })
}

if (-not $OutJson) {
  $OutJson = Join-Path $PSScriptRoot "..\..\data\aurora-content-reconcile.json"
  if (-not (Test-Path (Split-Path $OutJson))) {
    $OutJson = Join-Path $env:TEMP "vellum-aurora-content-reconcile.json"
  }
}
$dir = Split-Path -Parent $OutJson
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
($report | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $OutJson -Encoding UTF8
Write-Host "`nWrote $OutJson"
Write-Host "really_missing=$($misses.Count)  mapping_hits=$($hits.Count)"
exit 0
