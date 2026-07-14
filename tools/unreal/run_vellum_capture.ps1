#Requires -Version 5.1
<#
.SYNOPSIS
  Unsupervised Fireworks scratch inspect + still capture -> Vellum.

.DESCRIPTION
  Phase 0 (once): ensure permanent Lookdev Studio map (floor, pedestal, lights, slot).
  Phase A: inventory Niagara systems (cached when possible).
  Phase B: author Sequencer + MoviePipelineQueue onto the studio map; MRQ render; ingest.

.EXAMPLE
  pwsh -File tools/unreal/run_vellum_capture.ps1
#>
param(
  [string]$Project = "",
  [string]$AssetId = "fireworks-vol-1-niagara",
  [string]$ContentRoot = "/Game/FireworksV1",
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$Lane = "slots",
  [string]$EngineVersion = "5.8",
  [string]$IntakeRunId = "",
  [string]$UeCmd = $env:VELLUM_UE_CMD,
  [string]$HostName = "",
  [int]$MaxSystems = $(if ($env:VELLUM_MAX_SYSTEMS) { [int]$env:VELLUM_MAX_SYSTEMS } else { 0 }),
  [int]$Width = $(if ($env:VELLUM_WIDTH) { [int]$env:VELLUM_WIDTH } else { 1920 }),
  [int]$Height = $(if ($env:VELLUM_HEIGHT) { [int]$env:VELLUM_HEIGHT } else { 1080 }),
  [string]$MapPath = "/Game/Vellum/Maps/VellumLookdevStudio",
  [string]$JobId = $(if ($env:VELLUM_JOB_ID) { $env:VELLUM_JOB_ID } else { "" }),
  [switch]$ForceCapture = $(
    if ($env:VELLUM_FORCE_CAPTURE -match '^(1|true|yes)$') { $true } else { $false }
  ),
  [switch]$ForceStudio = $(
    if ($env:VELLUM_FORCE_STUDIO -match '^(1|true|yes)$') { $true } else { $false }
  )
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "ue-hosts.ps1")
$RepoRootEarly = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$UeHost = Get-UeHostProfile -RepoRoot $RepoRootEarly -HostName $HostName
if (-not $Project) { $Project = $UeHost.project }
if (-not $ContentRoot -or $ContentRoot -eq "/Game/FireworksV1") {
  if ($UeHost.content_root) { $ContentRoot = $UeHost.content_root }
}
if (-not $EngineVersion -or $EngineVersion -eq "5.8") {
  if ($UeHost.engine_version) { $EngineVersion = $UeHost.engine_version }
}

function Find-UeEditor {
  param([string]$CmdPath)
  # Prefer the GUI binary beside Cmd when needed.
  if ($CmdPath -and $CmdPath -match "UnrealEditor-Cmd\.exe$") {
    $gui = $CmdPath -replace "UnrealEditor-Cmd\.exe$", "UnrealEditor.exe"
    if (Test-Path $gui) { return $gui }
  }
  if ($UeHost.ue_editor -and (Test-Path -LiteralPath $UeHost.ue_editor)) {
    return (Resolve-Path -LiteralPath $UeHost.ue_editor).Path
  }
  foreach ($c in @(
      "F:\Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe",
      "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe",
      "C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe"
    )) {
    if (Test-Path $c) { return $c }
  }
  return $CmdPath
}

function Get-ImageFiles {
  # Windows PowerShell: -Include without a trailing \* often returns NOTHING.
  # Prefer -Filter (one extension per call) + -File.
  # Use ArrayList - List[object].Add(FileInfo) throws "Argument types do not match" on PS 5.1.
  param([string]$Root, [string[]]$Extensions = @("*.png", "*.jpg", "*.jpeg", "*.bmp"))
  if (-not (Test-Path $Root)) { return @() }
  $found = New-Object System.Collections.ArrayList
  foreach ($ext in $Extensions) {
    Get-ChildItem -Path $Root -Recurse -File -Filter $ext -ErrorAction SilentlyContinue |
      ForEach-Object { [void]$found.Add($_) }
  }
  return @($found.ToArray())
}

function Wait-MrqOutputFrames {
  <#
    Artifact gate: UnrealEditor -game often exits while MRQ is still writing PNGs.
    Done = stable count >= ExpectFrames.
    After a batch process has already exited: AcceptPartialStable accepts any
    stable n>0; EmptyAbortSec returns early when still 0 (avoid 900s x N).
  #>
  param(
    [string]$SeqOutDir,
    [int]$ExpectFrames = 1,
    [int]$TimeoutSec = 1800,
    [int]$StableSeconds = 8,
    [int]$EmptyAbortSec = 0,
    [switch]$AcceptPartialStable,
    [string]$Phase = "MRQ frames"
  )
  if ($ExpectFrames -lt 1) { $ExpectFrames = 1 }
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  $started = Get-Date
  $lastCount = -1
  $stableSince = $null
  while ((Get-Date) -lt $deadline) {
    $n = @(Get-ImageFiles -Root $SeqOutDir).Count
    if ($n -ne $lastCount) {
      $lastCount = $n
      $stableSince = Get-Date
      Send-VellumProgress -Message "$Phase frames=$n (want>=$ExpectFrames)"
    } elseif ($null -ne $stableSince) {
      $stableFor = ((Get-Date) - $stableSince).TotalSeconds
      if ($n -ge $ExpectFrames -and $stableFor -ge $StableSeconds) {
        Send-VellumProgress -Message "$Phase ready frames=$n"
        return $n
      }
      if ($AcceptPartialStable -and $n -gt 0 -and $stableFor -ge $StableSeconds) {
        Send-VellumProgress -Message "$Phase stable-partial frames=$n (batch done)"
        return $n
      }
      if ($EmptyAbortSec -gt 0 -and $n -eq 0 -and $stableFor -ge $EmptyAbortSec) {
        Send-VellumProgress -Message "$Phase empty-abort frames=0 after ${EmptyAbortSec}s"
        return 0
      }
    }
    Start-Sleep -Seconds 3
  }
  Send-VellumProgress -Message "$Phase timeout frames=$lastCount want>=$ExpectFrames"
  return [Math]::Max(0, $lastCount)
}

function Find-RecentImages {
  param(
    [string[]]$Roots,
    [datetime]$Since,
    [string]$NameHint = ""
  )
  $found = New-Object System.Collections.ArrayList
  foreach ($root in $Roots) {
    foreach ($img in (Get-ImageFiles -Root $root)) {
      if ($img.LastWriteTime -lt $Since.AddSeconds(-5)) { continue }
      if ($NameHint -ne "" -and
          $img.Name -notlike "*$NameHint*" -and
          $img.DirectoryName -notlike "*VellumCapture*" -and
          $img.DirectoryName -notlike "*Screenshots*") {
        continue
      }
      [void]$found.Add($img)
    }
  }
  return @($found.ToArray() | Sort-Object LastWriteTime -Descending)
}

function Get-VellumLogTailShared {
  # AbsLog is locked exclusive-ish by Unreal; Get-Content can hang forever.
  # Open with FileShare.ReadWrite and only sample the end.
  param([string]$LogPath, [int]$MaxBytes = 4096)
  if (-not $LogPath -or -not (Test-Path -LiteralPath $LogPath)) { return "" }
  try {
    $fs = [System.IO.File]::Open(
      $LogPath,
      [System.IO.FileMode]::Open,
      [System.IO.FileAccess]::Read,
      [System.IO.FileShare]::ReadWrite
    )
    try {
      $len = $fs.Length
      if ($len -le 0) { return "" }
      $start = [Math]::Max(0, $len - $MaxBytes)
      [void]$fs.Seek($start, [System.IO.SeekOrigin]::Begin)
      $buf = New-Object byte[] ([int]($len - $start))
      $read = $fs.Read($buf, 0, $buf.Length)
      $text = [System.Text.Encoding]::UTF8.GetString($buf, 0, $read)
      $lines = $text -split "`r?`n"
      return (($lines | Select-Object -Last 12) -join "`n")
    } finally { $fs.Dispose() }
  } catch {
    return ""
  }
}

