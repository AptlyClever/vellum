$ErrorActionPreference='Continue'
Set-Location E:\Dev\vellum
Write-Host '=== kill UnrealEditor ==='
Get-Process UnrealEditor* -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host ("Stopping PID {0}" -f $_.Id)
  Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep 3
# Stage boot from repo (Ensure also stages, but be explicit)
$src='E:\Dev\vellum\tools\unreal\vellum_ue_worker_boot.py'
$dst='F:\Games\AuroraVellum\Saved\VellumCapture\vellum_ue_worker_boot.py'
New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
Copy-Item -Force $src $dst
Write-Host ("staged boot bytes={0}" -f (Get-Item $dst).Length)
Select-String -Path $dst -Pattern 'class _Handler' | ForEach-Object { Write-Host $_.Line }
Write-Host '=== Start-ScheduledTask Ensure ==='
Start-ScheduledTask -TaskName 'VellumLookdevWorkerEnsure'
# Poll up to 4 min
for ($i=0; $i -lt 24; $i++) {
  Start-Sleep 10
  $ue = @(Get-Process UnrealEditor* -ErrorAction SilentlyContinue)
  try {
    $h = Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 3
    Write-Host ("try={0} ue={1} health={2}" -f $i, $ue.Count, ($h | ConvertTo-Json -Compress))
    if ($h.ok) {
      Write-Host 'WORKER_HEALTHY'
      break
    }
  } catch {
    Write-Host ("try={0} ue={1} health_fail={2}" -f $i, $ue.Count, $_.Exception.Message)
  }
}
Write-Host '=== reinstall agent UseLookdevWorker ==='
& pwsh -NoProfile -File tools\unreal\host-install\install-agent-interactive.ps1 -HostName aurora -VellumBase http://192.168.68.93:8770 *>&1 | Out-String | Write-Host
Start-Sleep 4
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent' } | ForEach-Object { Write-Host $_.CommandLine }
