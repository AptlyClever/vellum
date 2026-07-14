$ErrorActionPreference='Continue'
Set-Location E:\Dev\vellum
Get-Process UnrealEditor* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
try { Stop-ScheduledTask -TaskName VellumLookdevWorkerEnsure -ErrorAction SilentlyContinue } catch {}
Start-Sleep 2
Copy-Item -Force E:\Dev\vellum\tools\unreal\vellum_ue_worker_boot.py F:\Games\AuroraVellum\Saved\VellumCapture\vellum_ue_worker_boot.py
$Pwsh = 'C:\Program Files\PowerShell\7\pwsh.exe'
$WorkerPs1 = 'E:\Dev\vellum\tools\unreal\vellum_ue_worker.ps1'
$action = New-ScheduledTaskAction -Execute $Pwsh -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WorkerPs1`" -Ensure -LaunchGui -HostName aurora" -WorkingDirectory 'E:\Dev\vellum'
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Set-ScheduledTask -TaskName VellumLookdevWorkerEnsure -Action $action -Principal $principal | Out-Null
Write-Host '=== Start Ensure -LaunchGui ==='
Start-ScheduledTask -TaskName VellumLookdevWorkerEnsure
for ($i=0; $i -lt 36; $i++) {
  Start-Sleep 10
  $ue = @(Get-Process UnrealEditor* -ErrorAction SilentlyContinue)
  try {
    $h = Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 3
    Write-Host ("try={0} ue={1} {2}" -f $i,$ue.Count,($h|ConvertTo-Json -Compress))
    if ($h.ok) { Write-Host 'WORKER_HEALTHY'; break }
  } catch {
    Write-Host ("try={0} ue={1} fail={2}" -f $i,$ue.Count,$_.Exception.Message)
  }
}
Get-ScheduledTaskInfo VellumLookdevWorkerEnsure | Format-List LastRunTime,LastTaskResult | Out-String | Write-Host
& pwsh -NoProfile -File tools\unreal\host-install\install-agent-interactive.ps1 -HostName aurora -VellumBase http://192.168.68.93:8770 *>&1 | Select-Object -Last 12
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent' } | ForEach-Object { $_.CommandLine }