function Send-VellumProgress {
  param(
    [string]$Message,
    [string]$LogPath = ""
  )
  Write-Host $Message
  if (-not $JobId -or -not $VellumBase) { return }
  $tail = ""
  if ($LogPath) { $tail = Get-VellumLogTailShared -LogPath $LogPath }
  $body = @{ message = $Message; log_tail = $tail } | ConvertTo-Json -Compress
  try {
    Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$JobId/progress" `
      -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 5 | Out-Null
  } catch {
    # Progress is best-effort; never fail the capture on heartbeat errors.
  }
}

function Invoke-UeLogged {
  # Never RedirectStandardOutput/Error on UE - after Unreal exits, Process.Dispose
  # and ExitCode on redirected handles hang PowerShell forever (observed Aurora).
  # Liveness = Get-Process -Id only. Logs via -AbsLog=. TimeoutSec kills hung UE.
  param(
    [string]$Exe,
    [string[]]$ArgumentList,
    [string]$LogPath,
    [string]$Phase,
    [int]$HeartbeatSeconds = 15,
    [int]$TimeoutSec = 0,
    [switch]$NoRedirect  # retained for callers; always no-redirect now
  )
  if (Test-Path $LogPath) { Remove-Item -Force $LogPath -ErrorAction SilentlyContinue }
  Send-VellumProgress -Message "$Phase starting exe=$Exe"
  $joined = [System.Collections.Generic.List[string]]::new()
  foreach ($a in @($ArgumentList)) { [void]$joined.Add([string]$a) }
  if (-not ($joined | Where-Object { $_ -like "-AbsLog=*" })) {
    [void]$joined.Add("-AbsLog=$LogPath")
  }
  $proc = Start-Process -FilePath $Exe -ArgumentList $joined.ToArray() `
    -PassThru -WindowStyle Minimized
  $uePid = [int]$proc.Id
  # Drop Process object immediately - keep only PID. Do not Dispose/ExitCode.
  $proc = $null
  Send-VellumProgress -Message "$Phase pid=$uePid"
  $started = Get-Date
  while ($null -ne (Get-Process -Id $uePid -ErrorAction SilentlyContinue)) {
    Start-Sleep -Seconds $HeartbeatSeconds
    if ($null -eq (Get-Process -Id $uePid -ErrorAction SilentlyContinue)) { break }
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    if ($TimeoutSec -gt 0 -and $elapsed -ge $TimeoutSec) {
      Send-VellumProgress -Message "$Phase TIMEOUT ${elapsed}s - killing pid=$uePid"
      try { Stop-Process -Id $uePid -Force -ErrorAction SilentlyContinue } catch { }
      Start-Sleep -Seconds 2
      try {
        Get-Process -Name "UnrealEditor","UnrealEditor-Cmd" -ErrorAction SilentlyContinue |
          Where-Object { $_.Id -eq $uePid } | Stop-Process -Force -ErrorAction SilentlyContinue
      } catch { }
      break
    }
    # Never attach AbsLog here - Get-Content/share-read still blocked mid-shutdown.
    Send-VellumProgress -Message "$Phase still running (${elapsed}s)"
  }
  Send-VellumProgress -Message "$Phase process gone"
  return 0
}

function Get-SavedTreeSnippet {
  param([string]$SavedRoot, [int]$MaxLines = 30)
  if (-not (Test-Path $SavedRoot)) { return "(no Saved dir)" }
  $lines = Get-ImageFiles -Root $SavedRoot |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First $MaxLines |
    ForEach-Object { "{0:u}  {1}" -f $_.LastWriteTime.ToUniversalTime(), $_.FullName }
  if (-not $lines) { return "(no images under Saved/)" }
  return ($lines -join "`n")
}

function Get-LogShotSnippet([string]$LogPath) {
  if (-not (Test-Path $LogPath)) { return "(no game log)" }
  $lines = Select-String -Path $LogPath -Pattern "Screenshot taken|Wrote screenshot|HighResScreenshot|Taking high res screenshot|Bringing up level for play|LogLoad: Took |Error:|Fatal" -ErrorAction SilentlyContinue |
    Where-Object { $_.Line -notmatch "commandline=|Command Line:|-ExecCmds=" } |
    Select-Object -Last 40 |
    ForEach-Object { $_.Line }
  if (-not $lines) { return "(no screenshot/map-ready lines in log - cmdline HighResShot echo ignored)" }
  return ($lines -join "`n")
}

function Get-LogMrqSnippet([string]$LogPath) {
  if (-not (Test-Path $LogPath)) { return "(no MRQ log)" }
  $lines = Select-String -Path $LogPath -Pattern "MoviePipeline|Movie Render|LevelSequence|Failed to|Error:|Fatal|Render complete|Finished rendering|Writing frame|Output directory|Could not|not found|LogPython" -ErrorAction SilentlyContinue |
    Select-Object -Last 50 |
    ForEach-Object { $_.Line.Trim() }
  if (-not $lines) { return "(no MoviePipeline/Error lines in MRQ log)" }
  return ($lines -join "`n")
}

function ConvertTo-UePath([string]$Path) {
  return (($Path -replace '\\', '/').TrimEnd('/'))
}

function ConvertTo-UeSoftPath([string]$PackageOrSoft) {
  # Epic cmdline requires /Game/Path/Asset.Asset - package path alone often exits 0 with zero frames.
  $p = ConvertTo-UePath $PackageOrSoft
  if (-not $p) { return $p }
  $leaf = ($p -split "/")[-1]
  if ($leaf -match "\.") { return $p }
  return "$p.$leaf"
}

function Get-LogPythonSnippet([string]$LogText) {
  if (-not $LogText) { return "" }
  $lines = $LogText -split "`r?`n" | Where-Object {
    $_ -match "LogPython|ExecutePythonScript|vellum_capture|Vellum capture|Vellum inventory|Vellum bake-map|Could not load Python"
  }
  if (-not $lines) { return "" }
  return (($lines | Select-Object -Last 40) -join "`n")
}

function Safe-Name([string]$Name) {
  return -join ($Name.ToCharArray() | ForEach-Object { if ($_ -match "[A-Za-z0-9_-]") { $_ } else { "_" } })
}

