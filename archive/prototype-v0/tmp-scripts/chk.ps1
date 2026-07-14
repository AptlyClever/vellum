Write-Host 'PROCESSES'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -match 'vellum_ue_agent') } | ForEach-Object {
  Write-Host ("{0} | {1}" -f $_.ProcessId, $_.CommandLine.Substring(0,[Math]::Min(220,$_.CommandLine.Length)))
}
Write-Host 'HEALTH'
try { Invoke-RestMethod http://127.0.0.1:8771/health | ConvertTo-Json -Compress } catch { $_.Exception.Message }
Write-Host 'OUT'
if (Test-Path E:\Dev\vellum\tmp\agent-out.log) { Get-Content E:\Dev\vellum\tmp\agent-out.log -Tail 40 }
Write-Host 'ERR'
if (Test-Path E:\Dev\vellum\tmp\agent-err.log) { Get-Content E:\Dev\vellum\tmp\agent-err.log -Tail 40 }
