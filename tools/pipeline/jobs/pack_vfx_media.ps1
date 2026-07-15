#Requires -Version 7.0
<#
.SYNOPSIS
  Pack MRQ PNG sequences into transparent WebM + simple sprite-sheet atlases when possible.
#>
param(
  [Parameter(Mandatory = $true)][string]$Pack,
  [string]$WorkDir = "F:\Games\AuroraVellum\Saved\VellumPipeline",
  [string]$OutDir = "",
  [int]$FrameRate = 30,
  [int]$MinFrames = 2,
  [switch]$RequireArtifacts
)

$ErrorActionPreference = "Stop"
$mrqRoot = Join-Path $WorkDir "$Pack\vfx\mrq"
if (-not $OutDir) { $OutDir = Join-Path $WorkDir "$Pack\vfx\packed" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
$results = @()

function Get-BigEndianUInt32 {
  param([byte[]]$Bytes, [int]$Offset)
  return (([int64]$Bytes[$Offset] -shl 24) -bor
    ([int64]$Bytes[$Offset + 1] -shl 16) -bor
    ([int64]$Bytes[$Offset + 2] -shl 8) -bor
    [int64]$Bytes[$Offset + 3])
}

function Get-PngInfo {
  param([Parameter(Mandatory = $true)][string]$Path)
  $bytes = [System.IO.File]::ReadAllBytes($Path)
  if ($bytes.Length -lt 33) { throw "png_too_small:$Path" }
  $sig = [byte[]](0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)
  for ($i = 0; $i -lt $sig.Length; $i++) {
    if ($bytes[$i] -ne $sig[$i]) { throw "not_png:$Path" }
  }

  $offset = 8
  $width = $null
  $height = $null
  $colorType = $null
  $hasTransparencyChunk = $false
  while ($offset + 12 -le $bytes.Length) {
    $length = [int](Get-BigEndianUInt32 -Bytes $bytes -Offset $offset)
    $chunkType = [System.Text.Encoding]::ASCII.GetString($bytes, $offset + 4, 4)
    $dataOffset = $offset + 8
    if ($chunkType -eq "IHDR") {
      $width = [int](Get-BigEndianUInt32 -Bytes $bytes -Offset $dataOffset)
      $height = [int](Get-BigEndianUInt32 -Bytes $bytes -Offset ($dataOffset + 4))
      $colorType = [int]$bytes[$dataOffset + 9]
    } elseif ($chunkType -eq "tRNS") {
      $hasTransparencyChunk = $true
    } elseif ($chunkType -eq "IEND") {
      break
    }
    $offset += 12 + $length
  }

  [pscustomobject]@{
    width = $width
    height = $height
    color_type = $colorType
    alpha = ($colorType -in @(4, 6)) -or $hasTransparencyChunk
  }
}

function Test-FrameMotion {
  param([Parameter(Mandatory = $true)][System.IO.FileInfo[]]$Frames)
  if ($Frames.Count -lt 2) { return $false }
  $first = (Get-FileHash -Algorithm SHA256 -LiteralPath $Frames[0].FullName).Hash
  $middle = (Get-FileHash -Algorithm SHA256 -LiteralPath $Frames[[Math]::Floor($Frames.Count / 2)].FullName).Hash
  $last = (Get-FileHash -Algorithm SHA256 -LiteralPath $Frames[$Frames.Count - 1].FullName).Hash
  return ($first -ne $middle) -or ($first -ne $last)
}

function New-SpriteSheet {
  param(
    [Parameter(Mandatory = $true)][System.IO.FileInfo[]]$Frames,
    [Parameter(Mandatory = $true)][string]$Destination
  )
  Add-Type -AssemblyName System.Drawing
  $sample = [System.Drawing.Image]::FromFile($Frames[0].FullName)
  try {
    $frameWidth = $sample.Width
    $frameHeight = $sample.Height
  } finally {
    $sample.Dispose()
  }
  $columns = [Math]::Min(8, $Frames.Count)
  $rows = [Math]::Ceiling($Frames.Count / $columns)
  $sheet = [System.Drawing.Bitmap]::new($frameWidth * $columns, $frameHeight * $rows, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $graphics = [System.Drawing.Graphics]::FromImage($sheet)
  try {
    $graphics.Clear([System.Drawing.Color]::Transparent)
    for ($i = 0; $i -lt $Frames.Count; $i++) {
      $img = [System.Drawing.Image]::FromFile($Frames[$i].FullName)
      try {
        $x = ($i % $columns) * $frameWidth
        $y = [Math]::Floor($i / $columns) * $frameHeight
        $graphics.DrawImage($img, $x, $y, $frameWidth, $frameHeight)
      } finally {
        $img.Dispose()
      }
    }
    $sheet.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Png)
  } finally {
    $graphics.Dispose()
    $sheet.Dispose()
  }
  [pscustomobject]@{
    path = $Destination
    columns = $columns
    rows = $rows
    frame_width = $frameWidth
    frame_height = $frameHeight
  }
}

function Get-WebMProbe {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not $ffprobe) { return $null }
  $json = & $ffprobe.Source -v error -select_streams v:0 -show_entries stream=width,height,nb_frames,pix_fmt,duration:stream_tags=alpha_mode -of json $Path
  if ($LASTEXITCODE -ne 0 -or -not $json) { return $null }
  try { return ($json | ConvertFrom-Json) } catch { return $null }
}

