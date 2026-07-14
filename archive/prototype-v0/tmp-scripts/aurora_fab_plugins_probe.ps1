Write-Host "=== FabPlugins tree ==="
Get-ChildItem "$env:LOCALAPPDATA\FabPlugins" -Recurse -Depth 3 -ErrorAction SilentlyContinue |
  Select-Object -First 60 FullName, Length | Format-Table -AutoSize

Write-Host "`n=== FabLibrary listings DB ==="
Get-ChildItem "C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\FabLibrary" -Recurse -ErrorAction SilentlyContinue |
  Select-Object FullName, Length | Format-Table -AutoSize

Write-Host "`n=== VaultCache folder count ==="
(Get-ChildItem "C:\ProgramData\Epic\EpicGamesLauncher\VaultCache" -Directory).Count
Get-ChildItem "C:\ProgramData\Epic\EpicGamesLauncher\VaultCache" -Directory | ForEach-Object { $_.Name }
