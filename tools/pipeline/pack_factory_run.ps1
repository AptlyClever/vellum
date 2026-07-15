#Requires -Version 7.0
<#
.SYNOPSIS
  Zip a Conversion Factory pack output tree for hub upload.

Uses Store (no recompression) for already-compressed formats (png/glb/webm/wav)
and prefers manifests + a bounded slice of binaries so uploads stay under the
hub ingest cap.
#>
param(
  [Parameter(Mandatory = $true)][string[]]$SourceDirs,
  [Parameter(Mandatory = $true)][string]$DestinationZip,
  [int]$MaxFiles = 480
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$storeExt = [System.Collections.Generic.HashSet[string]]::new(
  [string[]]@(".png", ".jpg", ".jpeg", ".webp", ".glb", ".gltf", ".webm", ".wav", ".ogg", ".mp3")
)

$files = New-Object System.Collections.Generic.List[object]
foreach ($dir in $SourceDirs) {
  if (-not (Test-Path $dir)) { continue }
  $root = (Resolve-Path $dir).Path
  Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($root.Length).TrimStart("\", "/")
    $entry = Join-Path (Split-Path $root -Leaf) $rel
    $files.Add([pscustomobject]@{
      FullName = $_.FullName
      Entry    = ($entry -replace "\\", "/")
      Ext      = $_.Extension.ToLowerInvariant()
      IsManifest = ($_.Name -match '(?i)manifest\.json$|bake-plan\.json$')
      Length = $_.Length
    })
  }
}

# Prefer manifests, then smaller binaries, then the rest — stay under MaxFiles.
$selected = @(
  ($files | Where-Object IsManifest) +
  ($files | Where-Object { -not $_.IsManifest } | Sort-Object Length)
) | Select-Object -First $MaxFiles

if (Test-Path $DestinationZip) { Remove-Item $DestinationZip -Force }
$zip = [System.IO.Compression.ZipFile]::Open($DestinationZip, [System.IO.Compression.ZipArchiveMode]::Create)
try {
  foreach ($f in $selected) {
    $level = if ($storeExt.Contains($f.Ext)) {
      [System.IO.Compression.CompressionLevel]::NoCompression
    } else {
      [System.IO.Compression.CompressionLevel]::Optimal
    }
    [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $f.FullName, $f.Entry, $level)
  }
} finally {
  $zip.Dispose()
}

Write-Host "Packed $($selected.Count)/$($files.Count) files -> $DestinationZip"
