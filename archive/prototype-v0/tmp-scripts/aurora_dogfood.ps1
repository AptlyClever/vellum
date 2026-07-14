$ErrorActionPreference = 'Continue'
Write-Host '=== health 8771 ==='
try { (Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 5) | ConvertTo-Json -Compress } catch { Write-Host $_.Exception.Message }

$cap = 'F:\Games\AuroraVellum\Saved\VellumCapture'
Write-Host "author-ready=$(Test-Path $cap\author-ready.json) author-result=$(Test-Path $cap\author-result.json)"
if (Test-Path $cap\author-result.json) {
  $j = Get-Content $cap\author-result.json -Raw | ConvertFrom-Json
  Write-Host "author-result ok=$($j.ok) jobs=$($j.jobs.Count) mtime=$((Get-Item $cap\author-result.json).LastWriteTime)"
}
if (Test-Path $cap\author-ready.json) {
  Write-Host "author-ready mtime=$((Get-Item $cap\author-ready.json).LastWriteTime) bytes=$((Get-Item $cap\author-ready.json).Length)"
}
Write-Host '=== outbox ==='
Get-ChildItem "$cap\worker-outbox" -EA SilentlyContinue | ForEach-Object { "$($_.LastWriteTime) $($_.Length) $($_.Name)" }
if (Test-Path "$cap\worker-outbox\result.json") {
  Get-Content "$cap\worker-outbox\result.json" -Raw
}
Write-Host '=== ground png ==='
Get-ChildItem "$cap\mrq" -Directory -EA SilentlyContinue | Where-Object { $_.Name -match 'Chaos|Earth|Flame|Lightning|Magma' } | ForEach-Object {
  $n = @(Get-ChildItem $_.FullName -Filter *.png -EA SilentlyContinue).Count
  "$($_.Name) png=$n mtime=$($_.LastWriteTime)"
}
Write-Host '=== agents ==='
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent' } | ForEach-Object { $_.ProcessId }
Write-Host '=== worker boot hash on disk ==='
Get-FileHash "$cap\vellum_ue_worker_boot.py" -Algorithm SHA256 | Select-Object Hash
Get-FileHash 'E:\Dev\vellum\tools\unreal\vellum_ue_worker_boot.py' -Algorithm SHA256 | Select-Object Hash
Select-String -Path "$cap\vellum_ue_worker_boot.py" -Pattern 'author-result.json' | Select-Object -First 3 Line
