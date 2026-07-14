$ErrorActionPreference = 'Continue'
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and $_.CommandLine -match 'vellum_ue_agent\.ps1'
} | ForEach-Object {
  Write-Host "Stop $($_.ProcessId)"
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep 2
New-Item -ItemType Directory -Force -Path 'E:\Dev\vellum\tmp' | Out-Null
$out='E:\Dev\vellum\tmp\agent-out.log'; $err='E:\Dev\vellum\tmp\agent-err.log'
Remove-Item $out,$err -ErrorAction SilentlyContinue
Copy-Item -Force 'E:\Dev\vellum\tools\unreal\vellum_ue_worker_boot.py' 'F:\Games\AuroraVellum\Saved\VellumCapture\vellum_ue_worker_boot.py'
Start-Process pwsh -ArgumentList @(
  '-NoProfile','-ExecutionPolicy','Bypass',
  '-File','E:\Dev\vellum\tools\unreal\vellum_ue_agent.ps1',
  '-VellumBase','http://192.168.68.93:8770','-HostName','aurora','-UseLookdevWorker'
) -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden
Start-Sleep 15
Write-Host 'HEALTH'
try { (Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 5) | ConvertTo-Json -Compress } catch { $_.Exception.Message }
Write-Host 'AGENTS'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent\.ps1' } | ForEach-Object {
  Write-Host "$($_.ProcessId) $($_.CommandLine.Substring(0,[Math]::Min(180,$_.CommandLine.Length)))"
}
Write-Host 'OUT'; if (Test-Path $out) { Get-Content $out -Tail 25 }
Write-Host 'ERR'; if (Test-Path $err) { Get-Content $err -Tail 25 }
