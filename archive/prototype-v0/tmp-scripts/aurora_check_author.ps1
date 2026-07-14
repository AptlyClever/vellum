$cap = "F:\Games\AuroraVellum\Saved\VellumCapture"
$j = Get-Content "$cap\author-result.json" -Raw | ConvertFrom-Json
Write-Host "ok=$($j.ok) jobs=$($j.jobs.Count) queue=$($j.queue_path)"
Write-Host "last notes:"
$j.notes | Select-Object -Last 20 | ForEach-Object { Write-Host "  $_" }
Write-Host "ground mrq dirs:"
Get-ChildItem "$cap\mrq" -Directory | Where-Object { $_.Name -match 'Chaos|Earth|Fire|Water|Metal|Explosion|Ground' } | ForEach-Object {
  $png = @(Get-ChildItem $_.FullName -Filter '*.png' -EA SilentlyContinue).Count
  Write-Host "  $($_.Name) png=$png mtime=$($_.LastWriteTime)"
}
Write-Host "agent:"
Get-Process -Id 35636 -EA SilentlyContinue | Format-List Id,CPU,WorkingSet64,StartTime
