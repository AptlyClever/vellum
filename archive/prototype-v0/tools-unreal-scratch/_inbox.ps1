$base='F:\Games\AuroraVellum\Saved\VellumCapture'
Write-Host '=== inbox ==='
Get-ChildItem "$base\worker-inbox" -ErrorAction SilentlyContinue | Format-Table Name,Length,LastWriteTime
if (Test-Path "$base\worker-inbox\job.json") { Get-Content "$base\worker-inbox\job.json" -Raw | Select-Object -First 1 }
Write-Host '=== outbox ==='
Get-ChildItem "$base\worker-outbox" -ErrorAction SilentlyContinue | Format-Table Name,Length,LastWriteTime
if (Test-Path "$base\worker-outbox\result.json") { Get-Content "$base\worker-outbox\result.json" -Raw | Select-Object -First 500 }
Write-Host '=== health ==='
Invoke-RestMethod http://127.0.0.1:8771/health | ConvertTo-Json -Compress
Write-Host '=== recent VellumWorker log lines ==='
$log = Get-ChildItem 'F:\Games\AuroraVellum\Saved\Logs\AuroraVellum.log' | Sort-Object LastWriteTime -Desc | Select-Object -First 1
Select-String -Path $log.FullName -Pattern 'VellumWorker' | Select-Object -Last 30 | ForEach-Object { $_.Line }
