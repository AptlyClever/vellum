#Requires -Version 5.1
$ErrorActionPreference = "Continue"
Write-Host "=== Launcher installed apps / engines ==="
$roots = @(
  "$env:PROGRAMDATA\Epic\UnrealEngineLauncher",
  "$env:PROGRAMDATA\Epic\EpicGamesLauncher",
  "$env:LOCALAPPDATA\EpicGamesLauncher\Saved\Data",
  "$env:LOCALAPPDATA\EpicGamesLauncher\Saved\Config\Windows"
)
foreach ($r in $roots) {
  if (Test-Path $r) {
    Write-Host "ROOT $r"
    Get-ChildItem $r -Recurse -File -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match 'Install|Manifest|LauncherInstalled|Engine|AppList|\.dat|\.json|\.xml' } |
      Select-Object -First 40 FullName, Length
  }
}
Write-Host "=== LauncherInstalled.dat ==="
$lid = @(
  "C:\ProgramData\Epic\UnrealEngineLauncher\LauncherInstalled.dat",
  "C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests",
  "$env:PROGRAMDATA\Epic\EpicGamesLauncher\Data\Manifests"
)
foreach ($p in $lid) {
  if (Test-Path $p) {
    Write-Host "FOUND $p"
    if ((Get-Item $p).PSIsContainer) {
      Get-ChildItem $p | Select-Object Name, Length
    } else {
      Get-Content $p -Raw | Select-Object -First 1
    }
  }
}
Write-Host "=== Registry Unreal Engine ==="
foreach ($hive in @(
  "HKLM:\SOFTWARE\EpicGames\Unreal Engine",
  "HKLM:\SOFTWARE\WOW6432Node\EpicGames\Unreal Engine",
  "HKCU:\SOFTWARE\Epic Games"
)) {
  if (Test-Path $hive) {
    Write-Host "HIVE $hive"
    Get-ChildItem $hive -ErrorAction SilentlyContinue | ForEach-Object {
      $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
      "$_ => InstalledDirectory=$($p.InstalledDirectory) InstallationGuid=$($p.InstallationGuid)"
    }
  }
}
Write-Host "=== Does F:\Games\UE_5.8 look Launcher-installed? ==="
Get-ChildItem "F:\Games\UE_5.8" -Force | Select-Object Name
Test-Path "F:\Games\UE_5.8\.egstore"
Test-Path "F:\Games\UE_5.8\Engine\Build\InstalledBuild.txt"
Get-Content "F:\Games\UE_5.8\Engine\Build\InstalledBuild.txt" -ErrorAction SilentlyContinue
