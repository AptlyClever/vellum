$log = 'F:\Games\AuroraVellum\Saved\Logs\AuroraVellum.log'
Write-Host '=== boot/tick/capture lines ==='
Select-String -Path $log -Pattern 'VellumWorker.*(tick|boot|inbox|capture|listening|http_background|Error)|NameError|_Handler' |
  Select-Object -Last 80 | ForEach-Object { $_.Line }
Write-Host '=== UE env VELLUM ==='
$p = Get-CimInstance Win32_Process -Filter "Name='UnrealEditor.exe'" | Select-Object -First 1
if ($p) {
  # Get env via wmi commandline only
  Write-Host $p.CommandLine
}
Write-Host '=== worker-ready ==='
Get-Content 'F:\Games\AuroraVellum\Saved\VellumCapture\worker-ready.json' -ErrorAction SilentlyContinue
# What path does Python think? Drop a probe via ensure won't work.
# List all worker-inbox anywhere under Saved
Get-ChildItem 'F:\Games\AuroraVellum\Saved' -Recurse -Filter 'job.json' -ErrorAction SilentlyContinue |
  Select-Object FullName,Length,LastWriteTime | Format-Table -AutoSize
