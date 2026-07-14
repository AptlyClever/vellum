$ErrorActionPreference = 'Continue'
# Do not kill Unreal — worker is mid-author.
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and $_.CommandLine -match 'vellum_ue_agent\.ps1'
} | ForEach-Object {
  Write-Host "Stop agent $($_.ProcessId)"
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep 2
$out='E:\Dev\vellum\tmp\agent-out.log'; $err='E:\Dev\vellum\tmp\agent-err.log'
Remove-Item $out,$err -ErrorAction SilentlyContinue
Start-Process pwsh -ArgumentList @(
  '-NoProfile','-ExecutionPolicy','Bypass',
  '-File','E:\Dev\vellum\tools\unreal\vellum_ue_agent.ps1',
  '-VellumBase','http://192.168.68.93:8770','-HostName','aurora',
  '-UseLookdevWorker','-SkipHostHeal'
) -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden
Start-Sleep 8
Write-Host 'AGENTS'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent\.ps1' } | ForEach-Object {
  $role = if ($_.CommandLine -match 'SidecarOnly') { 'SIDECAR' } else { 'PRIMARY' }
  Write-Host "$role $($_.ProcessId)"
}
Write-Host 'HEALTH'
try { (Invoke-RestMethod http://127.0.0.1:8771/health) | ConvertTo-Json -Compress } catch { $_.Exception.Message }
Write-Host 'TAIL'
Get-Content $out -Tail 15 -ErrorAction SilentlyContinue
Get-Content $err -Tail 15 -ErrorAction SilentlyContinue
