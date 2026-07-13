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
  # Use ArrayList — List[object].Add(FileInfo) throws "Argument types do not match" on PS 5.1.
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
    Artifact gate: UnrealEditor -game often exits (or HasExited flaps) while MRQ
    is still writing PNGs. Done = stable frame count on disk, not process exit.
  #>
  param(
    [string]$SeqOutDir,
    [int]$ExpectFrames = 1,
    [int]$TimeoutSec = 1800,
    [int]$StableSeconds = 8,
    [string]$Phase = "MRQ frames"
  )
  if ($ExpectFrames -lt 1) { $ExpectFrames = 1 }
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  $lastCount = -1
  $stableSince = $null
  while ((Get-Date) -lt $deadline) {
    $n = @(Get-ImageFiles -Root $SeqOutDir).Count
    if ($n -ne $lastCount) {
      $lastCount = $n
      $stableSince = Get-Date
      Send-VellumProgress -Message "$Phase frames=$n (want>=$ExpectFrames)"
    } elseif ($n -ge $ExpectFrames -and $null -ne $stableSince) {
      $stableFor = ((Get-Date) - $stableSince).TotalSeconds
      if ($stableFor -ge $StableSeconds) {
        Send-VellumProgress -Message "$Phase ready frames=$n"
        return $n
      }
    }
    # Also treat MoviePipeline log "Finished rendering" + any frames as success
    # when ExpectFrames is approximate (warm-up frames etc.).
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

function Send-VellumProgress {
  param(
    [string]$Message,
    [string]$LogPath = ""
  )
  Write-Host $Message
  if (-not $JobId -or -not $VellumBase) { return }
  $tail = ""
  if ($LogPath -and (Test-Path $LogPath)) {
    try {
      $tail = ((Get-Content -Path $LogPath -Tail 12 -ErrorAction SilentlyContinue) -join "`n")
    } catch { $tail = "" }
  }
  $body = @{ message = $Message; log_tail = $tail } | ConvertTo-Json -Compress
  try {
    Invoke-RestMethod -Method Post -Uri "$VellumBase/api/jobs/$JobId/progress" `
      -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 5 | Out-Null
  } catch {
    # Progress is best-effort; never fail the capture on heartbeat errors.
  }
}

function Invoke-UeLogged {
  # Start UE, stream stdout/stderr to a log, heartbeat progress until exit.
  param(
    [string]$Exe,
    [string[]]$ArgumentList,
    [string]$LogPath,
    [string]$Phase,
    [int]$HeartbeatSeconds = 15
  )
  if (Test-Path $LogPath) { Remove-Item -Force $LogPath }
  $errPath = "$LogPath.stderr"
  if (Test-Path $errPath) { Remove-Item -Force $errPath }
  Send-VellumProgress -Message "$Phase starting" -LogPath $LogPath
  $proc = Start-Process -FilePath $Exe -ArgumentList $ArgumentList `
    -PassThru -NoNewWindow `
    -RedirectStandardOutput $LogPath `
    -RedirectStandardError $errPath
  $started = Get-Date
  while ($true) {
    # Process.HasExited is stale until Refresh — without this the runner
    # can sit forever after Unreal exits (nothing visible on the host).
    try { $proc.Refresh() } catch { }
    if ($proc.HasExited) { break }
    $exited = $false
    try {
      $exited = $proc.WaitForExit([Math]::Max(1000, $HeartbeatSeconds * 1000))
    } catch {
      Start-Sleep -Seconds $HeartbeatSeconds
    }
    try { $proc.Refresh() } catch { }
    if ($exited -or $proc.HasExited) { break }
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    if (Test-Path $errPath) {
      Get-Content $errPath -ErrorAction SilentlyContinue | Add-Content -Path $LogPath -ErrorAction SilentlyContinue
      Clear-Content $errPath -ErrorAction SilentlyContinue
    }
    Send-VellumProgress -Message "$Phase still running (${elapsed}s)" -LogPath $LogPath
  }
  if (Test-Path $errPath) {
    Get-Content $errPath -ErrorAction SilentlyContinue | Add-Content -Path $LogPath -ErrorAction SilentlyContinue
  }
  $code = 0
  try {
    $proc.Refresh()
    $code = $proc.ExitCode
  } catch { $code = 0 }
  if ($null -eq $code) { $code = 0 }
  Send-VellumProgress -Message "$Phase exited code=$code" -LogPath $LogPath
  return $code
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
  if (-not $lines) { return "(no screenshot/map-ready lines in log — cmdline HighResShot echo ignored)" }
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
  # Epic cmdline requires /Game/Path/Asset.Asset — package path alone often exits 0 with zero frames.
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
  foreach ($still in $HeroStills) {
    $path = [string]$still.path
    if (-not (Test-Path $path)) { continue }
    foreach ($laneName in $Lanes) {
      $null = & curl.exe -sS -X POST "$VellumBase/api/lookdev/ingest-render" `
        -F "asset_id=$AssetId" `
        -F "lane=$laneName" `
        -F "note=auto Niagara MRQ $($still.role) via mrq-batch" `
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
  }
  if ((Test-Path $SeqDir)) {
    $zipPath = Join-Path $OutDir ("seq-" + (Safe-Name $SystemName) + ".zip")
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    Compress-Archive -Path (Join-Path $SeqDir "*") -DestinationPath $zipPath -Force
    foreach ($laneName in $Lanes) {
      $null = & curl.exe -sS -X POST "$VellumBase/api/lookdev/ingest-sequence" `
        -F "asset_id=$AssetId" `
        -F "lane=$laneName" `
        -F "system_name=$SystemName" `
        -F "note=auto Niagara MRQ sequence via mrq-batch" `
        -F "archive=@$zipPath"
      if ($LASTEXITCODE -ne 0) {
        if ($Errors) {
          [void]$Errors.Add("ingest_sequence_failed:$SystemName`:$laneName")
        }
        Write-Host "WARNING ingest-sequence failed for $SystemName lane=$laneName"
        continue
      }
      Write-Host "Ingested sequence $SystemName -> $laneName"
    }
  }
  return $uploaded
}

function Get-LookdevOutputs {
  param([string]$VellumBase, [string]$AssetId)
  try {
    # Pull enough rows to cover a full pack (API default 50 is too small).
    $r = Invoke-RestMethod -Method Get `
      -Uri "$VellumBase/api/lookdev/outputs?asset_id=$AssetId&limit=200" -TimeoutSec 45
    if ($r.outputs) { return @($r.outputs) }
  } catch {
    Write-Host "WARNING: lookdev outputs fetch failed: $($_.Exception.Message)"
  }
  return @()
}

function Get-VaultCoveredSystemSet {
  # Fast set of system names that already have niagara-render on every required lane.
  param(
    [object[]]$Outputs,
    [string[]]$Lanes
  )
  $bySystem = @{}
  foreach ($o in @($Outputs)) {
    if ([string]$o.kind -ne "niagara-render") { continue }
    $lane = [string]$o.lane
    if ($Lanes -notcontains $lane) { continue }
    $blob = ("{0} {1} {2}" -f [string]$o.path, [string]$o.note, [string]$o.system_name)
    $names = [regex]::Matches($blob, 'NS_[A-Za-z0-9_]+') | ForEach-Object { $_.Value }
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
$Ue = $null

function Ensure-UeCmd {
  if ($script:Ue) { return $script:Ue }
  $script:Ue = Find-UeCmdFromHost -HostProfile $UeHost -Hint $UeCmd
  Write-Host "UE (Cmd): $script:Ue"
  return $script:Ue
}

Write-Host "Project: $ProjectUe"
Write-Host "MaxSystems=$MaxSystems (0=entire pack) Width=$Width Height=$Height MapPath=$MapPath"
Write-Host "Runner version: mrq-adaptive-frames (2026-07-13)"
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
  Send-VellumProgress -Message "Building Lookdev Studio map…"
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
    Write-Host "Inventory cache max_systems mismatch (cache=$cachedMax want=$MaxSystems) — refreshing"
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
# Phase A: inventory (use on-disk cache when fresh — avoid UE cold start)
# ---------------------------------------------------------------------------
$inv = $null
$inventoryFromCache = $false
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
# Skip systems already covered in vault (fast HashSet — no local PNG scans).
# ForceCapture / VELLUM_FORCE_CAPTURE re-renders everything.
# ---------------------------------------------------------------------------
$skippedVault = New-Object System.Collections.ArrayList
$toRenderSystems = New-Object System.Collections.ArrayList
$vaultCovered = New-Object 'System.Collections.Generic.HashSet[string]'
$skipSw = [System.Diagnostics.Stopwatch]::StartNew()
if (-not $ForceCapture -and $pickedSystems.Count -gt 0) {
  Send-VellumProgress -Message "Skip check: fetching vault lookdev…"
  $vaultOutputs = Get-LookdevOutputs -VellumBase $VellumBase -AssetId $AssetId
  $vaultCovered = Get-VaultCoveredSystemSet -Outputs $vaultOutputs -Lanes $IngestLanes
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
  [void]$toRenderSystems.Add($sys)
}
$skipSw.Stop()
Send-VellumProgress -Message ("Skip plan: render={0} vault_skip={1} force={2} cache={3} ({4}ms)" -f `
  $toRenderSystems.Count, $skippedVault.Count, [bool]$ForceCapture, [bool]$inventoryFromCache, $skipSw.ElapsedMilliseconds)
Write-Host ("Skip plan done in {0}ms render={1} vault_skip={2}" -f `
  $skipSw.ElapsedMilliseconds, $toRenderSystems.Count, $skippedVault.Count)

if ($toRenderSystems.Count -eq 0) {
  Send-VellumProgress -Message "No Unreal author/MRQ needed (vault already covered or nothing picked)"
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

      $UeMrq = Find-UeEditor -CmdPath $Ue
      Write-Host "Phase C UE binary: $UeMrq"

      if ($queueSoft) {
        Write-Host "Phase C queue MRQ queue=$queueSoft map=$mapSoft jobs=$($authoredJobs.Count)"
        $MrqLog = Join-Path $OutDir "ue-mrq-batch.log"
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
          "-stdout",
          "-FullStdOutLogOutput",
          "-allowStdOutLogVerbosity",
          "-MoviePipelineConfig=$queueSoft"
        )
        $mrqExit = 0
        try {
          $mrqExit = Invoke-UeLogged -Exe $UeMrq -ArgumentList $mrqArgs -LogPath $MrqLog `
            -Phase "Phase C batch MRQ" -HeartbeatSeconds 20
        } catch {
          $mrqExit = 1
          $_ | Out-File -FilePath $MrqLog -Append
        }
        Write-Host "Phase C batch MRQ process exit=$mrqExit (artifacts are the gate)"
        # Do NOT trust exit code — wait for frames for each authored system next.
        $renderedOk = $true
      } else {
        Write-Host "Phase C: no queue_path from author — falling back to per-system MRQ"
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
        # Parent -game process may already have exited; poll disk until stable.
        $frameCount = Wait-MrqOutputFrames -SeqOutDir $seqOutDir -ExpectFrames $expect `
          -Phase "Phase C[$slotIndex] $systemName" -TimeoutSec 900
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
            "-stdout",
            "-FullStdOutLogOutput",
            "-allowStdOutLogVerbosity",
            "-LevelSequence=$seqSoft",
            "-MoviePipelineConfig=$cfgSoft"
          )
          try {
            [void](Invoke-UeLogged -Exe $UeMrq -ArgumentList $mrqArgs -LogPath $MrqLog `
              -Phase "Phase C[$slotIndex] MRQ $systemName" -HeartbeatSeconds 20)
          } catch {
            $_ | Out-File -FilePath $MrqLog -Append
          }
          [void](Wait-MrqOutputFrames -SeqOutDir $seqOutDir -ExpectFrames $expect `
            -Phase "Phase C[$slotIndex] $systemName retry" -TimeoutSec 900)
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
        & $py.Source $StagedPickHeroesPy $seqOutDir --json-out $HeroJson *> $null
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $HeroJson)) {
          [void]$allErrors.Add("hero_pick_failed:$systemName")
          $slotIndex++
          continue
        }
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
# Manifest + scratch (per-system ingest already completed above)
# ---------------------------------------------------------------------------
$vaultSkipOk = ($pickedSystems.Count -gt 0 -and $toRenderSystems.Count -eq 0 -and
  $skippedVault.Count -gt 0)
$partialOk = ($stills.Count -gt 0)
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
  render_systems        = @($toRenderSystems | ForEach-Object { $_.asset_name })
  force_capture         = [bool]$ForceCapture
  inventory_from_cache  = [bool]$inventoryFromCache
  errors                = @($allErrors)
  stills_attempted      = ($toRenderSystems.Count -gt 0)
  ok                    = ($partialOk -or $vaultSkipOk)
  ingest_policy         = "per_system"
  skip_policy           = "vault_hashset"
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
