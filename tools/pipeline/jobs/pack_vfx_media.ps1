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
if (Test-Path -LiteralPath $OutDir) {
  Remove-Item -LiteralPath $OutDir -Recurse -Force
}
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

function Get-FrameVisualStats {
  param([Parameter(Mandatory = $true)][string]$Path)
  Add-Type -AssemblyName System.Drawing
  $bitmap = [System.Drawing.Bitmap]::new($Path)
  try {
    $stepX = [Math]::Max(1, [Math]::Floor($bitmap.Width / 240))
    $stepY = [Math]::Max(1, [Math]::Floor($bitmap.Height / 135))
    $samples = 0
    $opaque = 0
    $visible = 0
    $bright = 0
    for ($y = 0; $y -lt $bitmap.Height; $y += $stepY) {
      for ($x = 0; $x -lt $bitmap.Width; $x += $stepX) {
        $pixel = $bitmap.GetPixel($x, $y)
        $samples++
        if ($pixel.A -lt 16) { continue }
        $opaque++
        $peak = [Math]::Max($pixel.R, [Math]::Max($pixel.G, $pixel.B))
        if ($peak -ge 24) { $visible++ }
        if ($peak -ge 64) { $bright++ }
      }
    }
    $visibleToOpaque = if ($opaque -gt 0) { $visible / [double]$opaque } else { 0.0 }
    [pscustomobject]@{
      frame = $Path
      sampled_pixels = $samples
      opaque_pixels = $opaque
      visible_pixels = $visible
      bright_pixels = $bright
      opaque_fraction = [Math]::Round($opaque / [double]$samples, 6)
      visible_fraction = [Math]::Round($visible / [double]$samples, 6)
      visible_to_opaque_ratio = [Math]::Round($visibleToOpaque, 6)
    }
  } finally {
    $bitmap.Dispose()
  }
}

function Get-AlphaBoundingBox {
  <#
    Union bounding box of visible (alpha >= 16) pixels across sampled frames.
    Runtimes position effects relative to their anchor, so the contained
    derivative must crop away the empty canvas around the actual burst.
  #>
  param(
    [Parameter(Mandatory = $true)][System.IO.FileInfo[]]$Frames,
    [int]$MaxSampledFrames = 12,
    [int]$PixelStep = 6
  )
  Add-Type -AssemblyName System.Drawing
  $stride = [Math]::Max(1, [Math]::Floor($Frames.Count / $MaxSampledFrames))
  $minX = [int]::MaxValue; $minY = [int]::MaxValue
  $maxX = -1; $maxY = -1
  for ($f = 0; $f -lt $Frames.Count; $f += $stride) {
    $bitmap = [System.Drawing.Bitmap]::new($Frames[$f].FullName)
    try {
      for ($y = 0; $y -lt $bitmap.Height; $y += $PixelStep) {
        for ($x = 0; $x -lt $bitmap.Width; $x += $PixelStep) {
          if ($bitmap.GetPixel($x, $y).A -ge 16) {
            if ($x -lt $minX) { $minX = $x }
            if ($x -gt $maxX) { $maxX = $x }
            if ($y -lt $minY) { $minY = $y }
            if ($y -gt $maxY) { $maxY = $y }
          }
        }
      }
    } finally {
      $bitmap.Dispose()
    }
  }
  if ($maxX -lt 0) { return $null }
  [pscustomobject]@{
    x = $minX
    y = $minY
    width = ($maxX - $minX + 1)
    height = ($maxY - $minY + 1)
  }
}

