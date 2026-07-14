$ErrorActionPreference='Continue'
Write-Host '=== unreal ==='
Get-CimInstance Win32_Process -Filter "Name='UnrealEditor.exe'" | ForEach-Object { "PID=$($_.ProcessId)"; $_.CommandLine }
Write-Host '=== listen ==='
netstat -ano | findstr :8771
Write-Host '=== latest log vellum/error ==='
$latest = Get-ChildItem 'F:\Games\AuroraVellum\Saved\Logs\*.log' | Sort-Object LastWriteTime -Desc | Select-Object -First 1
Write-Host $latest.FullName $latest.LastWriteTime
Select-String -Path $latest.FullName -Pattern 'VellumWorker|NameError|_Handler|Traceback|listening|http_background|Error: Python' |
  Select-Object -Last 50 | ForEach-Object { $_.Line }
Write-Host '=== class _Handler in staged ==='
Select-String -Path 'F:\Games\AuroraVellum\Saved\VellumCapture\vellum_ue_worker_boot.py' -Pattern 'class _Handler|def main'
Write-Host '=== env note: worker-ready ==='
Get-Content 'F:\Games\AuroraVellum\Saved\VellumCapture\worker-ready.json' -ErrorAction SilentlyContinue
