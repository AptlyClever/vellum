$need = @(
  'Abandoned','Arabic','Cappadocia','Glass','Ice Fortress','Loot','Magic Abilit','Magic Project',
  'Dirty Wall','Marble','Middle Eastern','Motel','Niagara Mega','Oil Rig','Stylized','Church','Mansion','Warehouse','Cabin'
)
$roots = @(
  'F:\Games\AuroraVellum\Content',
  'C:\ProgramData\Epic\EpicGamesLauncher\VaultCache',
  "$env:LOCALAPPDATA\EpicGamesLauncher\Saved",
  'C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests'
)
Write-Host '=== Content match (should be empty for the 19) ==='
Get-ChildItem 'F:\Games\AuroraVellum\Content' -Directory -ErrorAction SilentlyContinue |
  Where-Object { $n=$_.Name; $need | Where-Object { $n -match $_ } } |
  ForEach-Object { $_.Name }

Write-Host '=== VaultCache top folders (count) ==='
$vc = 'C:\ProgramData\Epic\EpicGamesLauncher\VaultCache'
if (Test-Path $vc) {
  $dirs = Get-ChildItem $vc -Directory -ErrorAction SilentlyContinue
  Write-Host "VaultCache dirs: $($dirs.Count)"
  $dirs | Select-Object -First 30 Name | ForEach-Object { $_.Name }
} else { Write-Host "NO VaultCache at $vc" }

Write-Host '=== FabLibrary / .manifest quick ==='
@(
  'C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests',
  "$env:LOCALAPPDATA\EpicGamesLauncher\Saved\Library"
) | ForEach-Object {
  if (Test-Path $_) { Write-Host "exists $_"; Get-ChildItem $_ -ErrorAction SilentlyContinue | Select-Object -First 8 Name }
  else { Write-Host "missing $_" }
}

# Fab plugin local listing if any under Aurora
Write-Host '=== search for local_listing json near Fab ==='
Get-ChildItem 'F:\Games\AuroraVellum' -Recurse -Filter '*local_listing*' -ErrorAction SilentlyContinue |
  Select-Object -First 10 FullName
Get-ChildItem "$env:LOCALAPPDATA\UnrealEngine" -Recurse -Filter '*Fab*' -Directory -ErrorAction SilentlyContinue |
  Select-Object -First 15 FullName
