$ErrorActionPreference='Continue'
$latest = Get-ChildItem 'F:\Games\AuroraVellum\Saved\Logs\AuroraVellum*.log' | Sort-Object LastWriteTime -Desc | Select-Object -First 5
$latest | ForEach-Object { Write-Host ("FILE {0} {1} {2}KB" -f $_.Name, $_.LastWriteTime, [int]($_.Length/1KB)) }
$log = ($latest | Select-Object -First 1).FullName
Write-Host "=== tail $log ==="
Get-Content $log -Tail 80
Write-Host '=== all VellumWorker / Python Error in this log ==='
Select-String -Path $log -Pattern 'VellumWorker|LogPython: Error|ExecutePython|Critical|Fatal|shutdown' | Select-Object -Last 60 | ForEach-Object { $_.Line }
