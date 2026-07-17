#Requires -Version 7.0
<#
.SYNOPSIS
  Copy only validation-passing VFX pack outputs into a filtered upload tree.

.DESCRIPTION
  `pack_vfx_media.ps1 -AllowPartialArtifacts` can produce a useful partial VFX
  run where some Niagara systems pass alpha / visible-content / motion gates
  and some do not. Game lanes should only see valid systems, and upload-run
  replaces whole pack catalog rows, so this script builds the upload tree from
  the passing systems only.
#>
param(
  [Parameter(Mandatory = $true)][string]$SourceDir,
  [Parameter(Mandatory = $true)][string]$DestinationDir
)

$ErrorActionPreference = "Stop"
$manifestPath = Join-Path $SourceDir "pack-manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath)) {
  throw "missing_pack_manifest:$manifestPath"
}

if (Test-Path -LiteralPath $DestinationDir) {
  Remove-Item -LiteralPath $DestinationDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$valid = @($manifest.packed | Where-Object { [bool]$_.validation.ok })
if ($valid.Count -eq 0) {
  throw "no_valid_vfx_systems:$SourceDir"
}

foreach ($entry in $valid) {
  $sys = [string]$entry.system
  foreach ($file in @(Get-ChildItem -LiteralPath $SourceDir -Recurse -File | Where-Object { $_.Name -like "$sys*" })) {
    $rel = $file.FullName.Substring($SourceDir.Length + 1)
    $target = Join-Path $DestinationDir $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target -Force
  }
}

$filtered = [ordered]@{
  schema_version = $manifest.schema_version
  pack           = $manifest.pack
  ok             = $true
  partial        = [bool](@($manifest.packed).Count -gt $valid.Count)
  packed         = $valid
  ffmpeg         = $manifest.ffmpeg
  ffprobe        = $manifest.ffprobe
  validation     = [ordered]@{
    min_frames              = $manifest.validation.min_frames
    frame_rate              = $manifest.validation.frame_rate
    require_artifacts       = $manifest.validation.require_artifacts
    allow_partial_artifacts = $true
    valid_systems           = $valid.Count
    invalid_systems         = 0
    artifact_systems        = $valid.Count
    filtered_from_systems   = @($manifest.packed).Count
  }
}
$filtered | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $DestinationDir "pack-manifest.json") -Encoding utf8
Write-Host "Filtered VFX systems: $($valid.Count) / $(@($manifest.packed).Count) -> $DestinationDir"
