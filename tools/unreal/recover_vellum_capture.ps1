#Requires -Version 5.1
<#
.SYNOPSIS
  Recover interrupted MRQ captures: pick heroes from on-disk sequences and ingest.

.DESCRIPTION
  Reads F:\Games\AuroraVellum\Saved\VellumCapture\mrq\<system>\ (via host profile),
  rejects pure-black sequences, copies heroes to stills\, POSTs ingest-render +
  ingest-sequence to slots + hail-overlay. No Unreal launch.

.EXAMPLE
  pwsh -File tools/unreal/recover_vellum_capture.ps1
#>
param(
  [string]$AssetId = "fireworks-vol-1-niagara",
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$HostName = "",
  [string]$Project = "",
  [int]$MinFrames = 30,
  [int]$MinRgb = 8,
  [string[]]$Systems = @(),  # empty = all dirs under mrq/ with enough PNGs
  [switch]$Force = $(
    if ($env:VELLUM_FORCE_CAPTURE -match '^(1|true|yes)$') { $true } else { $false }
  )
)

$ErrorActionPreference = "Stop"

function Invoke-ExeQuiet {
  # Temp .bat + EnableDelayedExpansion — never `echo %ERRORLEVEL%` in cmd /c one-liner.
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string[]]$ArgumentList,
    [int]$TimeoutSec = 180,
    [switch]$CaptureStdoutToTemp
  )
  $stamp = [guid]::NewGuid().ToString("n")
  $ecFile = Join-Path $env:TEMP "vellum-exe-$stamp-ec.txt"
  $outFile = Join-Path $env:TEMP "vellum-exe-$stamp-out.txt"
  $errFile = Join-Path $env:TEMP "vellum-exe-$stamp-err.txt"
  $batFile = Join-Path $env:TEMP "vellum-exe-$stamp.bat"
  $exe = [string]$FilePath
  $argLine = @(
    foreach ($a in $ArgumentList) {
      $s = [string]$a
      if ($s -match '[\s"^&|<>%]') { '"' + ($s -replace '"', '""') + '"' } else { $s }
    }
  ) -join ' '
  if ($exe -match '[\s"]') { $exe = '"' + ($exe -replace '"', '""') + '"' }
  $lines = New-Object System.Collections.Generic.List[string]
  [void]$lines.Add("@echo off")
  [void]$lines.Add("setlocal EnableDelayedExpansion")
  if ($CaptureStdoutToTemp -and $argLine -notmatch '(^|\s)(-o|--output)(\s|$)') {
    [void]$lines.Add("$exe -o `"$outFile`" $argLine 2>`"$errFile`"")
  } else {
    [void]$lines.Add("$exe $argLine >`"$outFile`" 2>`"$errFile`"")
  }
  [void]$lines.Add("echo !ERRORLEVEL!>`"$ecFile`"")
  [void]$lines.Add("endlocal")
  Set-Content -LiteralPath $batFile -Value $lines -Encoding Ascii
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "cmd.exe"
  $psi.Arguments = "/c `"$batFile`""
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.RedirectStandardInput = $false
  $psi.RedirectStandardOutput = $false
  $psi.RedirectStandardError = $false
  $p = New-Object System.Diagnostics.Process
  $p.StartInfo = $psi
  try {
    [void]$p.Start()
    $waitMs = [Math]::Max(5000, $TimeoutSec * 1000)
    if (-not $p.WaitForExit($waitMs)) {
      try { $p.Kill($true) } catch { try { $p.Kill() } catch {} }
      return 124
    }
  } finally {
    try { $p.Close() } catch {}
  }
  $exitCode = 1
  if (Test-Path $ecFile) {
    $raw = (Get-Content -LiteralPath $ecFile -Raw -ErrorAction SilentlyContinue | ForEach-Object { $_.Trim() })
    if ($raw -match '^-?\d+$') { $exitCode = [int]$raw }
  }
  Remove-Item -Force $ecFile, $outFile, $errFile, $batFile -ErrorAction SilentlyContinue
  return $exitCode
}

function Find-VellumPython {
  $candidates = @()
  if ($env:VELLUM_PYTHON) { $candidates += $env:VELLUM_PYTHON }
  $candidates += @(
    "C:\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Program Files\Python312\python.exe"
  )
  foreach ($cmdName in @("python", "py")) {
    $cmd = Get-Command $cmdName -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $candidates += $cmd.Source }
  }
  foreach ($c in $candidates) {
    if (-not $c) { continue }
    if ($c -like "*\WindowsApps\*") { continue }
    if (-not (Test-Path -LiteralPath $c)) { continue }
    if ((Get-Item -LiteralPath $c).Length -lt 1024) { continue }
    return $c
  }
  throw "No real Python found. Install with: choco install python312 -y"
}

. (Join-Path $PSScriptRoot "ue-hosts.ps1")
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$UeHost = Get-UeHostProfile -RepoRoot $RepoRoot -HostName $HostName
if (-not $Project) { $Project = Resolve-UprojectFromHost -HostProfile $UeHost }
if (-not (Test-Path $Project)) { throw "Project not found: $Project" }

$PickHeroesPy = Join-Path $PSScriptRoot "pick_heroes.py"
if (-not (Test-Path $PickHeroesPy)) { throw "pick_heroes.py missing" }

$ProjectDir = Split-Path $Project -Parent
$OutDir = Join-Path $ProjectDir "Saved\VellumCapture"
$MrqRoot = Join-Path $OutDir "mrq"
$StillsDir = Join-Path $OutDir "stills"
New-Item -ItemType Directory -Force -Path $StillsDir | Out-Null

function Safe-Name([string]$Name) {
  return -join ($Name.ToCharArray() | ForEach-Object { if ($_ -match "[A-Za-z0-9_-]") { $_ } else { "_" } })
}

function Get-ImageCount([string]$Root) {
  if (-not (Test-Path $Root)) { return 0 }
  return @(Get-ChildItem -Path $Root -Recurse -File -Filter "*.png" -ErrorAction SilentlyContinue).Count
}

function Get-LookdevOutputs {
  param([string]$VellumBase, [string]$AssetId)
  try {
    $r = Invoke-RestMethod -Method Get -Uri "$VellumBase/api/lookdev/outputs?asset_id=$AssetId" -TimeoutSec 45
    if ($r.outputs) { return @($r.outputs) }
  } catch {
    Write-Host "WARNING: lookdev outputs fetch failed: $($_.Exception.Message)"
  }
  return @()
}

function Test-VaultHasSystemLookdev {
  param(
    [object[]]$Outputs,
    [string]$SystemName,
    [string[]]$Lanes
  )
  foreach ($laneName in $Lanes) {
    $hits = @($Outputs | Where-Object {
        $_.kind -eq "niagara-render" -and
        [string]$_.lane -eq $laneName -and (
          ([string]$_.path -like "*$SystemName*") -or
          ([string]$_.note -like "*$SystemName*")
        )
      })
    if ($hits.Count -eq 0) { return $false }
  }
  return $true
}

$IngestLanes = @("slots", "hail-overlay")
$vaultOutputs = @()
if (-not $Force) {
  $vaultOutputs = Get-LookdevOutputs -VellumBase $VellumBase -AssetId $AssetId
  Write-Host "Recover skip check: vault outputs=$(@($vaultOutputs).Count) force=$Force"
}

$pyExe = Find-VellumPython
Write-Host "Using Python: $pyExe"

if (-not (Test-Path $MrqRoot)) {
  throw "No MRQ output root at $MrqRoot - nothing to recover"
}

$dirs = @()
if ($Systems.Count -gt 0) {
  foreach ($s in $Systems) {
    $d = Join-Path $MrqRoot (Safe-Name $s)
    if (Test-Path $d) { $dirs += Get-Item $d }
  }
} else {
  $dirs = @(Get-ChildItem -Path $MrqRoot -Directory -ErrorAction SilentlyContinue)
}

# Prefer freshest _Single shells; skip stale _Loop dirs when a Single sibling exists.
# Alphabetical listing hit old pure-black Loop first and looked like a total failure.
$singleNames = @{}
foreach ($d in $dirs) {
  if ($d.Name -match '_Single$') { $singleNames[$d.Name] = $true }
}
$filtered = New-Object System.Collections.ArrayList
foreach ($d in $dirs) {
  if ($d.Name -match '^(.*)_Loop$' ) {
    $singleSibling = $Matches[1] + "_Single"
    if ($singleNames.ContainsKey($singleSibling)) {
      Write-Host "IGNORE $($d.Name) (stale loop; sibling $singleSibling present)"
      continue
    }
  }
  [void]$filtered.Add($d)
}
$dirs = @($filtered | Sort-Object {
    $n = $_.Name
    $pri = if ($n -match '_Single$') { 0 } else { 1 }
    "{0}-{1:yyyyMMddHHmmss}-{2}" -f $pri, $_.LastWriteTimeUtc, $n
  })

$report = [ordered]@{
  schema_version = 1
  tool           = "recover_vellum_capture"
  asset_id       = $AssetId
  project_dir    = $ProjectDir
  mrq_root       = $MrqRoot
  systems        = (New-Object System.Collections.ArrayList)
  ingested       = (New-Object System.Collections.ArrayList)
  skipped        = (New-Object System.Collections.ArrayList)
  errors         = (New-Object System.Collections.ArrayList)
  ok             = $false
}

Write-Host "Recover MRQ capture under $MrqRoot"
Write-Host "Candidate systems (after loop filter): $($dirs.Count)"
foreach ($d in $dirs) {
  Write-Host "  - $($d.Name)  frames=$(Get-ImageCount $d.FullName)  mtime=$($d.LastWriteTime)"
}

foreach ($dir in $dirs) {
  $systemName = $dir.Name
  $frames = Get-ImageCount $dir.FullName
  $entry = [ordered]@{
    system = $systemName
    path   = $dir.FullName
    frames = $frames
  }
  if (-not $Force -and (Test-VaultHasSystemLookdev -Outputs $vaultOutputs -SystemName $systemName -Lanes $IngestLanes)) {
    $entry.skip = "vault_covered"
    [void]$report.skipped.Add($entry)
    Write-Host "SKIP $systemName vault already has lookdev on $($IngestLanes -join '+')"
    continue
  }
  if ($frames -lt $MinFrames) {
    $entry.skip = "too_few_frames:$frames"
    [void]$report.skipped.Add($entry)
    Write-Host "SKIP $systemName frames=$frames (need >= $MinFrames)"
    continue
  }

  $HeroJson = Join-Path $OutDir "heroes-recover-$systemName.json"
  $resultJson = Join-Path $OutDir "ingest-result-recover-$systemName.json"
  if (Test-Path $resultJson) { Remove-Item -Force $resultJson -ErrorAction SilentlyContinue }
  $IngestPy = Join-Path $PSScriptRoot "ingest_mrq_system.py"
  if (-not (Test-Path $IngestPy)) { throw "ingest_mrq_system.py missing" }
  $ingestArgs = @(
    $IngestPy,
    "--vellum-base", $VellumBase,
    "--asset-id", $AssetId,
    "--system-name", $systemName,
    "--seq-dir", $dir.FullName,
    "--out-dir", $OutDir,
    "--stills-dir", $StillsDir,
    "--lanes", "slots,hail-overlay",
    "--heroes-json", $HeroJson,
    "--result-json", $resultJson,
    "--note-prefix", "recover MRQ",
    "--min-rgb", "$MinRgb",
    "--score-budget", "8"
  )
  Write-Host "Python ingest $systemName"
  $ec = Invoke-ExeQuiet -FilePath $pyExe -ArgumentList $ingestArgs -TimeoutSec 960
  if (-not (Test-Path $resultJson)) {
    $entry.skip = "ingest_no_result"
    [void]$report.skipped.Add($entry)
    Write-Host "SKIP $systemName ingest_no_result exit=$ec"
    continue
  }
  $doc = Get-Content $resultJson -Raw | ConvertFrom-Json
  $entry.peak_rgb = 0
  $entry.hero_ok = [bool]$doc.ok -or ([int]$doc.uploaded -gt 0)
  $entry.uploaded = [int]$doc.uploaded
  if (-not $entry.hero_ok) {
    $errJoin = (@($doc.errors) -join ";")
    if ($errJoin -match "still_pure_black|no_frames") {
      $entry.skip = $errJoin
      [void]$report.skipped.Add($entry)
      Write-Host "SKIP $systemName $errJoin"
      continue
    }
    [void]$report.errors.Add("ingest_failed:$systemName`:$errJoin")
    Write-Host "FAIL $systemName $errJoin"
    continue
  }
  $entry.heroes = @($doc.heroes)
  [void]$report.systems.Add($entry)
  [void]$report.ingested.Add(@{
      kind = "python_ingest"
      system = $systemName
      uploaded = [int]$doc.uploaded
      lanes = @("slots", "hail-overlay")
    })
  Write-Host "Ingested $systemName uploaded=$($doc.uploaded)"
}

$okSystems = @($report.systems).Count
$report.ok = ($okSystems -gt 0 -and $report.errors.Count -eq 0)
$notes = "recover(mrq-sequencer) systems_ok=$okSystems skipped=$(@($report.skipped).Count) ingested=$(@($report.ingested).Count)"
$scratchBody = @{
  asset_id             = $AssetId
  scratch_project_path = $ProjectDir
  engine_version       = $(if ($UeHost.engine_version) { $UeHost.engine_version } else { "5.8" })
  notes                = $notes
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$VellumBase/api/scratch/record" `
  -ContentType "application/json" -Body $scratchBody | Out-Null

$ReportPath = Join-Path $OutDir "recover-report.json"
($report | ConvertTo-Json -Depth 8) | Set-Content -Path $ReportPath -Encoding utf8
Write-Host "Wrote $ReportPath"
Write-Host "Recover done ok=$($report.ok) systems=$okSystems ingested=$(@($report.ingested).Count) skipped=$(@($report.skipped).Count)"
if (-not $report.ok) { exit 2 }
exit 0
