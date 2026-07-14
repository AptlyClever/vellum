$paths = @(
  "$env:LOCALAPPDATA\Fab",
  "$env:LOCALAPPDATA\UnrealEngine\Common\Fab",
  "$env:LOCALAPPDATA\UnrealEngine\5.8\Saved\Fab",
  "$env:LOCALAPPDATA\EpicGamesLauncher\Saved",
  "C:\ProgramData\Epic\EpicGamesLauncher\VaultCache",
  "F:\Games\AuroraVellum\Saved\Fab",
  "$env:LOCALAPPDATA\EpicGamesLauncher\Saved\Config\Windows",
  "$env:LOCALAPPDATA\UnrealEngine\Common"
)
foreach ($p in $paths) {
  if (Test-Path $p) {
    Write-Host "FOUND $p"
    Get-ChildItem $p -ErrorAction SilentlyContinue | Select-Object -First 20 Name, Mode, Length | Format-Table -AutoSize
  } else {
    Write-Host "missing $p"
  }
}

Write-Host "`n=== search for FabAssetsCache / downloads ==="
Get-ChildItem "$env:LOCALAPPDATA" -Directory -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -match 'Fab|Epic|Unreal' } |
  ForEach-Object { Write-Host $_.FullName }

# Look for *.db under Epic that might list ALL library entitlements
Write-Host "`n=== Epic DBs ==="
Get-ChildItem "$env:LOCALAPPDATA\EpicGamesLauncher" -Recurse -Include *.db,*.json -ErrorAction SilentlyContinue |
  Where-Object { $_.Length -lt 50MB } |
  Select-Object -First 40 FullName, Length
