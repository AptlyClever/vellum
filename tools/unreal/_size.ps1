$ErrorActionPreference = "Continue"
foreach ($n in @("Dark_Village", "FabricBundle", "Steampunk_Zepline_Station", "ContainerCity", "Garage")) {
  $p = "F:\Games\AuroraVellum\Content\$n"
  if (-not (Test-Path $p)) { Write-Host "$n MISSING"; continue }
  $m = Get-ChildItem $p -Recurse -File -EA SilentlyContinue | Measure-Object Length -Sum
  "{0}: {1:N2} GB, {2} files" -f $n, ($m.Sum / 1GB), $m.Count
}
Write-Host "--- stage dir ---"
Get-ChildItem "F:\Games\AuroraVellum\Saved\VellumStage" -EA SilentlyContinue | ForEach-Object {
  "{0} {1:N2} GB {2}" -f $_.Name, ($_.Length / 1GB), $_.LastWriteTime
}
Write-Host "--- procs ---"
Get-Process python*, UnrealEditor -EA SilentlyContinue | ForEach-Object {
  "$($_.Name) pid=$($_.Id) cpu=$([int]$_.CPU)"
}
