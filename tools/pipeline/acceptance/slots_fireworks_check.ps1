#Requires -Version 7.0
param(
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$AssetId = "fireworks-vol-1-niagara"
)

$ErrorActionPreference = "Stop"
$els = Invoke-RestMethod "$VellumBase/api/game-ready/elements?asset_id=$AssetId&limit=50"
Write-Host "elements=$($els.count)"
$published = @($els.elements | Where-Object { $_.lanes -contains "slots" })
Write-Host "published_to_slots=$($published.Count)"
if ($els.count -lt 1) {
  Write-Host "FAIL: no game-ready elements — run bake-vfx / export jobs + ingest-manifest"
  exit 1
}
if ($published.Count -lt 1) {
  Write-Host "WARN: elements exist but none published to slots yet"
  exit 2
}
foreach ($p in $published) {
  $lp = $p.lane_paths.slots
  Write-Host "ok id=$($p.id) kind=$($p.kind) lane_path=$lp"
}
Write-Host "PASS: catalog + slots publish present (operator still confirms in-game playback)"
exit 0
