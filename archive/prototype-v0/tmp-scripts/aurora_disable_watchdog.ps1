$ErrorActionPreference = 'Continue'
Get-ScheduledTask | Where-Object { $_.TaskName -match 'Vellum' } | ForEach-Object {
  try {
    Stop-ScheduledTask -TaskName $_.TaskName -ErrorAction SilentlyContinue
    Disable-ScheduledTask -TaskName $_.TaskName -ErrorAction SilentlyContinue
    Write-Host "DISABLED $($_.TaskName) now=$($_.State)"
  } catch { Write-Host "fail $($_.TaskName): $_" }
}
# kill any heal/watchdog/agent leftover — NOT Unreal
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and (
    $_.CommandLine -match 'vellum_ue_agent' -or
    $_.CommandLine -match 'host-heal' -or
    $_.CommandLine -match 'vellum_ue_worker' -or
    $_.CommandLine -match 'run_vellum_capture' -or
    $_.CommandLine -match 'VellumLookdevWorker'
  )
} | ForEach-Object {
  Write-Host "Stop $($_.ProcessId) $($_.CommandLine.Substring(0,[Math]::Min(100,$_.CommandLine.Length)))"
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Host '=== tasks ==='
Get-ScheduledTask | Where-Object { $_.TaskName -match 'Vellum' } | ForEach-Object {
  Write-Host "$($_.TaskName) State=$($_.State)"
}
Write-Host '=== Unreal (untouched) ==='
Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host "still up $($_.Id)" }
if (-not (Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue)) {
  Write-Host 'Editor not running — safe for you to open AuroraVellum and Fab again'
}
