$ErrorActionPreference = 'Continue'
Write-Host 'Stop agents...'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent\.ps1' } | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Host 'Stop warm UnrealEditor (Cmd needs clean project lock)...'
Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "Kill $($_.ProcessName) $($_.Id)"
  Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep 8
$out='E:\Dev\vellum\tmp\agent-out.log'; $err='E:\Dev\vellum\tmp\agent-err.log'
Remove-Item $out,$err -ErrorAction SilentlyContinue
# Default = Epic batch Cmd (no -UseLookdevWorker)
Start-Process pwsh -ArgumentList @(
  '-NoProfile','-ExecutionPolicy','Bypass',
  '-File','E:\Dev\vellum\tools\unreal\vellum_ue_agent.ps1',
  '-VellumBase','http://192.168.68.93:8770','-HostName','aurora',
  '-SkipHostHeal'
) -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden
Start-Sleep 12
Write-Host 'AGENTS'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent\.ps1' } | ForEach-Object {
  $role = if ($_.CommandLine -match 'SidecarOnly') { 'SIDECAR' } else { 'PRIMARY' }
  Write-Host "$role $($_.ProcessId)"
}
Write-Host 'OUT'
Get-Content $out -Tail 25 -ErrorAction SilentlyContinue
Write-Host 'ERR'
Get-Content $err -Tail 20 -ErrorAction SilentlyContinue
