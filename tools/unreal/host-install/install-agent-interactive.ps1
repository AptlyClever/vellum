#Requires -Version 5.1
<#
.SYNOPSIS
  Run VellumUeAgent in the interactive desktop session (not Local System).

.DESCRIPTION
  UnrealEditor-Cmd under WinSW/LocalSystem uses Session 0 + systemprofile DDC and
  cannot finish GPU lookdev. This script:
    1) Stops/uninstalls the VellumUeAgent Windows service if present
    2) Registers a logon Scheduled Task as the current interactive user
    3) Starts that task now

.EXAMPLE
  pwsh -File tools/unreal/host-install/install-agent-interactive.ps1
#>
param(
  [string]$HostName = "aurora",
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) {
  $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
$AgentPs1 = Join-Path $RepoRoot "tools\unreal\vellum_ue_agent.ps1"
if (-not (Test-Path $AgentPs1)) { throw "Missing $AgentPs1" }

$Pwsh = $null
$cmd = Get-Command pwsh -ErrorAction SilentlyContinue
if ($cmd) { $Pwsh = $cmd.Source }
if (-not $Pwsh) {
  $cmd = Get-Command powershell -ErrorAction SilentlyContinue
  if ($cmd) { $Pwsh = $cmd.Source }
}
if (-not $Pwsh) { throw "pwsh/powershell not on PATH" }

Write-Host "RepoRoot=$RepoRoot"
Write-Host "User=$env:USERNAME (interactive agent - not LocalSystem)"

# Stop SYSTEM service - it cannot own GPU UnrealEditor-Cmd.
$InstallDir = Join-Path $RepoRoot "tools\unreal\host-install\runtime"
$WinSwExe = Join-Path $InstallDir "VellumUeAgent.exe"
if (Get-Service -Name "VellumUeAgent" -ErrorAction SilentlyContinue) {
  Write-Host "Stopping/uninstalling Windows Service VellumUeAgent (LocalSystem)..."
  if (Test-Path $WinSwExe) {
    Push-Location $InstallDir
    try { & .\VellumUeAgent.exe stop | Out-Host } catch { }
    try { & .\VellumUeAgent.exe uninstall | Out-Host } catch { }
    Pop-Location
  } else {
    try { Stop-Service VellumUeAgent -Force -ErrorAction SilentlyContinue } catch { }
  }
  Start-Sleep -Seconds 2
}

# Kill any leftover agent process started by the service.
Get-CimInstance Win32_Process -Filter "Name='pwsh.exe' OR Name='powershell.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match 'vellum_ue_agent\.ps1' } |
  ForEach-Object {
    Write-Host "Killing leftover agent PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

$taskName = "VellumUeAgent"
$args = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$AgentPs1`" -VellumBase $VellumBase -HostName $HostName -LegacyCmdRunner"
$action = New-ScheduledTaskAction -Execute $Pwsh -Argument $args -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -RestartCount 5 `
  -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
  -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Scheduled Task '$taskName' registered (At logon, interactive)."

Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3
$info = Get-ScheduledTaskInfo -TaskName $taskName
$task = Get-ScheduledTask -TaskName $taskName
Write-Host ("TaskState={0} LastTaskResult={1} LastRunTime={2}" -f $task.State, $info.LastTaskResult, $info.LastRunTime)

# Fingerprint from disk (process may still be starting).
$fp = Select-String -Path $AgentPs1 -Pattern 'Agent fingerprint:' | Select-Object -First 1
Write-Host "Script: $($fp.Line.Trim())"
Write-Host "git HEAD: $(git -C $RepoRoot rev-parse --short HEAD)"
Write-Host "Done. Agent must run as $env:USERNAME - verify no VellumUeAgent Windows service remains."
Get-Service -Name "VellumUeAgent" -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "WARNING: service still present Status=$($_.Status) - uninstall failed?"
}
