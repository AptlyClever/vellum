#Requires -Version 7.0
<#
.SYNOPSIS
  Publish an asset's baked VFX clips to a game lane with a per-variant
  presentation contract.

.DESCRIPTION
  After a Conversion Factory VFX run is uploaded (upload-run registers
  vfx-clip rows with meta.variant = contained|breakout), this script
  publishes each clip to the target lane so games can consume it.

  The tier contract is templated off the proven Fireworks BrocadeCrown row:
    contained -> normal win   (anchor=reel-window, tier=win)
    breakout  -> big-win burst (anchor=reel-window, tier=big-win, radial)

  Idempotent: clips already published to the lane are skipped.

.EXAMPLE
  pwsh -File tools/pipeline/publish_vfx_slots.ps1 -AssetId fireworks-vol-1-niagara
#>
param(
  [Parameter(Mandatory = $true)][string]$AssetId,
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$Lane = "slots",
  [string]$Anchor = "reel-window",
  [switch]$PublishInvalid,
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

# Per-variant presentation contract (matches the shipped BrocadeCrown rows).
$contracts = @{
  contained = @{
    anchor               = $Anchor
    containment          = "contained"
    tier                 = "win"
    scale                = 1.0
    max_duration_seconds = 4.0
  }
  breakout  = @{
    anchor               = $Anchor
    containment          = "breakout"
    tier                 = "big-win"
    spread               = "radial"
    scale                = 1.6
    max_duration_seconds = 5.0
  }
}

$elems = Invoke-RestMethod "$VellumBase/api/game-ready/elements?asset_id=$AssetId&kind=vfx-clip&limit=1000" -TimeoutSec 30
Write-Host "vfx-clip rows for ${AssetId}: $($elems.count)"

$published = 0
$skipped = 0
$invalid = 0
foreach ($el in @($elems.elements)) {
  $variant = [string]$el.meta.variant
  if (-not $contracts.ContainsKey($variant)) {
    # Non-variant master clips are not lane-published; only anchored derivatives.
    continue
  }
  if (-not $PublishInvalid -and -not [bool]$el.meta.validation.ok) {
    Write-Host "skip invalid -> $($el.id) [$variant] $((Split-Path $el.path -Leaf))"
    $invalid++
    continue
  }
  $lanes = @($el.lanes)
  if ($lanes -contains $Lane) {
    $skipped++
    continue
  }
  $body = @{ lane = $Lane; presentation = $contracts[$variant] } | ConvertTo-Json -Depth 6
  $label = "$($el.id) [$variant] $((Split-Path $el.path -Leaf))"
  if ($WhatIf) {
    Write-Host "WOULD publish -> $label"
    continue
  }
  try {
    $null = Invoke-RestMethod -Method Post `
      -Uri "$VellumBase/api/game-ready/elements/$($el.id)/publish" `
      -ContentType "application/json" -Body $body -TimeoutSec 60
    Write-Host "published -> $label"
    $published++
  } catch {
    Write-Warning "publish failed for ${label}: $($_.Exception.Message)"
  }
}

Write-Host "Done. published=$published already_on_lane=$skipped invalid_skipped=$invalid lane=$Lane"
