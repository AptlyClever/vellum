#Requires -Version 7.0
<#
.SYNOPSIS
  Pack MRQ PNG sequences into transparent WebM + simple sprite-sheet atlases when possible.
#>
param(
  [Parameter(Mandatory = $true)][string]$Pack,
  [string]$WorkDir = "F:\Games\AuroraVellum\Saved\VellumPipeline",
  [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$mrqRoot = Join-Path $WorkDir "$Pack\vfx\mrq"
if (-not $OutDir) { $OutDir = Join-Path $WorkDir "$Pack\vfx\packed" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$results = @()

if (-not (Test-Path $mrqRoot)) {
  Write-Host "No MRQ frames at $mrqRoot — bake plan only (expected until Cmd MRQ render phase)."
  @{
    schema_version = 1
    pack = $Pack
    ok = $true
    packed = @()
    note = "no_mrq_frames_yet"
  } | ConvertTo-Json | Set-Content (Join-Path $OutDir "pack-manifest.json") -Encoding utf8
  exit 0
}

Get-ChildItem -LiteralPath $mrqRoot -Directory | ForEach-Object {
  $sys = $_.Name
  $pngs = @(Get-ChildItem -LiteralPath $_.FullName -Recurse -Filter *.png | Sort-Object FullName)
  if ($pngs.Count -eq 0) { return }
  $clipDir = Join-Path $OutDir $sys
  New-Item -ItemType Directory -Force -Path $clipDir | Out-Null
  $destWebm = Join-Path $clipDir "$sys.webm"
  $entry = @{ system = $sys; frames = $pngs.Count; webm = $null; sprite_sheet = $null }

  if ($ffmpeg) {
    $list = Join-Path $clipDir "frames.txt"
    $pngs | ForEach-Object { "file '$($_.FullName.Replace('\','/'))'" } | Set-Content $list -Encoding ascii
    # yuva420p transparent webm
    & ffmpeg -y -r 30 -i ($pngs[0].DirectoryName + "\%*.png") -c:v libvpx -pix_fmt yuva420p -auto-alt-ref 0 $destWebm 2>$null
    if (Test-Path $destWebm) { $entry.webm = $destWebm }
  } else {
    Write-Warning "ffmpeg not on PATH — copying PNG sequence only"
    $seq = Join-Path $clipDir "frames"
    New-Item -ItemType Directory -Force -Path $seq | Out-Null
    $pngs | Copy-Item -Destination $seq
    $entry.sprite_sheet = $seq
  }
  $results += $entry
}

@{
  schema_version = 1
  pack = $Pack
  ok = $true
  packed = $results
  ffmpeg = [bool]$ffmpeg
} | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $OutDir "pack-manifest.json") -Encoding utf8
Write-Host "Packed $($results.Count) systems -> $OutDir"