function New-StoreZipFromDir {
  # PNGs are already compressed - store-only zip is much faster than Compress-Archive.
  param([string]$SourceDir, [string]$ZipPath)
  if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
  Add-Type -AssemblyName System.IO.Compression
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [System.IO.Compression.ZipFile]::Open($ZipPath, [System.IO.Compression.ZipArchiveMode]::Create)
  try {
    $root = (Resolve-Path $SourceDir).Path.TrimEnd('\','/')
    Get-ChildItem -Path $SourceDir -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
      $rel = $_.FullName.Substring($root.Length).TrimStart('\','/') -replace '\\','/'
      [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $zip,
        $_.FullName,
        $rel,
        [System.IO.Compression.CompressionLevel]::NoCompression
      )
    }
  } finally {
    $zip.Dispose()
  }
}

function Ingest-CapturedSystem {
  # Upload heroes + sequence immediately so an interrupt mid-batch still lands vault outputs.
  # Soft-fail: one bad upload must not abort the rest of the pack.
  param(
    [string]$AssetId,
    [string]$SystemName,
    [object[]]$HeroStills,
    [string]$SeqDir,
    [string]$OutDir,
    [string]$VellumBase,
    [string[]]$Lanes,
    [System.Collections.IList]$Errors
  )
  $uploaded = 0
  $heroTasks = New-Object System.Collections.ArrayList
  foreach ($still in $HeroStills) {
    $path = [string]$still.path
    if (-not (Test-Path $path)) { continue }
    foreach ($laneName in $Lanes) {
      [void]$heroTasks.Add(@{
          path = $path
          lane = $laneName
          role = [string]$still.role
        })
    }
  }
  # Sequential hero curls - ForEach-Object -Parallel deadlocked the pack ingest
  # mid-flight after the first system (pwsh 7 runspace pool). Store-zip + single
  # sequence POST already dominates the win; 4 sequential curls are ~1s.
  foreach ($task in $heroTasks) {
    $path = [string]$task.path
    $laneName = [string]$task.lane
    $role = [string]$task.role
    Send-VellumProgress -Message "Ingest render $SystemName $role -> $laneName"
    $null = & curl.exe -sfS --connect-timeout 20 --max-time 180 -X POST "$VellumBase/api/lookdev/ingest-render" `
      -F "asset_id=$AssetId" `
      -F "lane=$laneName" `
      -F "system_name=$SystemName" `
      -F "note=auto Niagara MRQ $role $SystemName via mrq-batch" `
      -F "file=@$path"
    if ($LASTEXITCODE -ne 0) {
      if ($Errors) {
        [void]$Errors.Add("ingest_render_failed:$SystemName`:$laneName")
      }
      Write-Host "WARNING ingest-render failed for $path lane=$laneName"
      continue
    }
    $uploaded++
    Write-Host "Ingested hero $path -> $laneName"
  }
  if ((Test-Path $SeqDir)) {
    $zipPath = Join-Path $OutDir ("seq-" + (Safe-Name $SystemName) + ".zip")
    Send-VellumProgress -Message "Zip sequence $SystemName (store)"
    New-StoreZipFromDir -SourceDir $SeqDir -ZipPath $zipPath
    $laneCsv = ($Lanes -join ",")
    Send-VellumProgress -Message "Ingest sequence $SystemName -> $laneCsv"
    $null = & curl.exe -sfS --connect-timeout 20 --max-time 900 -X POST "$VellumBase/api/lookdev/ingest-sequence" `
      -F "asset_id=$AssetId" `
      -F "lanes=$laneCsv" `
      -F "system_name=$SystemName" `
      -F "note=auto Niagara MRQ sequence $SystemName via mrq-batch" `
      -F "archive=@$zipPath"
    if ($LASTEXITCODE -ne 0) {
      if ($Errors) {
        [void]$Errors.Add("ingest_sequence_failed:$SystemName")
      }
      Write-Host "WARNING ingest-sequence failed for $SystemName lanes=$laneCsv"
    } else {
      $uploaded += @($Lanes).Count
      Write-Host "Ingested sequence $SystemName -> $laneCsv"
    }
  }
  return $uploaded
}

function Get-LookdevOutputs {
  param([string]$VellumBase, [string]$AssetId, [switch]$Required)
  try {
    # Pack scale: heroes x lanes x systems can exceed 200; API allows up to 1000.
    $r = Invoke-RestMethod -Method Get `
      -Uri "$VellumBase/api/lookdev/outputs?asset_id=$AssetId&limit=1000" -TimeoutSec 60
    if ($r.outputs) { return @($r.outputs) }
    return @()
  } catch {
    Write-Host "WARNING: lookdev outputs fetch failed: $($_.Exception.Message)"
    if ($Required) { throw "lookdev_outputs_fetch_failed:$($_.Exception.Message)" }
  }
  return @()
}

function Get-VaultCoveredSystemSet {
  # Only treat Capture runner provenance as done. Recover / pre-harden afternoon
  # MRP rows must NOT satisfy skip (they were recorded under broken host paths).
  param(
    [object[]]$Outputs,
    [string[]]$Lanes,
    [datetime]$TrustedAfterUtc,
    [string]$TrustedNoteNeedle = "via mrq-batch"
  )
  $bySystem = @{}
  foreach ($o in @($Outputs)) {
    if ([string]$o.kind -ne "niagara-render") { continue }
    $lane = [string]$o.lane
    if ($Lanes -notcontains $lane) { continue }
    $note = [string]$o.note
    if ($TrustedNoteNeedle -and ($note -notlike "*$TrustedNoteNeedle*")) { continue }
    $created = $null
    try { $created = [datetime]::Parse([string]$o.created_at, $null, [System.Globalization.DateTimeStyles]::RoundtripKind) } catch { $created = $null }
    if ($null -eq $created) { continue }
    if ($created.ToUniversalTime() -lt $TrustedAfterUtc) { continue }
    $exact = [string]$o.system_name
    if ($exact -and $exact.StartsWith("NS_")) {
      $names = @($exact)
    } else {
      $blob = ("{0} {1} {2}" -f [string]$o.path, $note, [string]$o.system_name)
      $names = @([regex]::Matches($blob, 'NS_[A-Za-z0-9_]+') | ForEach-Object { $_.Value })
    }
    foreach ($name in $names) {
      if (-not $bySystem.ContainsKey($name)) {
        $bySystem[$name] = New-Object 'System.Collections.Generic.HashSet[string]'
      }
      [void]$bySystem[$name].Add($lane)
    }
  }
  $covered = New-Object 'System.Collections.Generic.HashSet[string]'
  $need = $Lanes.Count
  foreach ($kv in $bySystem.GetEnumerator()) {
    if ($kv.Value.Count -ge $need) {
      [void]$covered.Add([string]$kv.Key)
    }
  }
  return $covered
}

function Test-LocalMrqTrusted {
  # ingest_only only when on-disk frames are from the hardened Capture era.
  param([string]$SeqOutDir, [datetime]$TrustedAfterUtc, [int]$MinFrames = 30)
  $files = @(Get-ImageFiles -Root $SeqOutDir)
  if ($files.Count -lt $MinFrames) { return $false }
  $newest = ($files | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).LastWriteTimeUtc
  return ($newest -ge $TrustedAfterUtc)
}

