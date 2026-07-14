#Requires -Version 5.1
<#
.SYNOPSIS
  Install a Fab/Epic owned pack from local VaultCache into AuroraVellum Content.

.DESCRIPTION
  Epic Launcher already downloaded packs under
  C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\<pack>\data\Content\.
  This copies that Content subtree into the F: AuroraVellum project — no Fab UI.

.EXAMPLE
  pwsh -File install_fab_pack_from_vault_cache.ps1 `
    -ProjectContent "F:\Games\AuroraVellum\Content" `
    -ContentRelPaths @("Hangar-X") `
    -OutJson "F:\Games\AuroraVellum\Saved\VellumFabInstall\hangar-x.json"
#>
param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectContent,

  [Parameter(Mandatory = $true)]
  [string[]]$ContentRelPaths,

  [string]$VaultCacheRoot = "C:\ProgramData\Epic\EpicGamesLauncher\VaultCache",

  [string]$OutJson = "",

  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Normalize-Rel([string]$p) {
  return (($p -replace "/", "\").Trim("\")).Trim()
}

if (-not (Test-Path -LiteralPath $ProjectContent)) {
  throw "project_content_missing:$ProjectContent"
}
if (-not (Test-Path -LiteralPath $VaultCacheRoot)) {
  throw "vault_cache_root_missing:$VaultCacheRoot"
}

$cacheDirs = @(Get-ChildItem -LiteralPath $VaultCacheRoot -Directory -ErrorAction Stop |
  Where-Object { $_.Name -ne "FabLibrary" })

$foundSrc = $null
$foundRel = $null
$foundCache = $null

foreach ($relRaw in @($ContentRelPaths)) {
  $rel = Normalize-Rel $relRaw
  if (-not $rel) { continue }
  foreach ($cache in $cacheDirs) {
    $src = Join-Path $cache.FullName (Join-Path "data\Content" $rel)
    if (Test-Path -LiteralPath $src) {
      $foundSrc = $src
      $foundRel = $rel
      $foundCache = $cache.FullName
      break
    }
  }
  if ($foundSrc) { break }
}

if (-not $foundSrc) {
  $result = [ordered]@{
    ok                 = $false
    error              = "not_in_vault_cache"
    content_rel_paths  = @($ContentRelPaths)
    vault_cache_root   = $VaultCacheRoot
    notes              = "Pack not extracted under VaultCache/*/data/Content. Open UE Fab once to download into VaultCache, then retry."
  }
  if ($OutJson) {
    $dir = Split-Path $OutJson -Parent
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    ($result | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $OutJson -Encoding UTF8
  }
  Write-Host ($result | ConvertTo-Json -Compress)
  exit 2
}

$dest = Join-Path $ProjectContent $foundRel
$parent = Split-Path $dest -Parent
if (-not (Test-Path -LiteralPath $parent)) {
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
}

$bytesBefore = 0L
if (Test-Path -LiteralPath $dest) {
  $bytesBefore = [int64]((Get-ChildItem -LiteralPath $dest -Recurse -File -ErrorAction SilentlyContinue |
      Measure-Object Length -Sum).Sum)
}

Write-Host "install_fab: $foundSrc -> $dest"
if (-not $DryRun) {
  # /E copy subdirs; /XO skip older; /R:2 /W:2 retry; /NFL /NDL quieter
  & robocopy $foundSrc $dest /E /XO /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
  $rc = $LASTEXITCODE
  # robocopy 0-7 = success-ish
  if ($rc -ge 8) {
    throw "robocopy_failed exit=$rc src=$foundSrc dest=$dest"
  }
}

$bytesAfter = [int64]((Get-ChildItem -LiteralPath $dest -Recurse -File -ErrorAction SilentlyContinue |
    Measure-Object Length -Sum).Sum)
$folderName = Split-Path $foundRel -Leaf

$result = [ordered]@{
  ok                 = $true
  source_path        = $foundSrc
  vault_cache_pack   = $foundCache
  content_rel_path   = $foundRel
  host_content_path  = $dest
  content_folder_name = $folderName
  bytes              = $bytesAfter
  bytes_before       = $bytesBefore
  dry_run            = [bool]$DryRun
  notes              = "Installed from Epic VaultCache (no Fab UI)"
}

if ($OutJson) {
  $dir = Split-Path $OutJson -Parent
  if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  ($result | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $OutJson -Encoding UTF8
}

Write-Host ($result | ConvertTo-Json -Compress)
exit 0
