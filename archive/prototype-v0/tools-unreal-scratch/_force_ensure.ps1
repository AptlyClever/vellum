$ErrorActionPreference='Continue'
Set-Location E:\Dev\vellum
Get-Process UnrealEditor* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
# Stop stuck Ensure task instances
Get-ScheduledTask VellumLookdevWorkerEnsure -ErrorAction SilentlyContinue | Stop-ScheduledTask -ErrorAction SilentlyContinue
Start-Sleep 2
Copy-Item -Force E:\Dev\vellum\tools\unreal\vellum_ue_worker_boot.py F:\Games\AuroraVellum\Saved\VellumCapture\vellum_ue_worker_boot.py
Write-Host '=== direct Ensure (not Wait-only) ==='
& pwsh -NoProfile -File tools\unreal\vellum_ue_worker.ps1 -Ensure -HostName aurora *>&1 | Out-String | Write-Host
try { Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 5 | ConvertTo-Json -Compress } catch { "health=$($_.Exception.Message)" }
& pwsh -NoProfile -File tools\unreal\host-install\install-agent-interactive.ps1 -HostName aurora -VellumBase http://192.168.68.93:8770 *>&1 | Select-Object -Last 15
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent' } | ForEach-Object { $_.CommandLine }