function Test-VaultHasSystemLookdev {
  param(
    [System.Collections.Generic.HashSet[string]]$Covered,
    [string]$SystemName
  )
  if (-not $Covered) { return $false }
  return $Covered.Contains($SystemName)
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$InventoryPySource = Join-Path $PSScriptRoot "vellum_capture.py"
$AuthorPySource = Join-Path $PSScriptRoot "vellum_capture_mrq_author.py"
$StudioPySource = Join-Path $PSScriptRoot "vellum_lookdev_studio_author.py"
$PickHeroesPy = Join-Path $PSScriptRoot "pick_heroes.py"
if (-not (Test-Path $InventoryPySource)) { throw "vellum_capture.py not found next to runner" }
if (-not (Test-Path $AuthorPySource)) { throw "vellum_capture_mrq_author.py not found next to runner" }
if (-not (Test-Path $StudioPySource)) { throw "vellum_lookdev_studio_author.py not found next to runner" }
if (-not (Test-Path $PickHeroesPy)) { throw "pick_heroes.py not found next to runner" }
if (-not $Project) {
  $Project = Resolve-UprojectFromHost -HostProfile $UeHost
}
if (-not (Test-Path $Project)) { throw "Project not found: $Project" }

$ProjectDir = Split-Path $Project -Parent
$OutDir = Join-Path $ProjectDir "Saved\VellumCapture"
$StillsDir = Join-Path $OutDir "stills"
$MrqRoot = Join-Path $OutDir "mrq"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path $StillsDir | Out-Null
New-Item -ItemType Directory -Force -Path $MrqRoot | Out-Null

$StagedInventoryPy = Join-Path $OutDir "vellum_capture.py"
$StagedAuthorPy = Join-Path $OutDir "vellum_capture_mrq_author.py"
$StagedStudioPy = Join-Path $OutDir "vellum_lookdev_studio_author.py"
$StagedPickHeroesPy = Join-Path $OutDir "pick_heroes.py"
Copy-Item -Force -Path $InventoryPySource -Destination $StagedInventoryPy
Copy-Item -Force -Path $AuthorPySource -Destination $StagedAuthorPy
Copy-Item -Force -Path $StudioPySource -Destination $StagedStudioPy
Copy-Item -Force -Path $PickHeroesPy -Destination $StagedPickHeroesPy

$ProjectUe = ConvertTo-UePath $Project
$OutDirUe = ConvertTo-UePath $OutDir
$FrameCount = 120
$FrameRate = 30
$IngestLanes = @("slots", "hail-overlay")
# Vault/local skip only trusts Capture outputs after the Cmd hang fixes + AbsLog harden.
# Override: VELLUM_TRUSTED_CAPTURE_AFTER=2026-07-13T23:15:00Z
$TrustedAfterUtc = [datetime]::Parse(
  $(if ($env:VELLUM_TRUSTED_CAPTURE_AFTER) { $env:VELLUM_TRUSTED_CAPTURE_AFTER } else { "2026-07-13T23:15:00Z" }),
  $null,
  [System.Globalization.DateTimeStyles]::RoundtripKind
).ToUniversalTime()
Write-Host "TrustedCaptureAfterUtc=$TrustedAfterUtc (skip ignores recover/pre-harden vault)"
$Ue = $null

function Ensure-UeCmd {
  if ($script:Ue) { return $script:Ue }
  $script:Ue = Find-UeCmdFromHost -HostProfile $UeHost -Hint $UeCmd
  Write-Host "UE (Cmd): $script:Ue"
  return $script:Ue
}

Write-Host "Project: $ProjectUe"
Write-Host "MaxSystems=$MaxSystems (0=entire pack) Width=$Width Height=$Height MapPath=$MapPath"
Write-Host "Runner version: mrq-pack-harden (2026-07-13)"
Write-Host "UE host: $($UeHost.id) ($($UeHost.label))"
Write-Host "Ingest lanes: $($IngestLanes -join ', ')"
Write-Host "ForceCapture=$ForceCapture ForceStudio=$ForceStudio MaxFrameCount=$FrameCount (per-system estimate may be shorter)"
if ($JobId) { Write-Host "JobId=$JobId (progress -> $VellumBase/api/jobs/$JobId/progress)" }

$allErrors = New-Object System.Collections.ArrayList
$stills = New-Object System.Collections.ArrayList
$sequences = New-Object System.Collections.ArrayList
$InventoryCachePath = Join-Path $OutDir "inventory-cache.json"
$StudioReadyPath = Join-Path $OutDir "studio-ready.json"
$InventoryCacheMaxAgeHours = 72

# ---------------------------------------------------------------------------
# Phase 0: ensure permanent Lookdev Studio map exists (photo studio)
# ---------------------------------------------------------------------------
$needStudio = $ForceStudio -or -not (Test-Path $StudioReadyPath)
if (-not $needStudio) {
  try {
    $studioDoc = Get-Content $StudioReadyPath -Raw | ConvertFrom-Json
    if (-not [bool]$studioDoc.ok) { $needStudio = $true }
    if ($studioDoc.map_path -and [string]$studioDoc.map_path -ne $MapPath) { $needStudio = $true }
    $studioBuild = 0
    if ($null -ne $studioDoc.studio_build) { $studioBuild = [int]$studioDoc.studio_build }
    if ($studioBuild -lt 3) { $needStudio = $true }
  } catch {
    $needStudio = $true
  }
}
if ($needStudio) {
  $Ue = Ensure-UeCmd
  $env:VELLUM_OUT_DIR = $OutDirUe
  $env:VELLUM_STUDIO_MAP = $MapPath
  $StudioLog = Join-Path $OutDir "ue-studio.log"
  if (Test-Path $StudioLog) { Remove-Item -Force $StudioLog }
  $StudioExecFlag = "-ExecutePythonScript=" + (ConvertTo-UePath $StagedStudioPy)
  Write-Host "Phase 0 (lookdev studio): $StudioExecFlag"
  Send-VellumProgress -Message "Building Lookdev Studio map..."
  $studioExit = 0
  try {
    $studioExit = Invoke-UeLogged -Exe $Ue -ArgumentList @(
        $ProjectUe, "-stdout", "-FullStdOutLogOutput", "-unattended", "-nop4", $StudioExecFlag
      ) -LogPath $StudioLog -Phase "Phase 0 lookdev studio"
  } catch {
    $studioExit = 1
    $_ | Out-File -FilePath $StudioLog -Append
  }
  if (-not (Test-Path $StudioReadyPath)) {
    throw "Lookdev Studio did not write studio-ready.json (exit=$studioExit). See $StudioLog"
  }
  $studioDoc = Get-Content $StudioReadyPath -Raw | ConvertFrom-Json
  if (-not [bool]$studioDoc.ok) {
    throw "Lookdev Studio build reported ok=false. See $StudioLog"
  }
  Send-VellumProgress -Message "Lookdev Studio ready: $MapPath"
} else {
  Write-Host "Phase 0 skipped: studio-ready.json present"
  Send-VellumProgress -Message "Lookdev Studio already built"
}

function Read-InventoryCache {
  param([string]$Path, [string]$ExpectedRoot, [int]$MaxAgeHours, [int]$MaxSystems)
  if (-not (Test-Path $Path)) { return $null }
  try {
    $doc = Get-Content $Path -Raw | ConvertFrom-Json
  } catch {
    return $null
  }
  if (-not $doc -or -not $doc.niagara_systems) { return $null }
  if ([string]$doc.content_root -ne $ExpectedRoot) { return $null }
  $cachedMax = 0
  if ($null -ne $doc.max_systems) { $cachedMax = [int]$doc.max_systems }
  if ($cachedMax -ne $MaxSystems) {
    Write-Host "Inventory cache max_systems mismatch (cache=$cachedMax want=$MaxSystems) - refreshing"
    return $null
  }
  if ($doc.written_at) {
    try {
      $written = [datetime]::Parse([string]$doc.written_at).ToUniversalTime()
      if (((Get-Date).ToUniversalTime() - $written).TotalHours -gt $MaxAgeHours) {
        Write-Host "Inventory cache expired (>$MaxAgeHours h)"
        return $null
      }
    } catch {
      # keep using cache if timestamp unreadable
    }
  }
  return $doc
}

function Write-InventoryCache {
  param([string]$Path, [object]$Inventory, [string]$ContentRoot, [int]$MaxSystems)
  $doc = @{
    schema_version        = 1
    written_at            = (Get-Date).ToUniversalTime().ToString("o")
    content_root          = $ContentRoot
    max_systems           = $MaxSystems
    niagara_systems_found = [int]$Inventory.niagara_systems_found
    niagara_systems       = @($Inventory.niagara_systems)
  }
  ($doc | ConvertTo-Json -Depth 8) | Set-Content -Path $Path -Encoding utf8
}

# ---------------------------------------------------------------------------
# Phase A: inventory (use on-disk cache when fresh - avoid UE cold start)
# ---------------------------------------------------------------------------
$inv = $null
$inventoryFromCache = $false
if ($ForceCapture -and (Test-Path $InventoryCachePath)) {
  Remove-Item -Force $InventoryCachePath -ErrorAction SilentlyContinue
  Write-Host "ForceCapture: cleared inventory cache"
}
if (-not $ForceCapture) {
  $inv = Read-InventoryCache -Path $InventoryCachePath -ExpectedRoot $ContentRoot `
    -MaxAgeHours $InventoryCacheMaxAgeHours -MaxSystems $MaxSystems
  if ($inv) {
    $inventoryFromCache = $true
    Write-Host "Phase A skipped: using inventory cache ($($inv.niagara_systems.Count) systems)"
    Send-VellumProgress -Message "Inventory cache hit: systems=$(@($inv.niagara_systems).Count) root=$ContentRoot"
  }
}

if (-not $inv) {
  $Ue = Ensure-UeCmd
  $env:VELLUM_ASSET_ID = $AssetId
  $env:VELLUM_CONTENT_ROOT = $ContentRoot
  $env:VELLUM_OUT_DIR = $OutDirUe
  $env:VELLUM_MAX_SYSTEMS = "$MaxSystems"

  $InventoryLog = Join-Path $OutDir "ue-inventory.log"
  if (Test-Path $InventoryLog) { Remove-Item -Force $InventoryLog }
  $InventoryExecFlag = "-ExecutePythonScript=" + (ConvertTo-UePath $StagedInventoryPy)
  Write-Host "Phase A (inventory): $InventoryExecFlag"

  $ueExit = 0
  try {
    $ueExit = Invoke-UeLogged -Exe $Ue -ArgumentList @(
        $ProjectUe, "-stdout", "-FullStdOutLogOutput", "-unattended", "-nop4", $InventoryExecFlag
      ) -LogPath $InventoryLog -Phase "Phase A inventory"
  } catch {
    $ueExit = 1
    $_ | Out-File -FilePath $InventoryLog -Append
    Send-VellumProgress -Message "Phase A inventory crashed: $_" -LogPath $InventoryLog
  }
  Write-Host "Inventory phase exit code: $ueExit"

  $InventoryManifestPath = Join-Path $OutDir "manifest-inventory.json"
  if (-not (Test-Path $InventoryManifestPath)) {
    $logTail = ""
    if (Test-Path $InventoryLog) {
      $logTail = Get-LogPythonSnippet (Get-Content $InventoryLog -Raw -ErrorAction SilentlyContinue)
    }
    throw @"
Inventory did not write manifest-inventory.json under $OutDir (runner=mrq-sequencer).
Unreal exit=$ueExit staged=$StagedInventoryPy

LogPython snippet:
$logTail
"@
  }

  $inv = Get-Content $InventoryManifestPath -Raw | ConvertFrom-Json
  Write-InventoryCache -Path $InventoryCachePath -Inventory $inv -ContentRoot $(
    if ($inv.content_root) { [string]$inv.content_root } else { $ContentRoot }
  ) -MaxSystems $MaxSystems
}
if ($inv.errors) { foreach ($e in @($inv.errors)) { [void]$allErrors.Add("inventory:$e") } }
if ($inv.content_root) { $ContentRoot = [string]$inv.content_root }
$pickedSystems = @($inv.niagara_systems)
Write-Host "Inventory systems_found=$($inv.niagara_systems_found) picked=$($pickedSystems.Count) content_root=$ContentRoot"
if ($inv.notes) { Write-Host "Inventory notes: $((@($inv.notes) | Select-Object -First 12) -join ' | ')" }
if ($inv.disk) {
  try {
    $diskJson = $inv.disk | ConvertTo-Json -Compress -Depth 5
    Write-Host "Inventory disk: $diskJson"
  } catch {
    Write-Host "Inventory disk: (present)"
  }
}
Send-VellumProgress -Message "Inventory done: found=$($inv.niagara_systems_found) picked=$($pickedSystems.Count) root=$ContentRoot"
if ($pickedSystems.Count -eq 0) {
  [void]$allErrors.Add("no_systems_to_capture")
  if ($inv.errors) { foreach ($e in @($inv.errors)) { [void]$allErrors.Add([string]$e) } }
}

# ---------------------------------------------------------------------------
# Skip systems already covered in vault (fast HashSet - no local PNG scans).
# ForceCapture / VELLUM_FORCE_CAPTURE re-renders everything.
# Local MRQ dirs with enough frames -> ingest_only (no wipe / no re-author).
# ---------------------------------------------------------------------------
$skippedVault = New-Object System.Collections.ArrayList
$toRenderSystems = New-Object System.Collections.ArrayList
$toIngestOnly = New-Object System.Collections.ArrayList
$vaultCovered = New-Object 'System.Collections.Generic.HashSet[string]'
$skipSw = [System.Diagnostics.Stopwatch]::StartNew()
if (-not $ForceCapture -and $pickedSystems.Count -gt 0) {
  Send-VellumProgress -Message "Skip check: fetching vault lookdev..."
  $vaultOutputs = Get-LookdevOutputs -VellumBase $VellumBase -AssetId $AssetId -Required
  $vaultCovered = Get-VaultCoveredSystemSet -Outputs $vaultOutputs -Lanes $IngestLanes -TrustedAfterUtc $TrustedAfterUtc
  Write-Host "Skip check: vault outputs=$(@($vaultOutputs).Count) covered=$($vaultCovered.Count) force=$ForceCapture"
}
foreach ($sys in $pickedSystems) {
  $systemName = [string]$sys.asset_name
  $objectPath = [string]$sys.object_path
  $safeHint = Safe-Name $systemName
  $seqOutDir = Join-Path $MrqRoot $safeHint
  $skipEntry = @{
    asset_name  = $systemName
    object_path = $objectPath
    safe_name   = $safeHint
    seq_dir     = $seqOutDir
  }
  if ($ForceCapture) {
    [void]$toRenderSystems.Add($sys)
    continue
  }
  if (Test-VaultHasSystemLookdev -Covered $vaultCovered -SystemName $systemName) {
    $skipEntry.reason = "vault_covered"
    [void]$skippedVault.Add($skipEntry)
    continue
  }
  if (Test-LocalMrqTrusted -SeqOutDir $seqOutDir -TrustedAfterUtc $TrustedAfterUtc -MinFrames 30) {
    $localFrames = @(Get-ImageFiles -Root $seqOutDir).Count
    $skipEntry.reason = "ingest_only_trusted_local_frames:$localFrames"
    $skipEntry.sys = $sys
    [void]$toIngestOnly.Add($skipEntry)
    continue
  }
  [void]$toRenderSystems.Add($sys)
}
$skipSw.Stop()
Send-VellumProgress -Message ("Skip plan: render={0} ingest_only={1} vault_skip={2} force={3} cache={4} ({5}ms)" -f `
  $toRenderSystems.Count, $toIngestOnly.Count, $skippedVault.Count, [bool]$ForceCapture, [bool]$inventoryFromCache, $skipSw.ElapsedMilliseconds)
Write-Host ("Skip plan done in {0}ms render={1} ingest_only={2} vault_skip={3}" -f `
  $skipSw.ElapsedMilliseconds, $toRenderSystems.Count, $toIngestOnly.Count, $skippedVault.Count)

if ($toRenderSystems.Count -eq 0 -and $toIngestOnly.Count -eq 0) {
  Send-VellumProgress -Message "No Unreal author/MRQ needed (vault already covered or nothing picked)"
} elseif ($toRenderSystems.Count -eq 0 -and $toIngestOnly.Count -gt 0) {
  Send-VellumProgress -Message "Ingest-only: $($toIngestOnly.Count) local MRQ dirs (no UE author/MRQ)"
}

# ---------------------------------------------------------------------------
# Phase B: author systems needing render in one UE process + MoviePipelineQueue.
# Phase C: one cmdline MRQ for the queue (fallback: per-system if no queue).
# Then heroes + per-system ingest.
# ---------------------------------------------------------------------------
$batchSystems = @()
$slotIndex = 0
foreach ($sys in $toRenderSystems) {
  $systemName = [string]$sys.asset_name
  $objectPath = [string]$sys.object_path
  $safeHint = Safe-Name $systemName
  $seqOutDir = Join-Path $MrqRoot $safeHint
  New-Item -ItemType Directory -Force -Path $seqOutDir | Out-Null
  # Only wipe output dir for systems we are about to re-render (not vault skips).
  Get-ChildItem -Path $seqOutDir -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
  Get-ChildItem -Path $seqOutDir -Recurse -File -Filter "*.png" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
  $batchSystems += @{
    object_path = $objectPath
    asset_name  = $systemName
    output_dir  = (ConvertTo-UePath $seqOutDir)
  }
  $slotIndex++
}

if ($batchSystems.Count -gt 0) {
  $Ue = Ensure-UeCmd
  Write-Host "Phase B batch author systems=$($batchSystems.Count)"
  $job = @{
    asset_id         = $AssetId
    map_path         = $MapPath
    width            = $Width
    height           = $Height
    frame_count      = $FrameCount
    frame_rate       = $FrameRate
    sequence_package = "/Game/Vellum/Sequences"
    config_package   = "/Game/Vellum/MRQ"
    queue_name       = "VellumBatchQueue"
    systems          = $batchSystems
  }
  $JobPath = Join-Path $OutDir "job.json"
  ($job | ConvertTo-Json -Depth 6) | Set-Content -Path $JobPath -Encoding utf8
  $env:VELLUM_JOB_JSON = ConvertTo-UePath $JobPath
  $env:VELLUM_OUT_DIR = $OutDirUe

  $AuthorLog = Join-Path $OutDir "ue-author-batch.log"
  if (Test-Path $AuthorLog) { Remove-Item -Force $AuthorLog }
  $AuthorExecFlag = "-ExecutePythonScript=" + (ConvertTo-UePath $StagedAuthorPy)
  $authorExit = 0
  try {
    $authorExit = Invoke-UeLogged -Exe $Ue -ArgumentList @(
        $ProjectUe, "-stdout", "-FullStdOutLogOutput", "-unattended", "-nop4", $AuthorExecFlag
      ) -LogPath $AuthorLog -Phase "Phase B batch author"
  } catch {
    $authorExit = 1
    $_ | Out-File -FilePath $AuthorLog -Append
    Send-VellumProgress -Message "Phase B batch author crashed: $_" -LogPath $AuthorLog
  }

  $AuthorResultPath = Join-Path $OutDir "author-result.json"
  if (-not (Test-Path $AuthorResultPath)) {
    [void]$allErrors.Add("author_no_result:batch:exit=$authorExit")
    Send-VellumProgress -Message "FAIL batch author (no result)" -LogPath $AuthorLog
  } else {
    $author = Get-Content $AuthorResultPath -Raw | ConvertFrom-Json
    if ($author.errors) { foreach ($e in @($author.errors)) { [void]$allErrors.Add("author:$e") } }
    if ($author.notes) {
      Write-Host "Author notes: $((@($author.notes) | Select-Object -First 36) -join ' | ')"
    }
    if (-not [bool]$author.ok) {
      [void]$allErrors.Add("author_failed:batch")
      Send-VellumProgress -Message "FAIL batch author" -LogPath $AuthorLog
    } else {
      $authoredJobs = @($author.jobs)
      if ($authoredJobs.Count -eq 0 -and $author.system_name) {
        $authoredJobs = @($author)
      }
      $mapSoft = ConvertTo-UeSoftPath $(if ($author.map_path) { [string]$author.map_path } else { $MapPath })
      $queueSoft = $null
      if ($author.queue_path) { $queueSoft = ConvertTo-UeSoftPath ([string]$author.queue_path) }
      if (-not $queueSoft -and $authoredJobs.Count -gt 1) {
        [void]$allErrors.Add("author_queue_missing:jobs=$($authoredJobs.Count)")
        Send-VellumProgress -Message "FAIL author ok but no queue_path for multi-job pack"
      }

      Send-VellumProgress -Message "Phase B author ok - entering Phase C"
      $UeMrq = Find-UeEditor -CmdPath $Ue
      Send-VellumProgress -Message "Phase C UE binary: $UeMrq"
      Write-Host "Phase C UE binary: $UeMrq"

      if ($queueSoft) {
        Write-Host "Phase C queue MRQ queue=$queueSoft map=$mapSoft jobs=$($authoredJobs.Count)"
        Send-VellumProgress -Message "Phase C queue=$queueSoft jobs=$($authoredJobs.Count)"
        $MrqLog = Join-Path $OutDir "ue-mrq-batch.log"
        if (Test-Path $MrqLog) { Remove-Item -Force $MrqLog -ErrorAction SilentlyContinue }
        $mrqArgs = @(
          $ProjectUe,
          $mapSoft,
          "-game",
          "-windowed",
          "-ResX=$Width",
          "-ResY=$Height",
          "-nosplash",
          "-nop4",
          "-log",
          "-Unattended",
          "-MoviePipelineConfig=$queueSoft"
        )
        $mrqExit = 0
        # Epic: -MoviePipelineConfig may be a Queue asset (renders all jobs).
        # Timeout scales with job count so a hung editor cannot pin the pack forever.
        $batchTimeout = 300 + (60 * [Math]::Max(1, $authoredJobs.Count))
        try {
          $mrqExit = Invoke-UeLogged -Exe $UeMrq -ArgumentList $mrqArgs -LogPath $MrqLog `
            -Phase "Phase C batch MRQ" -HeartbeatSeconds 20 -TimeoutSec $batchTimeout -NoRedirect
        } catch {
          $mrqExit = 1
          $_ | Out-File -FilePath $MrqLog -Append
          Send-VellumProgress -Message "Phase C Start-Process failed: $_"
        }
        Write-Host "Phase C batch MRQ process exit=$mrqExit (artifacts are the gate)"
        $renderedOk = $true
      } else {
        Write-Host "Phase C: no queue_path from author - falling back to per-system MRQ"
      }

      # Per-system: wait for MRQ artifacts, then hero + ingest. Re-render only if zero frames.
      $slotIndex = 0
      foreach ($ajob in $authoredJobs) {
        $systemName = [string]$ajob.system_name
        $objectPath = [string]$ajob.system_object_path
        $safeHint = Safe-Name $systemName
        $seqOutDir = Join-Path $MrqRoot $safeHint
        if (-not $ajob.output_dir) { }
        else { $seqOutDir = ([string]$ajob.output_dir) -replace '/', '\' }
        New-Item -ItemType Directory -Force -Path $seqOutDir | Out-Null

        $expect = 30
        if ($null -ne $ajob.frame_count -and [int]$ajob.frame_count -gt 0) {
          $expect = [int]$ajob.frame_count
        }
        # After batch exit: short empty-abort + partial-stable (avoid 900s x N pack hang).
        if ($queueSoft) {
          $frameCount = Wait-MrqOutputFrames -SeqOutDir $seqOutDir -ExpectFrames $expect `
            -Phase "Phase C[$slotIndex] $systemName" -TimeoutSec 120 `
            -EmptyAbortSec 25 -AcceptPartialStable `
            -StableSeconds 6
        } else {
          $frameCount = 0
        }
        $frameFiles = @(Get-ImageFiles -Root $seqOutDir)

        if ($frameFiles.Count -eq 0 -or -not $queueSoft) {
          $seqSoft = ConvertTo-UeSoftPath $(if ($ajob.sequence_path) { [string]$ajob.sequence_path } else { [string]$ajob.sequence_asset })
          $cfgSoft = ConvertTo-UeSoftPath $(if ($ajob.config_path) { [string]$ajob.config_path } else { [string]$ajob.config_asset })
          Write-Host "Phase C[$slotIndex] per-system MRQ $systemName (no batch frames yet)"
          $MrqLog = Join-Path $OutDir "ue-mrq-$slotIndex.log"
          if (Test-Path $MrqLog) { Remove-Item -Force $MrqLog }
          $mrqArgs = @(
            $ProjectUe,
            $mapSoft,
            "-game",
            "-windowed",
            "-ResX=$Width",
            "-ResY=$Height",
            "-nosplash",
            "-nop4",
            "-log",
            "-Unattended",
            "-LevelSequence=$seqSoft",
            "-MoviePipelineConfig=$cfgSoft"
          )
          try {
            [void](Invoke-UeLogged -Exe $UeMrq -ArgumentList $mrqArgs -LogPath $MrqLog `
              -Phase "Phase C[$slotIndex] MRQ $systemName" -HeartbeatSeconds 20 `
              -TimeoutSec 420 -NoRedirect)
          } catch {
            $_ | Out-File -FilePath $MrqLog -Append
          }
          [void](Wait-MrqOutputFrames -SeqOutDir $seqOutDir -ExpectFrames $expect `
            -Phase "Phase C[$slotIndex] $systemName retry" -TimeoutSec 180 `
            -EmptyAbortSec 30 -AcceptPartialStable -StableSeconds 6)
          $frameFiles = @(Get-ImageFiles -Root $seqOutDir)
        }
        if ($frameFiles.Count -eq 0) {
          $savedRoot = Join-Path $ProjectDir "Saved"
          $movieRenders = Join-Path $savedRoot "MovieRenders"
          $since = (Get-Date).AddMinutes(-90)
          $frameFiles = @(Find-RecentImages -Roots @($seqOutDir, $MrqRoot, $movieRenders, $savedRoot) -Since $since -NameHint $safeHint)
        }
        Write-Host "Phase C[$slotIndex] frames found=$($frameFiles.Count) out=$seqOutDir"
        if ($frameFiles.Count -eq 0) {
          [void]$allErrors.Add("mrq_no_frames:$systemName")
          Send-VellumProgress -Message "FAIL MRQ no frames $systemName"
          $slotIndex++
          continue
        }
        foreach ($f in $frameFiles) {
          if ($f.DirectoryName -ne $seqOutDir) {
            Copy-Item -Force -Path $f.FullName -Destination (Join-Path $seqOutDir $f.Name)
          }
        }

        $HeroJson = Join-Path $OutDir "heroes-$slotIndex.json"
        $py = Get-Command python -ErrorAction SilentlyContinue
        if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
        if (-not $py) { throw "python/py not found on PATH for pick_heroes.py" }
        Send-VellumProgress -Message "Phase C[$slotIndex] pick heroes $systemName"
        # Do not redirect native stdout with *>$null - PowerShell can hang after
        # python exits (observed after heroes-0.json was already written).
        $pickArgs = @($StagedPickHeroesPy, $seqOutDir, "--json-out", $HeroJson, "--score-budget", "8")
        if (Test-Path $HeroJson) { Remove-Item -Force $HeroJson -ErrorAction SilentlyContinue }
        $pickProc = Start-Process -FilePath $py.Source -ArgumentList $pickArgs `
          -PassThru -WindowStyle Hidden
        $pickPid = [int]$pickProc.Id
        $pickProc = $null
        $pickDeadline = (Get-Date).AddMinutes(5)
        $pickLastBeat = Get-Date
        while ($null -ne (Get-Process -Id $pickPid -ErrorAction SilentlyContinue)) {
          if ((Get-Date) -gt $pickDeadline) {
            try { Stop-Process -Id $pickPid -Force -ErrorAction SilentlyContinue } catch { }
            Send-VellumProgress -Message "FAIL hero pick timeout $systemName"
            break
          }
          if (((Get-Date) - $pickLastBeat).TotalSeconds -ge 10) {
            Send-VellumProgress -Message "Phase C[$slotIndex] pick still running $systemName"
            $pickLastBeat = Get-Date
          }
          Start-Sleep -Seconds 2
        }
        if (-not (Test-Path $HeroJson)) {
          [void]$allErrors.Add("hero_pick_failed:$systemName")
          Send-VellumProgress -Message "FAIL hero pick $systemName (no json)"
          $slotIndex++
          continue
        }
        Send-VellumProgress -Message "Phase C[$slotIndex] heroes ready $systemName"
        $heroDoc = Get-Content $HeroJson -Raw | ConvertFrom-Json
        if (-not [bool]$heroDoc.ok) {
          [void]$allErrors.Add("hero_rejected:$systemName`:$($heroDoc.error)")
          Send-VellumProgress -Message "FAIL heroes $systemName $($heroDoc.error)"
          $slotIndex++
          continue
        }

        foreach ($h in @($heroDoc.heroes)) {
          $src = [string]$h.path
          if (-not (Test-Path $src)) { continue }
          $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
          $dest = Join-Path $StillsDir "$AssetId-$safeHint-$($h.role)-$stamp.png"
          Copy-Item -Force -Path $src -Destination $dest
          [void]$stills.Add(@{
              path        = $dest
              kind        = "niagara-render"
              system      = $systemName
              object_path = $objectPath
              method      = "mrq-batch"
              role        = [string]$h.role
              max_rgb     = [int]$h.max_rgb
              bytes       = (Get-Item $dest).Length
            })
          Write-Host "Hero $($h.role) -> $dest (max_rgb=$($h.max_rgb))"
        }
        [void]$sequences.Add(@{
            system = $systemName
            path   = $seqOutDir
            frames = [int]$heroDoc.frame_count
          })
        $sysHeroes = @($stills | Where-Object { $_.system -eq $systemName })
        Send-VellumProgress -Message "Phase C[$slotIndex] ingest $systemName"
        $nUp = Ingest-CapturedSystem -AssetId $AssetId -SystemName $systemName `
          -HeroStills $sysHeroes -SeqDir $seqOutDir -OutDir $OutDir `
          -VellumBase $VellumBase -Lanes $IngestLanes -Errors $allErrors
        if ($nUp -lt 1) {
          [void]$allErrors.Add("ingest_zero:$systemName")
          Send-VellumProgress -Message "FAIL ingest produced 0 uploads for $systemName"
        } else {
          Send-VellumProgress -Message "Captured $systemName heroes=$($heroDoc.heroes.Count) frames=$($heroDoc.frame_count) ingested=$nUp"
        }
        $slotIndex++
      }
    }
  }
}

