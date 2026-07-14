$ErrorActionPreference='Continue'
Write-Host 'agents:'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match 'vellum_ue_agent\.ps1' } | ForEach-Object { Write-Host $_.ProcessId $_.CommandLine.Substring(0,[Math]::Min(120,$_.CommandLine.Length)) }
Write-Host 'unreal:'
Get-Process Unreal* -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_.Id $_.ProcessName }
Write-Host 'capture dir logs:'
Get-ChildItem 'F:\Games\AuroraVellum\Saved\VellumCapture' -File -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 12 |
  ForEach-Object { Write-Host ("{0} {1} {2}" -f $_.LastWriteTime.ToString('HH:mm:ss'), $_.Length, $_.Name) }
Write-Host 'ue project logs:'
if (Test-Path 'F:\Games\AuroraVellum\Saved\Logs') {
  Get-ChildItem 'F:\Games\AuroraVellum\Saved\Logs' -Filter '*.log' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 5 |
    ForEach-Object { Write-Host ("{0} {1}" -f $_.LastWriteTime.ToString('HH:mm:ss'), $_.Name) }
}
Write-Host 'agent out live length:'
if (Test-Path 'E:\Dev\vellum\tmp\agent-out.log') {
  $f=Get-Item 'E:\Dev\vellum\tmp\agent-out.log'
  Write-Host $f.Length $f.LastWriteTime
  Get-Content $f.FullName -Tail 20
}
Write-Host 'inventory log tail if any:'
$inv = Get-ChildItem 'F:\Games\AuroraVellum\Saved\VellumCapture' -Filter '*ue-invent*' -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($inv) {
  Write-Host $inv.FullName
  Get-Content $inv.FullName -Tail 40
}
