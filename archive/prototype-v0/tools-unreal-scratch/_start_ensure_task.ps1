$ErrorActionPreference = 'Continue'
Write-Host ("SESSIONNAME={0}" -f $env:SESSIONNAME)
Write-Host ("UserInteractive={0}" -f [Environment]::UserInteractive)
Write-Host ("USERNAME={0}" -f $env:USERNAME)
Get-ScheduledTask -TaskName 'VellumLookdevWorkerEnsure','VellumLookdevWorkerWatchdog' -ErrorAction SilentlyContinue |
  Format-Table TaskName, State -AutoSize | Out-String | Write-Host
$t = Get-ScheduledTask -TaskName 'VellumLookdevWorkerEnsure' -ErrorAction SilentlyContinue
if ($t) {
  Write-Host 'Actions:'
  $t.Actions | ForEach-Object { Write-Host ("  {0} {1}" -f $_.Execute, $_.Arguments) }
  Write-Host '=== Start-ScheduledTask VellumLookdevWorkerEnsure ==='
  Start-ScheduledTask -TaskName 'VellumLookdevWorkerEnsure'
  Start-Sleep 8
  Get-ScheduledTaskInfo -TaskName 'VellumLookdevWorkerEnsure' |
    Format-List LastRunTime, LastTaskResult | Out-String | Write-Host
}
Write-Host '=== processes ==='
Get-Process UnrealEditor*, pwsh -ErrorAction SilentlyContinue |
  Format-Table ProcessName, Id -AutoSize | Out-String | Write-Host
Write-Host '=== poll health 3 min ==='
for ($i = 0; $i -lt 18; $i++) {
  try {
    $h = Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 5
    Write-Host ("health try={0} {1}" -f $i, ($h | ConvertTo-Json -Compress))
    if ($h.ok) { break }
  } catch {
    Write-Host ("health try={0} fail={1}" -f $i, $_.Exception.Message)
  }
  Start-Sleep 10
}
