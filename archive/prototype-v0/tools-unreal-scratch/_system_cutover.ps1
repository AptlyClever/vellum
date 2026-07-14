$ErrorActionPreference = 'Continue'
Set-Location E:\Dev\vellum

Write-Host '=== Stage + Ensure Lookdev Worker (init_unreal hosting) ==='
Get-Process UnrealEditor* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
try { Stop-ScheduledTask -TaskName VellumLookdevWorkerEnsure -ErrorAction SilentlyContinue } catch {}
Start-Sleep 3

$Pwsh = 'C:\Program Files\PowerShell\7\pwsh.exe'
$WorkerPs1 = 'E:\Dev\vellum\tools\unreal\vellum_ue_worker.ps1'
$action = New-ScheduledTaskAction `
  -Execute $Pwsh `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WorkerPs1`" -Ensure -LaunchGui -HostName aurora" `
  -WorkingDirectory 'E:\Dev\vellum'
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Set-ScheduledTask -TaskName VellumLookdevWorkerEnsure -Action $action -Principal $principal | Out-Null

Start-ScheduledTask -TaskName VellumLookdevWorkerEnsure

$ok = $false
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep 8
  try {
    $a = Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 3
    Start-Sleep 3
    $b = Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 3
    Write-Host ("try={0} v={1} ticks={2}->{3} init={4}" -f $i, $b.version, $a.tick_count, $b.tick_count, (Test-Path 'F:\Games\AuroraVellum\Content\Python\init_unreal.py'))
    if ($b.ok -and $b.version -match 'lookdev-worker-5' -and [int]$b.tick_count -gt [int]$a.tick_count -and [int]$b.tick_count -ge 5) {
      Write-Host 'PUMP_OK'
      $ok = $true
      break
    }
  } catch {
    Write-Host ("try={0} fail={1}" -f $i, $_.Exception.Message)
  }
}

if (-not $ok) { Write-Host 'PUMP_FAILED'; exit 1 }

& pwsh -NoProfile -File tools\unreal\host-install\install-agent-interactive.ps1 -HostName aurora -VellumBase http://192.168.68.93:8770 *>&1 | Select-Object -Last 12
Write-Host 'SYSTEM_CUTOVER_OK'
