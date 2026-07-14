$ErrorActionPreference = 'Continue'
Write-Host 'Stopping Vellum agents...'
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and ($_.CommandLine -match 'vellum_ue_agent\.ps1' -or $_.CommandLine -match 'run_vellum_capture\.ps1')
} | ForEach-Object {
  Write-Host "Stop pid=$($_.ProcessId)"
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Host 'Stopping UnrealEditor / UnrealEditor-Cmd...'
Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "Kill $($_.ProcessName) $($_.Id)"
  Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep 3
Write-Host '=== leftover ==='
$left = @()
Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue | ForEach-Object { $left += $_.ProcessName }
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent\.ps1' } | ForEach-Object { $left += "agent:$($_.ProcessId)" }
if ($left.Count -eq 0) { Write-Host 'CLEAR — no Unreal, no Vellum agent' } else { Write-Host ($left -join ', ') }
