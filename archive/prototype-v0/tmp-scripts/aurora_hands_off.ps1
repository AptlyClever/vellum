$ErrorActionPreference = 'Continue'
Write-Host '=== Unreal now ==='
Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("RUNNING {0} pid={1}" -f $_.ProcessName, $_.Id) }
if (-not (Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue)) {
  Write-Host 'No Unreal processes (you were kicked / editor closed)'
}

Write-Host '=== Vellum agents ==='
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and ($_.CommandLine -match 'vellum_ue_agent' -or $_.CommandLine -match 'run_vellum_capture' -or $_.CommandLine -match 'vellum_ue_worker')
} | ForEach-Object { Write-Host "KILL candidate $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host '=== Disable scheduled tasks that can bounce UE/agent ==='
foreach ($name in @(
  'VellumUeAgent',
  'VellumLookdevWorkerEnsure',
  'VellumUeAgentWatchdog',
  'VellumHostHeal',
  'VellumLookdevWorker'
)) {
  $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if ($t) {
    try {
      Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
      Disable-ScheduledTask -TaskName $name -ErrorAction Stop
      Write-Host "DISABLED $name"
    } catch {
      Write-Host "task $name : $($_.Exception.Message)"
    }
  } else {
    Write-Host "no task $name"
  }
}

Write-Host '=== List Vellum* tasks ==='
Get-ScheduledTask | Where-Object { $_.TaskName -match 'Vellum|UeAgent|Lookdev' } |
  ForEach-Object { Write-Host ("{0} State={1}" -f $_.TaskName, $_.State) }

Write-Host '=== DO NOT kill Unreal again — leave editor alone ==='
Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("LEAVE ALONE {0} pid={1}" -f $_.ProcessName, $_.Id) }