# ---------------------------------------------------------------------------
# Ingest-only: local MRQ already on disk (interrupted pack resume). No wipe.
# ---------------------------------------------------------------------------
if ($toIngestOnly.Count -gt 0) {
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
  if (-not $py) { throw "python/py not found on PATH for pick_heroes.py" }
  $slotIndex = 1000
  foreach ($io in $toIngestOnly) {
    $systemName = [string]$io.asset_name
    $objectPath = [string]$io.object_path
    $safeHint = [string]$io.safe_name
    $seqOutDir = [string]$io.seq_dir
    $frameFiles = @(Get-ImageFiles -Root $seqOutDir)
    Send-VellumProgress -Message "Ingest-only[$slotIndex] $systemName frames=$($frameFiles.Count)"
    if ($frameFiles.Count -lt 30) {
      [void]$allErrors.Add("ingest_only_too_few:$systemName")
      $slotIndex++
      continue
    }
    $HeroJson = Join-Path $OutDir "heroes-ingest-$safeHint.json"
    if (Test-Path $HeroJson) { Remove-Item -Force $HeroJson -ErrorAction SilentlyContinue }
    $pickArgs = @($StagedPickHeroesPy, $seqOutDir, "--json-out", $HeroJson, "--score-budget", "8")
    $pickProc = Start-Process -FilePath $py.Source -ArgumentList $pickArgs -PassThru -WindowStyle Hidden
    $pickPid = [int]$pickProc.Id
    $pickProc = $null
    $pickDeadline = (Get-Date).AddMinutes(5)
    $pickLastBeat = Get-Date
    while ($null -ne (Get-Process -Id $pickPid -ErrorAction SilentlyContinue)) {
      if ((Get-Date) -gt $pickDeadline) {
        try { Stop-Process -Id $pickPid -Force -ErrorAction SilentlyContinue } catch { }
        Send-VellumProgress -Message "FAIL ingest-only pick timeout $systemName"
        break
      }
      if (((Get-Date) - $pickLastBeat).TotalSeconds -ge 10) {
        Send-VellumProgress -Message "Ingest-only pick still running $systemName"
        $pickLastBeat = Get-Date
      }
      Start-Sleep -Seconds 2
    }
    if (-not (Test-Path $HeroJson)) {
      [void]$allErrors.Add("ingest_only_hero_pick_failed:$systemName")
      $slotIndex++
      continue
    }
    $heroDoc = Get-Content $HeroJson -Raw | ConvertFrom-Json
    if (-not [bool]$heroDoc.ok) {
      [void]$allErrors.Add("ingest_only_hero_rejected:$systemName`:$($heroDoc.error)")
      $slotIndex++
      continue
    }
    foreach ($h in @($heroDoc.heroes)) {
      $src = [string]$h.path
      if (-not (Test-Path $src)) { continue }
      $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
      $dest = Join-Path $StillsDir "$AssetId-$safeHint-$($h.role)-$stamp.png"
      Copy-Item -Force -Path $src -Destination $dest
      [void]$stills.Add(@{
          path        = $dest
          kind        = "niagara-render"
          system      = $systemName
          object_path = $objectPath
          method      = "ingest-only"
          role        = [string]$h.role
          max_rgb     = [int]$h.max_rgb
          bytes       = (Get-Item $dest).Length
        })
    }
    [void]$sequences.Add(@{
        system = $systemName
        path   = $seqOutDir
        frames = [int]$heroDoc.frame_count
      })
    $sysHeroes = @($stills | Where-Object { $_.system -eq $systemName })
    Send-VellumProgress -Message "Ingest-only[$slotIndex] ingest $systemName"
    $nUp = Ingest-CapturedSystem -AssetId $AssetId -SystemName $systemName `
      -HeroStills $sysHeroes -SeqDir $seqOutDir -OutDir $OutDir `
      -VellumBase $VellumBase -Lanes $IngestLanes -Errors $allErrors
    if ($nUp -lt 1) {
      [void]$allErrors.Add("ingest_only_zero:$systemName")
    } else {
      Send-VellumProgress -Message "Ingest-only captured $systemName heroes=$($heroDoc.heroes.Count) ingested=$nUp"
    }
    $slotIndex++
  }
}

