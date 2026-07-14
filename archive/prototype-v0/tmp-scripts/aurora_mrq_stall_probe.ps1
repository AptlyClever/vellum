Write-Host "=== health ==="
try {
  Invoke-RestMethod http://127.0.0.1:8765/health -TimeoutSec 5 | ConvertTo-Json -Compress
} catch { Write-Host "health FAIL: $($_.Exception.Message)" }

Write-Host "`n=== processes ==="
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'Unreal|pwsh' -or ($_.CommandLine -match 'vellum') } |
  ForEach-Object {
    $c = if ($_.CommandLine) { $_.CommandLine.Substring(0, [Math]::Min(160, $_.CommandLine.Length)) } else { $_.Name }
    Write-Host "$($_.ProcessId) $c"
  }

$base = "F:\Games\AuroraVellum\Saved\VellumCapture"
Write-Host "`n=== capture dirs ==="
if (Test-Path $base) {
  Get-ChildItem $base | ForEach-Object { Write-Host "$($_.LastWriteTime.ToString('s')) $($_.Name)" }
  foreach ($sub in @("worker-inbox","worker-outbox","mrq","logs")) {
    $p = Join-Path $base $sub
    if (Test-Path $p) {
      Write-Host "-- $sub --"
      Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 12 |
        ForEach-Object { Write-Host "$($_.LastWriteTime.ToString('s')) $($_.Length) $($_.FullName.Replace($base,''))" }
    }
  }
  foreach ($f in @(
    "worker-outbox\result.json",
    "author-ready.json",
    "worker-job.json",
    "worker-inbox\job.json"
  )) {
    $fp = Join-Path $base $f
    if (Test-Path $fp) {
      Write-Host "`nFILE $f ($((Get-Item $fp).Length) bytes, $((Get-Item $fp).LastWriteTime.ToString('s')))"
      Get-Content $fp -Raw -ErrorAction SilentlyContinue | Select-Object -First 1 | ForEach-Object { $_.Substring(0, [Math]::Min(800, $_.Length)) }
    } else { Write-Host "missing $f" }
  }
} else { Write-Host "missing $base" }

Write-Host "`n=== recent Lookdev/UE logs ==="
$logRoots = @(
  "F:\Games\AuroraVellum\Saved\Logs",
  "F:\Games\AuroraVellum\Saved\VellumCapture"
)
foreach ($lr in $logRoots) {
  if (Test-Path $lr) {
    Get-ChildItem $lr -File -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 8 |
      ForEach-Object { Write-Host "$($_.LastWriteTime.ToString('s')) $($_.Length) $($_.Name)" }
  }
}
