Write-Host "Stopping UnrealEditor..."
Get-Process UnrealEditor -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "Kill $($_.Id)"
  Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 8
Write-Host "Ensure worker ForceStudio..."
& "E:\Dev\vellum\tools\unreal\vellum_ue_worker.ps1" -Ensure -HostName aurora -ForceStudio
Write-Host "Health:"
try {
  (Invoke-RestMethod "http://127.0.0.1:8771/health" -TimeoutSec 10) | ConvertTo-Json -Compress
} catch {
  Write-Host $_.Exception.Message
}
Write-Host "Agents:"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "vellum_ue_agent" } | ForEach-Object {
  Write-Host $_.ProcessId
}
if (-not (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "vellum_ue_agent" })) {
  Start-Process pwsh -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-WindowStyle","Hidden","-File","E:\Dev\vellum\tools\unreal\vellum_ue_agent.ps1","-VellumBase","http://192.168.68.93:8770","-HostName","aurora","-UseLookdevWorker" -WindowStyle Hidden
  Start-Sleep 2
  Write-Host "started agent"
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "vellum_ue_agent" } | ForEach-Object { Write-Host $_.ProcessId }
}
