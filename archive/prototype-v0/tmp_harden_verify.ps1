$ErrorActionPreference = 'Continue'
Write-Host '=== boot versions ==='
@(
  'E:\Dev\vellum\tools\unreal\vellum_ue_worker_boot.py',
  'F:\Games\AuroraVellum\Saved\VellumCapture\vellum_ue_worker_boot.py'
) | ForEach-Object {
  if (Test-Path $_) {
    $m = Select-String -Path $_ -Pattern 'WORKER_VERSION' | Select-Object -First 1
    Write-Host "$_ -> $($m.Line.Trim())"
  } else { Write-Host "MISSING $_" }
}
Write-Host '=== agent SidecarOnly present ==='
(Select-String -Path 'E:\Dev\vellum\tools\unreal\vellum_ue_agent.ps1' -Pattern 'SidecarOnly').Count
Write-Host '=== agent processes ==='
Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'pwsh|powershell' -and $_.CommandLine -match 'vellum_ue_agent' } | ForEach-Object {
  Write-Host "$($_.ProcessId) $($_.CommandLine.Substring(0,[Math]::Min(180,$_.CommandLine.Length)))"
}
Write-Host '=== health ==='
try { Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 5 | ConvertTo-Json -Compress } catch { Write-Host $_.Exception.Message }
Write-Host '=== nvidia ==='
try { nvidia-smi --query-gpu=name,utilization.gpu,memory.used --format=csv,noheader } catch { Write-Host $_.Exception.Message }
