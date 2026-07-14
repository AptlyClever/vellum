#Requires -Version 5.1
<#
.SYNOPSIS
  Install Vellum UE host wrappers on Aurora (no babysat console).

.DESCRIPTION
  Default: interactive logon Scheduled Task for VellumUeAgent (Lookdev Worker path).
  Registers VellumLookdevWorkerEnsure (-LaunchGui) and watchdog.
  Optional WinSW service is disabled for Capture - LocalSystem Session 0 cannot own the GPU editor.

  Run elevated once on the GPU box after git pull.

.EXAMPLE
  pwsh -File tools/unreal/host-install/install.ps1
  pwsh -File tools/unreal/host-install/install-agent-interactive.ps1
#>
param(
  [string]$HostName = "aurora",
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$RepoRoot = "",
  # Capture agent must be interactive - do not install WinSW LocalSystem service.
  [switch]$InstallWinSwService,
  [switch]$SkipLogonTask,
  [switch]$SkipWatchdog,
  [switch]$SkipAgentTask,
  [switch]$StartWorkerNow
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
$RepoRoot = (Resolve-Path $RepoRoot).Path
$AgentPs1 = Join-Path $RepoRoot "tools\unreal\vellum_ue_agent.ps1"
$WorkerPs1 = Join-Path $RepoRoot "tools\unreal\vellum_ue_worker.ps1"
$Template = Join-Path $PSScriptRoot "VellumUeAgent.winsw.xml.template"
$InstallDir = Join-Path $RepoRoot "tools\unreal\host-install\runtime"
$LogDir = Join-Path $InstallDir "logs"
$WinSwExe = Join-Path $InstallDir "VellumUeAgent.exe"
$WinSwXml = Join-Path $InstallDir "VellumUeAgent.xml"
$WinSwUrl = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe"

if (-not (Test-Path $AgentPs1)) { throw "Missing agent: $AgentPs1" }
if (-not (Test-Path $WorkerPs1)) { throw "Missing worker: $WorkerPs1" }
if (-not (Test-Path $Template)) { throw "Missing template: $Template" }

$Pwsh = $null
$cmd = Get-Command pwsh -ErrorAction SilentlyContinue
if ($cmd) { $Pwsh = $cmd.Source }
if (-not $Pwsh) {
  $cmd = Get-Command powershell -ErrorAction SilentlyContinue
  if ($cmd) { $Pwsh = $cmd.Source }
}
if (-not $Pwsh) { throw "pwsh/powershell not on PATH" }

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "RepoRoot=$RepoRoot"
Write-Host "HostName=$HostName VellumBase=$VellumBase"
Write-Host "Pwsh=$Pwsh"

# --- Python (required for pick_heroes.py on Capture / Recover) ---
$pythonOk = $false
foreach ($pyCand in @(
    "C:\Python312\python.exe",
    "C:\Program Files\Python312\python.exe"
  )) {
  if ((Test-Path $pyCand) -and ((Get-Item $pyCand).Length -gt 1024)) {
    Write-Host "Python OK: $pyCand (& $($(& $pyCand --version) -join ' '))"
    $pythonOk = $true
    break
  }
}
if (-not $pythonOk) {
  $choco = Get-Command choco -ErrorAction SilentlyContinue
  if (-not $choco) {
    throw "Python 3.12 missing and chocolatey not on PATH. Install: https://chocolatey.org then choco install python312 -y"
  }
  Write-Host "Installing Python 3.12 via chocolatey (required for capture hero pick)..."
  & choco install python312 -y --no-progress
  if (-not (Test-Path "C:\Python312\python.exe")) {
    throw "choco install python312 finished but C:\Python312\python.exe missing"
  }
  Write-Host "Python installed: $((& C:\Python312\python.exe --version) -join ' ')"
}

# --- WinSW binary ---
if (-not (Test-Path $WinSwExe)) {
  Write-Host "Downloading WinSW 2.12.0..."
  Invoke-WebRequest -Uri $WinSwUrl -OutFile $WinSwExe -UseBasicParsing
}
if (-not (Test-Path $WinSwExe)) { throw "WinSW download failed: $WinSwExe" }

# --- Stamp service XML ---
$xml = Get-Content $Template -Raw
$xml = $xml.Replace("{{PWSH}}", $Pwsh)
$xml = $xml.Replace("{{AGENT_PS1}}", $AgentPs1)
$xml = $xml.Replace("{{VELLUM_BASE}}", $VellumBase)
$xml = $xml.Replace("{{HOST_NAME}}", $HostName)
$xml = $xml.Replace("{{REPO_ROOT}}", $RepoRoot)
$xml = $xml.Replace("{{LOG_DIR}}", $LogDir)
Set-Content -Path $WinSwXml -Value $xml -Encoding UTF8
Write-Host "Wrote $WinSwXml"

# --- Capture agent: interactive Scheduled Task (default). WinSW LocalSystem is opt-in only. ---
if (-not $SkipAgentTask) {
  $InteractiveInstall = Join-Path $PSScriptRoot "install-agent-interactive.ps1"
  if (-not (Test-Path $InteractiveInstall)) { throw "Missing $InteractiveInstall" }
  & $Pwsh -NoProfile -ExecutionPolicy Bypass -File $InteractiveInstall `
    -HostName $HostName -VellumBase $VellumBase -RepoRoot $RepoRoot
}

# --- Optional WinSW service (NOT recommended for Capture - Session 0 / no GPU) ---
if ($InstallWinSwService) {
  if (-not (Test-IsAdmin)) {
    throw "Service install needs elevation. Re-run from Admin PowerShell."
  }
  Write-Host "WARNING: Installing WinSW LocalSystem agent - UnrealEditor-Cmd Capture will hang."
  $existing = Get-Service -Name "VellumUeAgent" -ErrorAction SilentlyContinue
  if ($existing) {
    Write-Host "Stopping existing VellumUeAgent..."
    Push-Location $InstallDir
    try { & .\VellumUeAgent.exe stop | Out-Host } catch { }
    try { & .\VellumUeAgent.exe uninstall | Out-Host } catch { }
    Pop-Location
    Start-Sleep -Seconds 2
  }
  Write-Host "Installing Windows Service VellumUeAgent..."
  Push-Location $InstallDir
  try {
    & .\VellumUeAgent.exe install
    if ($LASTEXITCODE -ne 0) { throw "winsw install failed exit=$LASTEXITCODE" }
    & .\VellumUeAgent.exe start
    if ($LASTEXITCODE -ne 0) { throw "winsw start failed exit=$LASTEXITCODE" }
  } finally {
    Pop-Location
  }
  Write-Host "Service VellumUeAgent installed + started (Automatic delayed)."
}

# --- Logon task: warm Lookdev Worker ---
$taskWorker = "VellumLookdevWorkerEnsure"
if (-not $SkipLogonTask) {
  $action = New-ScheduledTaskAction `
    -Execute $Pwsh `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WorkerPs1`" -Ensure -LaunchGui -HostName $HostName" `
    -WorkingDirectory $RepoRoot
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
  Register-ScheduledTask -TaskName $taskWorker -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
  Write-Host "Scheduled Task '$taskWorker' registered (At logon, interactive)."
}

# --- Watchdog every 5 minutes: self-heal (git pull + Ensure + restart agent if code moved) ---
$taskWatch = "VellumLookdevWorkerWatchdog"
$HealPs1 = Join-Path $RepoRoot "tools\unreal\host-heal.ps1"
if (-not $SkipWatchdog) {
  if (-not (Test-Path $HealPs1)) { throw "Missing host-heal.ps1: $HealPs1" }
  $action = New-ScheduledTaskAction `
    -Execute $Pwsh `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$HealPs1`" -HostName $HostName -VellumBase $VellumBase -RestartAgentService" `
    -WorkingDirectory $RepoRoot
  $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
  Register-ScheduledTask -TaskName $taskWatch -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
  Write-Host "Scheduled Task '$taskWatch' registered (every 5 min host-heal)."
}

if ($StartWorkerNow) {
  Write-Host "Running host-heal now..."
  $HealPs1 = Join-Path $RepoRoot "tools\unreal\host-heal.ps1"
  & $Pwsh -NoProfile -ExecutionPolicy Bypass -File $HealPs1 -HostName $HostName -VellumBase $VellumBase
}

Write-Host ""
Write-Host "Done. Capture no longer depends on a parked PowerShell window."
Write-Host "  Service logs: $LogDir"
Write-Host "  Status: Get-Service VellumUeAgent ; Get-ScheduledTask VellumLookdev*"
Write-Host "  Health: Invoke-RestMethod http://127.0.0.1:8771/health"
Write-Host "  Uninstall: pwsh -File tools/unreal/host-install/uninstall.ps1"
