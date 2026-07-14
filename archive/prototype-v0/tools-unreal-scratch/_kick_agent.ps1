$ErrorActionPreference='Continue'
Stop-ScheduledTask -TaskName VellumUeAgent -ErrorAction SilentlyContinue
Start-Sleep 2
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 1
Start-ScheduledTask -TaskName VellumUeAgent
Start-Sleep 5
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent' } | ForEach-Object { $_.CommandLine }
Invoke-RestMethod http://127.0.0.1:8771/health | ConvertTo-Json -Compress
try { (Invoke-RestMethod http://192.168.68.93:8770/api/health).jobs_queued } catch { $_.Exception.Message }
