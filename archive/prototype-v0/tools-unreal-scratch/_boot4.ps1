$ErrorActionPreference='Continue'
Set-Location E:\Dev\vellum
# Fail current hanging agent wait by removing stale inbox after kill? Keep job - agent may still poll.
Get-Process UnrealEditor* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
try { Stop-ScheduledTask VellumLookdevWorkerEnsure -EA SilentlyContinue } catch {}
Start-Sleep 3
Copy-Item -Force E:\Dev\vellum\tools\unreal\vellum_ue_worker_boot.py F:\Games\AuroraVellum\Saved\VellumCapture\vellum_ue_worker_boot.py
# clear stuck outbox/inbox from deadlocked worker
Remove-Item -Force F:\Games\AuroraVellum\Saved\VellumCapture\worker-inbox\job.json -EA SilentlyContinue
Remove-Item -Force F:\Games\AuroraVellum\Saved\VellumCapture\worker-outbox\result.json -EA SilentlyContinue
$Pwsh='C:\Program Files\PowerShell\7\pwsh.exe'
$WorkerPs1='E:\Dev\vellum\tools\unreal\vellum_ue_worker.ps1'
$action=New-ScheduledTaskAction -Execute $Pwsh -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WorkerPs1`" -Ensure -LaunchGui -HostName aurora" -WorkingDirectory 'E:\Dev\vellum'
$principal=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Set-ScheduledTask -TaskName VellumLookdevWorkerEnsure -Action $action -Principal $principal | Out-Null
Start-ScheduledTask VellumLookdevWorkerEnsure
for ($i=0;$i -lt 24;$i++){
  Start-Sleep 8
  try {
    $h=Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 3
    Write-Host ("try={0} {1}" -f $i,($h|ConvertTo-Json -Compress))
    if ($h.ok -and $h.version -match 'lookdev-worker-4') {
      Start-Sleep 5
      $h2=Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 3
      Write-Host ("tick_check {0}" -f ($h2|ConvertTo-Json -Compress))
      if ([int]$h2.tick_count -gt [int]$h.tick_count) { Write-Host 'TICKS_ADVANCING'; break }
      else { Write-Host 'ticks_stalled_retry_wait' }
    }
  } catch { Write-Host ("try={0} fail={1}" -f $i,$_.Exception.Message) }
}
# bounce agent
Stop-ScheduledTask VellumUeAgent -EA SilentlyContinue
Start-Sleep 2
Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'vellum_ue_agent' } | % { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
Start-Sleep 1
Start-ScheduledTask VellumUeAgent
Start-Sleep 4
Write-Host 'agent restarted'
