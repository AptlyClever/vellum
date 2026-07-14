#Requires -Version 5.1
<#
.SYNOPSIS
  One-shot: make F:\Games\AuroraVellum the only Fab/Vellum UE project.

.DESCRIPTION
  1. Rename typo AuroraVallum.uproject to AuroraVellum.uproject on F:
  2. Robocopy Content folders from accidental C:\dev\AuroraVellum dump to F:
     (never overwrite Lookdev Vellum\; skip FireworksV1 if F: already has it)
  3. Optional -RemoveDumpAfter deletes C:\dev\AuroraVellum after copy.

.EXAMPLE
  pwsh -File tools/unreal/consolidate_aurora_projects.ps1
  pwsh -File tools/unreal/consolidate_aurora_projects.ps1 -RemoveDumpAfter
#>
param(
  [string]$CanonicalDir = "F:\Games\AuroraVellum",
  [string]$DumpDir = "C:\dev\AuroraVellum",
  [switch]$WhatIf,
  [switch]$RemoveDumpAfter
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Msg) { Write-Host "=== $Msg" }

$canonContent = Join-Path $CanonicalDir "Content"
$dumpContent = Join-Path $DumpDir "Content"
$canonUproject = Join-Path $CanonicalDir "AuroraVellum.uproject"
$typoUproject = Join-Path $CanonicalDir "AuroraVallum.uproject"

if (-not (Test-Path -LiteralPath $CanonicalDir)) {
  throw "Canonical project missing: $CanonicalDir"
}

Write-Step "Ensure AuroraVellum.uproject on F:"
if (Test-Path -LiteralPath $canonUproject) {
  Write-Host "OK $canonUproject"
} elseif (Test-Path -LiteralPath $typoUproject) {
  if ($WhatIf) {
    Write-Host "Would rename typo uproject to AuroraVellum.uproject"
  } else {
    Rename-Item -LiteralPath $typoUproject -NewName "AuroraVellum.uproject"
    Write-Host "Renamed AuroraVallum.uproject -> AuroraVellum.uproject"
  }
} else {
  $dumpProj = Join-Path $DumpDir "AuroraVellum.uproject"
  if (Test-Path -LiteralPath $dumpProj) {
    if ($WhatIf) {
      Write-Host "Would copy dump uproject to F:"
    } else {
      Copy-Item -LiteralPath $dumpProj -Destination $canonUproject
      Write-Host "Copied uproject from dump"
    }
  } else {
    throw "No AuroraVellum.uproject or AuroraVallum.uproject on F: and no dump uproject"
  }
}

New-Item -ItemType Directory -Force -Path $canonContent | Out-Null

$skipNames = @{
  Collections = $true
  Developers = $true
  __ExternalActors__ = $true
  __ExternalObjects__ = $true
  Vellum = $true
}

if (-not (Test-Path -LiteralPath $dumpContent)) {
  Write-Host "No dump Content at $dumpContent - nothing to copy (F: already sole root)."
  exit 0
}

Write-Step "Robocopy dump Content -> canonical F:"
$copied = 0
$skipped = 0
foreach ($d in @(Get-ChildItem -LiteralPath $dumpContent -Directory -ErrorAction SilentlyContinue)) {
  if ($skipNames.ContainsKey($d.Name)) {
    Write-Host "SKIP (protected/system): $($d.Name)"
    $skipped++
    continue
  }
  $dest = Join-Path $canonContent $d.Name
  if ($d.Name -eq "FireworksV1" -and (Test-Path -LiteralPath $dest)) {
    Write-Host "SKIP FireworksV1 (already on F:)"
    $skipped++
    continue
  }
  if ($WhatIf) {
    Write-Host "Would robocopy $($d.FullName) -> $dest"
    $copied++
    continue
  }
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  & robocopy $d.FullName $dest /E /XO /R:2 /W:2 /NFL /NDL /NJH /NJS | Out-Null
  $rc = $LASTEXITCODE
  if ($rc -ge 8) {
    throw "robocopy failed $($d.Name) exit=$rc"
  }
  Write-Host "COPIED $($d.Name) (robocopy=$rc)"
  $copied++
}

Write-Host "Done. copied=$copied skipped=$skipped"
Write-Host "Canonical Content:"
Get-ChildItem -LiteralPath $canonContent -Directory | ForEach-Object { Write-Host "  $($_.Name)" }

if ($RemoveDumpAfter -and -not $WhatIf) {
  Write-Step "Removing dump project $DumpDir"
  Remove-Item -LiteralPath $DumpDir -Recurse -Force
  Write-Host "Removed $DumpDir"
} else {
  Write-Host "Dump left in place. Fab must use: $canonUproject"
  Write-Host "Re-run with -RemoveDumpAfter after vault stages if you want C:\dev gone."
}
