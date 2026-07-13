#Requires -Version 5.1
<#
.SYNOPSIS
  Remove Vellum UE host wrappers (service + scheduled tasks).
#>
param(
  [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $p = New-Object Security.Principal.WindowsPrincipal($id)
  return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not $RepoRoot) {
  $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
}
$InstallDir = Join-Path $RepoRoot "tools\unreal\host-install\runtime"
$WinSwExe = Join-Path $InstallDir "VellumUeAgent.exe"

foreach ($name in @("VellumUeAgent", "VellumLookdevWorkerEnsure", "VellumLookdevWorkerWatchdog")) {
  if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "Removed task $name"
  }
}

if (Test-Path $WinSwExe) {
  if (-not (Test-IsAdmin)) {
    Write-Host "WARNING: elevate to uninstall the Windows Service cleanly."
  } else {
    Push-Location $InstallDir
    try { & .\VellumUeAgent.exe stop | Out-Host } catch { }
    try { & .\VellumUeAgent.exe uninstall | Out-Host } catch { }
    Pop-Location
    Write-Host "WinSW service removed (if it was installed)."
  }
} elseif (Get-Service -Name "VellumUeAgent" -ErrorAction SilentlyContinue) {
  if (Test-IsAdmin) {
    Stop-Service VellumUeAgent -Force -ErrorAction SilentlyContinue
    sc.exe delete VellumUeAgent | Out-Host
  }
}

Write-Host "Uninstall finished. Unreal editor may still be running - close it manually if desired."
