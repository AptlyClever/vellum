$ErrorActionPreference='Continue'
Write-Host '=== health ==='
try { Invoke-RestMethod http://127.0.0.1:8771/health -TimeoutSec 3 | ConvertTo-Json -Compress } catch { "fail: $($_.Exception.Message)" }
Write-Host '=== listen 8771 ==='
Get-NetTCPConnection -LocalPort 8771 -ErrorAction SilentlyContinue | Format-Table State,OwningProcess -AutoSize | Out-String | Write-Host
Write-Host '=== unreal procs ==='
Get-CimInstance Win32_Process -Filter "Name='UnrealEditor.exe'" | ForEach-Object { Write-Host "PID=$($_.ProcessId)"; Write-Host $_.CommandLine }
Write-Host '=== ensure task ==='
Get-ScheduledTaskInfo VellumLookdevWorkerEnsure | Format-List LastRunTime,LastTaskResult | Out-String | Write-Host
$proj = 'F:\Games\AuroraVellum'
$logs = Get-ChildItem "$proj\Saved\Logs" -Filter '*.log' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Desc | Select-Object -First 3
Write-Host '=== recent logs ==='
$logs | ForEach-Object { Write-Host $_.FullName $_.LastWriteTime }
$latest = $logs | Select-Object -First 1
if ($latest) {
  Write-Host "=== grepping $($latest.Name) for vellum/python/8771/error ==="
  Select-String -Path $latest.FullName -Pattern 'vellum_ue_worker|8771|Python|ExecutePython|Traceback|Error:|Lookdev' -SimpleMatch:$false |
    Select-Object -Last 40 | ForEach-Object { $_.Line }
}
$out = "$proj\Saved\VellumCapture"
Write-Host "=== staged boot py ==="
Get-Item "$out\vellum_ue_worker_boot.py" -ErrorAction SilentlyContinue | Format-List FullName,Length,LastWriteTime | Out-String | Write-Host
