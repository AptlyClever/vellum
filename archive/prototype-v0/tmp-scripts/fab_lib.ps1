$fab = 'C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\FabLibrary'
Write-Host "FabLibrary exists=$(Test-Path $fab)"
if (Test-Path $fab) {
  Get-ChildItem $fab -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'listing|library|json|manifest' } |
    Select-Object -First 40 FullName, Length
  Get-ChildItem $fab -ErrorAction SilentlyContinue | Select-Object Name, Mode, Length
}
# Motel / Japanese / Industrial / Untitled in VaultCache — map?
Write-Host '=== curious VaultCache names ==='
Get-ChildItem 'C:\ProgramData\Epic\EpicGamesLauncher\VaultCache' -Directory |
  ForEach-Object { $_.Name }
