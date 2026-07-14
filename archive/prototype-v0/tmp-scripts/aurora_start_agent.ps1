$out = "E:\Dev\vellum\tmp\agent-out.log"
$err = "E:\Dev\vellum\tmp\agent-err.log"
Remove-Item $out, $err -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "pwsh" -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", "E:\Dev\vellum\tools\unreal\vellum_ue_agent.ps1",
  "-VellumBase", "http://192.168.68.93:8770",
  "-HostName", "aurora",
  "-UseLookdevWorker"
) -PassThru -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden
Write-Host "started pid=$($p.Id)"
Start-Sleep -Seconds 8
$alive = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "vellum_ue_agent.ps1" }
if ($alive) {
  $alive | ForEach-Object { Write-Host "alive $($_.ProcessId)" }
} else {
  Write-Host "agent died"
}
Write-Host "=== ERR ==="
if (Test-Path $err) { Get-Content $err -Tail 50 }
Write-Host "=== OUT ==="
if (Test-Path $out) { Get-Content $out -Tail 50 }
