$ErrorActionPreference = 'Continue'
Set-Location E:\Dev\vellum
Write-Host '=== ensure worker ==='
& pwsh -NoProfile -File tools\unreal\vellum_ue_worker.ps1 -Ensure *>&1 | Out-String | Write-Host
Write-Host '=== wait health ==='
$ok = $false
for ($i = 0; $i -lt 24; $i++) {
  Start-Sleep -Seconds 10
  try {
    $h = Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 5
    Write-Host ("health try={0} {1}" -f $i, ($h | ConvertTo-Json -Compress))
    if ($h.ok) { $ok = $true; break }
  } catch {
    Write-Host ("health try={0} fail={1}" -f $i, $_.Exception.Message)
  }
}
Write-Host ("worker_ok={0}" -f $ok)
Write-Host '=== reinstall agent ==='
& pwsh -NoProfile -File tools\unreal\host-install\install-agent-interactive.ps1 -HostName aurora -VellumBase http://192.168.68.93:8770 *>&1 | Out-String | Write-Host
Start-Sleep 5
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent' } | ForEach-Object { Write-Host $_.CommandLine }
Get-Process UnrealEditor*, pwsh -ErrorAction SilentlyContinue | Format-Table ProcessName, Id -AutoSize | Out-String | Write-Host