if (-not (Test-Path $mrqRoot)) {
  Write-Host "No MRQ frames at $mrqRoot - bake plan only (expected until Cmd MRQ render phase)."
  @{
    schema_version = 1
    pack = $Pack
    ok = (-not $RequireArtifacts)
    packed = @()
    note = "no_mrq_frames_yet"
  } | ConvertTo-Json | Set-Content (Join-Path $OutDir "pack-manifest.json") -Encoding utf8
  if ($RequireArtifacts) { exit 1 }
  exit 0
}

Get-ChildItem -LiteralPath $mrqRoot -Directory | ForEach-Object {
  $sys = $_.Name
  $pngs = @(Get-ChildItem -LiteralPath $_.FullName -Recurse -Filter *.png | Sort-Object FullName)
  if ($pngs.Count -eq 0) { return }
  $clipDir = Join-Path $OutDir $sys
  New-Item -ItemType Directory -Force -Path $clipDir | Out-Null
  $destWebm = Join-Path $clipDir "$sys.webm"
  $destSheet = Join-Path $clipDir "$sys.sprite-sheet.png"
  $firstInfo = Get-PngInfo -Path $pngs[0].FullName
  $dimsOk = $true
  foreach ($png in $pngs) {
    $info = Get-PngInfo -Path $png.FullName
    if ($info.width -ne $firstInfo.width -or $info.height -ne $firstInfo.height) {
      $dimsOk = $false
      break
    }
  }
  $motion = Test-FrameMotion -Frames $pngs
  $frameValidation = @{
    ok = ($pngs.Count -ge $MinFrames) -and $dimsOk -and [bool]$firstInfo.alpha -and $motion
    frame_count = $pngs.Count
    width = $firstInfo.width
    height = $firstInfo.height
    alpha = [bool]$firstInfo.alpha
    dimensions_consistent = $dimsOk
    non_empty_motion = $motion
    duration_seconds = [Math]::Round($pngs.Count / [double]$FrameRate, 3)
  }
  $entry = @{
    system = $sys
    frames = $pngs.Count
    frame_rate = $FrameRate
    validation = $frameValidation
    webm = $null
    webm_probe = $null
    sprite_sheet = $null
  }

  if ($ffmpeg) {
    $list = Join-Path $clipDir "frames.txt"
    $pngs | ForEach-Object {
      $framePath = $_.FullName.Replace('\','/').Replace("'","'\''")
      "file '$framePath'"
    } | Set-Content $list -Encoding ascii
    # yuva420p transparent webm
    & $ffmpeg.Source -y -hide_banner -loglevel error -f concat -safe 0 -r $FrameRate -i $list -c:v libvpx-vp9 -pix_fmt yuva420p -auto-alt-ref 0 $destWebm
    if ($LASTEXITCODE -eq 0 -and (Test-Path $destWebm)) {
      $entry.webm = $destWebm
      $entry.webm_probe = Get-WebMProbe -Path $destWebm
    } else {
      Write-Warning "ffmpeg failed for $sys; keeping sprite sheet / frame validation only"
    }
  } else {
    Write-Warning "ffmpeg not on PATH - generating sprite sheet only"
  }

  try {
    $entry.sprite_sheet = New-SpriteSheet -Frames $pngs -Destination $destSheet
  } catch {
    Write-Warning "sprite sheet failed for ${sys}: $_"
  }
  $results += $entry
}

@{
  schema_version = 1
  pack = $Pack
  ok = ($results.Count -gt 0) -and (($results | Where-Object { -not $_.validation.ok }).Count -eq 0) -and ((-not $RequireArtifacts) -or (($results | Where-Object { $_.webm -or $_.sprite_sheet }).Count -gt 0))
  packed = $results
  ffmpeg = [bool]$ffmpeg
  ffprobe = [bool]$ffprobe
  validation = @{
    min_frames = $MinFrames
    frame_rate = $FrameRate
    require_artifacts = [bool]$RequireArtifacts
  }
} | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $OutDir "pack-manifest.json") -Encoding utf8
Write-Host "Packed $($results.Count) systems -> $OutDir"
if ($RequireArtifacts -and ($results.Count -eq 0)) { exit 1 }
