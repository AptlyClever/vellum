#Requires -Version 5.1
$ErrorActionPreference = "Continue"
$vault = "C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\FabLibrary"
Write-Host "=== VaultCache packs ==="
Get-ChildItem -LiteralPath $vault -Directory -ErrorAction SilentlyContinue | ForEach-Object {
  $count = @(Get-ChildItem -LiteralPath $_.FullName -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 5).Count
  $bytes = 0
  try {
    $bytes = (Get-ChildItem -LiteralPath $_.FullName -Recurse -File -ErrorAction SilentlyContinue |
      Measure-Object -Property Length -Sum).Sum
  } catch {}
  "{0}`tfiles~{1}+`tsize={2:N0}" -f $_.Name, $count, $bytes
}
Write-Host "=== sample ContainerCity tree ==="
$cc = Join-Path $vault "Container_City-caf4e413"
if (Test-Path -LiteralPath $cc) {
  Get-ChildItem -LiteralPath $cc -Force | Format-Table Name, Mode, Length
  Get-ChildItem -LiteralPath $cc -Recurse -Force -ErrorAction SilentlyContinue |
    Select-Object -First 30 FullName, Length
}
Write-Host "=== Launcher log hits ==="
$log = Join-Path $env:LOCALAPPDATA "EpicGamesLauncher\Saved\Logs\EpicGamesLauncher.log"
if (Test-Path $log) {
  Select-String -Path $log -Pattern "AuroraVellum|InstallDirectory|incompat|AddToProject|VaultCache|EngineAssociation|Browse" |
    Select-Object -Last 40 | ForEach-Object { $_.Line }
}
Write-Host "=== uproject + EngineAssoc ==="
Get-Content "F:\Games\AuroraVellum\AuroraVellum.uproject" -Raw
Write-Host "=== build id ==="
Get-Content "F:\Games\UE_5.8\Engine\Build\Build.version" -Raw