function Get-ContainedCrop {
  <# Pad the content bbox, clamp to the frame, force even dimensions. #>
  param(
    [Parameter(Mandatory = $true)]$Bbox,
    [Parameter(Mandatory = $true)][int]$FrameWidth,
    [Parameter(Mandatory = $true)][int]$FrameHeight,
    [int]$Padding = 24
  )
  $x = [Math]::Max(0, $Bbox.x - $Padding)
  $y = [Math]::Max(0, $Bbox.y - $Padding)
  $right = [Math]::Min($FrameWidth, $Bbox.x + $Bbox.width + $Padding)
  $bottom = [Math]::Min($FrameHeight, $Bbox.y + $Bbox.height + $Padding)
  $w = $right - $x
  $h = $bottom - $y
  if ($w % 2 -ne 0) { $w = [Math]::Max(2, $w - 1) }
  if ($h % 2 -ne 0) { $h = [Math]::Max(2, $h - 1) }
  [pscustomobject]@{ x = $x; y = $y; width = $w; height = $h }
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
  $sampleFrames = @(
    $pngs[0]
    $pngs[[Math]::Floor($pngs.Count / 2)]
    $pngs[$pngs.Count - 1]
  ) | Select-Object -Unique
  $visualSamples = @($sampleFrames | ForEach-Object {
    Get-FrameVisualStats -Path $_.FullName
  })
  $maxVisibleRatio = [double](($visualSamples | Measure-Object -Property visible_to_opaque_ratio -Maximum).Maximum ?? 0)
  $maxBrightPixels = [int](($visualSamples | Measure-Object -Property bright_pixels -Maximum).Maximum ?? 0)
  $visibleContent = ($maxVisibleRatio -ge 0.05) -and ($maxBrightPixels -ge 2)
  $frameValidation = @{
    ok = ($pngs.Count -ge $MinFrames) -and $dimsOk -and [bool]$firstInfo.alpha -and $motion -and $visibleContent
    frame_count = $pngs.Count
    width = $firstInfo.width
    height = $firstInfo.height
    alpha = [bool]$firstInfo.alpha
    dimensions_consistent = $dimsOk
    non_empty_motion = $motion
    visible_content = $visibleContent
    max_visible_to_opaque_ratio = [Math]::Round($maxVisibleRatio, 6)
    max_bright_sample_pixels = $maxBrightPixels
    visual_samples = $visualSamples
    duration_seconds = [Math]::Round($pngs.Count / [double]$FrameRate, 3)
  }
  $entry = @{
    system = $sys
    frames = $pngs.Count
    frame_rate = $FrameRate
    validation = $frameValidation
    webm = $null
    webm_probe = $null
    contained = $null
    breakout = $null
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

    # Anchored derivatives: tight-crop to visible content and cap size so TV
    # runtimes decode a small positioned burst instead of a full 1080p canvas.
    # "contained" serves normal wins inside the anchor; "breakout" serves
    # big-win escapes at a higher cap (until dedicated breakout media exists).
    if ($entry.webm) {
      $bbox = Get-AlphaBoundingBox -Frames $pngs
      if ($bbox) {
        $crop = Get-ContainedCrop -Bbox $bbox -FrameWidth $firstInfo.width -FrameHeight $firstInfo.height
        foreach ($variant in @(
          @{ name = "contained"; max_dim = 720 },
          @{ name = "breakout"; max_dim = 960 }
        )) {
          $maxDim = $variant.max_dim
          $scaleFactor = [Math]::Min(1.0, $maxDim / [double][Math]::Max($crop.width, $crop.height))
          $outW = [Math]::Max(2, [int]([Math]::Floor($crop.width * $scaleFactor / 2) * 2))
          $outH = [Math]::Max(2, [int]([Math]::Floor($crop.height * $scaleFactor / 2) * 2))
          $destVariant = Join-Path $clipDir "$sys.$($variant.name).webm"
          $filter = "crop=$($crop.width):$($crop.height):$($crop.x):$($crop.y),scale=${outW}:${outH}"
          & $ffmpeg.Source -y -hide_banner -loglevel error -f concat -safe 0 -r $FrameRate -i $list -vf $filter -c:v libvpx-vp9 -pix_fmt yuva420p -auto-alt-ref 0 $destVariant
          if ($LASTEXITCODE -eq 0 -and (Test-Path $destVariant)) {
            $entry[$variant.name] = @{
              webm = $destVariant
              source_crop = @{ x = $crop.x; y = $crop.y; width = $crop.width; height = $crop.height }
              width = $outW
              height = $outH
              probe = Get-WebMProbe -Path $destVariant
            }
          } else {
            Write-Warning "$($variant.name) derivative failed for $sys"
          }
        }
      } else {
        Write-Warning "no visible pixels found for anchored derivatives of $sys"
      }
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

$packOk = ($results.Count -gt 0) -and (($results | Where-Object { -not $_.validation.ok }).Count -eq 0) -and ((-not $RequireArtifacts) -or (($results | Where-Object { $_.webm -or $_.sprite_sheet }).Count -gt 0))
@{
  schema_version = 1
  pack = $Pack
  ok = $packOk
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
if ($RequireArtifacts -and -not $packOk) { exit 1 }