# ---------------------------------------------------------------------------
# Manifest + scratch (per-system ingest already completed above)
# ---------------------------------------------------------------------------
$vaultSkipOk = ($pickedSystems.Count -gt 0 -and $toRenderSystems.Count -eq 0 -and
  $toIngestOnly.Count -eq 0 -and $skippedVault.Count -gt 0)
$targetNames = New-Object System.Collections.Generic.HashSet[string]
foreach ($sys in $toRenderSystems) { [void]$targetNames.Add([string]$sys.asset_name) }
foreach ($io in $toIngestOnly) { [void]$targetNames.Add([string]$io.asset_name) }
$gotNames = New-Object System.Collections.Generic.HashSet[string]
foreach ($s in $stills) { if ($s.system) { [void]$gotNames.Add([string]$s.system) } }
$missing = @($targetNames | Where-Object { -not $gotNames.Contains($_) })
$coverageOk = ($targetNames.Count -eq 0) -or ($missing.Count -eq 0)
$Manifest = Join-Path $OutDir "manifest.json"
$man = @{
  schema_version        = 1
  tool                  = "vellum_capture"
  mode                  = "mrq-sequencer"
  asset_id              = $AssetId
  content_root          = $ContentRoot
  niagara_systems_found = [int]$inv.niagara_systems_found
  niagara_systems       = $inv.niagara_systems
  stills                = @($stills)
  sequences             = @($sequences)
  skipped_vault         = @($skippedVault)
  ingest_only           = @($toIngestOnly | ForEach-Object { $_.asset_name })
  render_systems        = @($toRenderSystems | ForEach-Object { $_.asset_name })
  missing_systems       = @($missing)
  force_capture         = [bool]$ForceCapture
  inventory_from_cache  = [bool]$inventoryFromCache
  errors                = @($allErrors)
  stills_attempted      = ($toRenderSystems.Count -gt 0 -or $toIngestOnly.Count -gt 0)
  ok                    = (($coverageOk -and $allErrors.Count -eq 0) -or $vaultSkipOk)
  partial               = ((-not $coverageOk) -and ($gotNames.Count -gt 0))
  ingest_policy         = "per_system"
  skip_policy           = "trusted_mrq_batch_after_cutoff+trusted_ingest_only"
}
($man | ConvertTo-Json -Depth 8) | Set-Content -Path $Manifest -Encoding utf8

$errJoin = (@($allErrors) -join "; ")
$notes = ("auto-capture(mrq-sequencer) systems={0} stills={1} sequences={2} vault_skip={3} render={4} errors={5}" -f `
  $inv.niagara_systems_found, $stills.Count, $sequences.Count, $skippedVault.Count, `
  $toRenderSystems.Count, $errJoin)
Write-Host "Manifest mode=$($man.mode) stills=$($stills.Count) ok=$($man.ok)"
if ($errJoin) { Write-Host "Manifest errors: $errJoin" }
Send-VellumProgress -Message "Done stills=$($stills.Count) ok=$($man.ok)"

$scratchBody = @{
  asset_id             = $AssetId
  scratch_project_path = $ProjectDir
  engine_version       = $EngineVersion
  notes                = $notes
  intake_run_id        = $IntakeRunId
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$VellumBase/api/scratch/record" `
  -ContentType "application/json" -Body $scratchBody | Out-Null
Write-Host "Recorded scratch inspect for $AssetId"

$uploaded = @($stills).Count * @($IngestLanes).Count
Write-Host "Done. systems=$($inv.niagara_systems_found) uploaded_heroes=$uploaded ok=$($man.ok)"
if (-not $man.ok) { exit 2 }
exit 0
