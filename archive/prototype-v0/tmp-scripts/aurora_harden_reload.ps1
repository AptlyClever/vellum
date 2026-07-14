$ErrorActionPreference = "Continue"
Write-Host "Stage lookdev-worker-6 into Saved/VellumCapture..."
Copy-Item -Force "E:\Dev\vellum\tools\unreal\vellum_ue_worker_boot.py" `
  "F:\Games\AuroraVellum\Saved\VellumCapture\vellum_ue_worker_boot.py"
Select-String -Path "F:\Games\AuroraVellum\Saved\VellumCapture\vellum_ue_worker_boot.py" `
  -Pattern "WORKER_VERSION" | Select-Object -First 1 | ForEach-Object { Write-Host $_.Line.Trim() }

Write-Host "Stop agents..."
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "vellum_ue_agent" } |
  ForEach-Object {
    Write-Host "Stop agent $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

Write-Host "Stop UnrealEditor (reload in-memory worker)..."
Get-Process UnrealEditor -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "Kill UE $($_.Id)"
  Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 10

Write-Host "Ensure worker..."
& "E:\Dev\vellum\tools\unreal\vellum_ue_worker.ps1" -Ensure -HostName aurora
$deadline = (Get-Date).AddMinutes(8)
do {
  Start-Sleep -Seconds 5
  try {
    $h = Invoke-RestMethod "http://127.0.0.1:8771/health" -TimeoutSec 5
    Write-Host ("health version={0} busy={1} map={2}" -f $h.version, $h.busy, $h.map)
    if ("$($h.version)" -match "lookdev-worker-6") { break }
  } catch {
    Write-Host "waiting worker: $($_.Exception.Message)"
  }
} while ((Get-Date) -lt $deadline)

Write-Host "Start primary agent (spawns SidecarOnly)..."
$out = "E:\Dev\vellum\tmp\agent-out.log"
$err = "E:\Dev\vellum\tmp\agent-err.log"
New-Item -ItemType Directory -Force -Path "E:\Dev\vellum\tmp" | Out-Null
Remove-Item $out, $err -ErrorAction SilentlyContinue
Start-Process -FilePath "pwsh" -ArgumentList @(
  "-NoProfile", "-ExecutionPolicy", "Bypass",
  "-File", "E:\Dev\vellum\tools\unreal\vellum_ue_agent.ps1",
  "-VellumBase", "http://192.168.68.93:8770",
  "-HostName", "aurora",
  "-UseLookdevWorker"
) -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden | Out-Null
Start-Sleep -Seconds 12

Write-Host "=== agents ==="
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "vellum_ue_agent" } |
  ForEach-Object {
    Write-Host "$($_.ProcessId) $($_.CommandLine.Substring(0,[Math]::Min(200,$_.CommandLine.Length)))"
  }
Write-Host "=== nvidia ==="
nvidia-smi --query-gpu=name,utilization.gpu,memory.used --format=csv,noheader
Write-Host "=== agent out tail ==="
if (Test-Path $out) { Get-Content $out -Tail 30 }
Write-Host "=== agent err tail ==="
if (Test-Path $err) { Get-Content $err -Tail 30 }
