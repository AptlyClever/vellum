#Requires -Version 5.1
<#
.SYNOPSIS
  Unsupervised Fireworks scratch inspect + still capture -> Vellum.

.DESCRIPTION
  Phase A (editor Cmd): inventory Niagara systems.
  Phase B (editor Cmd): bake one system into a capture map and write a PNG via
  SceneCapture2D + export_render_target. The old `-game` HighResShot path is
  gone — on this workstation the game window stayed blank and wrote zero PNGs.

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
  [int]$MaxSystems = $(if ($env:VELLUM_MAX_SYSTEMS) { [int]$env:VELLUM_MAX_SYSTEMS } else { 3 }),
  [int]$Width = $(if ($env:VELLUM_WIDTH) { [int]$env:VELLUM_WIDTH } else { 1920 }),
  [int]$Height = $(if ($env:VELLUM_HEIGHT) { [int]$env:VELLUM_HEIGHT } else { 1080 }),
  [string]$MapPath = "/Game/Vellum/Maps/VellumNiagaraCapture",
  [string]$JobId = $(if ($env:VELLUM_JOB_ID) { $env:VELLUM_JOB_ID } else { "" })
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
  while (-not $proc.HasExited) {
    Start-Sleep -Seconds $HeartbeatSeconds
    if ($proc.HasExited) { break }
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    # Merge stderr into main log so Select-String / Tee readers see everything.
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
  try { $code = $proc.ExitCode } catch { $code = 0 }
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

function ConvertTo-UePath([string]$Path) {
  return (($Path -replace '\\', '/').TrimEnd('/'))
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

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$InventoryPySource = Join-Path $PSScriptRoot "vellum_capture.py"
$AuthorPySource = Join-Path $PSScriptRoot "vellum_capture_mrq_author.py"
$PickHeroesPy = Join-Path $PSScriptRoot "pick_heroes.py"
if (-not (Test-Path $InventoryPySource)) { throw "vellum_capture.py not found next to runner" }
if (-not (Test-Path $AuthorPySource)) { throw "vellum_capture_mrq_author.py not found next to runner" }
if (-not (Test-Path $PickHeroesPy)) { throw "pick_heroes.py not found next to runner" }
if (-not $Project) {
  $Project = Resolve-UprojectFromHost -HostProfile $UeHost
}
if (-not (Test-Path $Project)) { throw "Project not found: $Project" }

$Ue = Find-UeCmdFromHost -HostProfile $UeHost -Hint $UeCmd
$ProjectDir = Split-Path $Project -Parent
$OutDir = Join-Path $ProjectDir "Saved\VellumCapture"
$StillsDir = Join-Path $OutDir "stills"
$MrqRoot = Join-Path $OutDir "mrq"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path $StillsDir | Out-Null
New-Item -ItemType Directory -Force -Path $MrqRoot | Out-Null

$StagedInventoryPy = Join-Path $OutDir "vellum_capture.py"
$StagedAuthorPy = Join-Path $OutDir "vellum_capture_mrq_author.py"
$StagedPickHeroesPy = Join-Path $OutDir "pick_heroes.py"
Copy-Item -Force -Path $InventoryPySource -Destination $StagedInventoryPy
Copy-Item -Force -Path $AuthorPySource -Destination $StagedAuthorPy
Copy-Item -Force -Path $PickHeroesPy -Destination $StagedPickHeroesPy

$ProjectUe = ConvertTo-UePath $Project
$OutDirUe = ConvertTo-UePath $OutDir
$FrameCount = 120
$FrameRate = 30
$IngestLanes = @("slots", "hail-overlay")

Write-Host "UE (Cmd): $Ue"
Write-Host "Project: $ProjectUe"
Write-Host "MaxSystems=$MaxSystems Width=$Width Height=$Height MapPath=$MapPath"
Write-Host "Runner version: mrq-sequencer (2026-07-13)"
Write-Host "UE host: $($UeHost.id) ($($UeHost.label))"
Write-Host "Ingest lanes: $($IngestLanes -join ', ')"
if ($JobId) { Write-Host "JobId=$JobId (progress -> $VellumBase/api/jobs/$JobId/progress)" }

$allErrors = New-Object System.Collections.ArrayList
$stills = New-Object System.Collections.ArrayList
$sequences = New-Object System.Collections.ArrayList

# ---------------------------------------------------------------------------
# Phase A: inventory
# ---------------------------------------------------------------------------
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
if ($inv.errors) { foreach ($e in @($inv.errors)) { [void]$allErrors.Add("inventory:$e") } }
if ($inv.content_root) { $ContentRoot = [string]$inv.content_root }
$pickedSystems = @($inv.niagara_systems)
Write-Host "Inventory systems_found=$($inv.niagara_systems_found) picked=$($pickedSystems.Count) content_root=$ContentRoot"
Send-VellumProgress -Message "Inventory done: found=$($inv.niagara_systems_found) picked=$($pickedSystems.Count) root=$ContentRoot"
if ($pickedSystems.Count -eq 0) {
  [void]$allErrors.Add("no_systems_to_capture")
}

# ---------------------------------------------------------------------------
# Phase B/C: author Sequencer+MRQ config, then cmdline MRQ render per system.
# ---------------------------------------------------------------------------
$slotIndex = 0
foreach ($sys in $pickedSystems) {
  $systemName = [string]$sys.asset_name
  $objectPath = [string]$sys.object_path
  $safeHint = Safe-Name $systemName
  $seqOutDir = Join-Path $MrqRoot $safeHint
  New-Item -ItemType Directory -Force -Path $seqOutDir | Out-Null
  # Clear prior frames for this system
  Get-ChildItem -Path $seqOutDir -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

  Write-Host "Phase B [$slotIndex] author MRQ $objectPath"
  $job = @{
    asset_id           = $AssetId
    map_path           = $MapPath
    system_object_path = $objectPath
    system_name        = $systemName
    slot_index         = $slotIndex
    width              = $Width
    height             = $Height
    frame_count        = $FrameCount
    frame_rate         = $FrameRate
    output_dir         = (ConvertTo-UePath $seqOutDir)
    sequence_package   = "/Game/Vellum/Sequences"
    config_package     = "/Game/Vellum/MRQ"
  }
  $JobPath = Join-Path $OutDir "job.json"
  ($job | ConvertTo-Json) | Set-Content -Path $JobPath -Encoding utf8
  $env:VELLUM_JOB_JSON = ConvertTo-UePath $JobPath
  $env:VELLUM_OUT_DIR = $OutDirUe

  $AuthorLog = Join-Path $OutDir "ue-author-$slotIndex.log"
  if (Test-Path $AuthorLog) { Remove-Item -Force $AuthorLog }
  $AuthorExecFlag = "-ExecutePythonScript=" + (ConvertTo-UePath $StagedAuthorPy)
  $authorExit = 0
  try {
    $authorExit = Invoke-UeLogged -Exe $Ue -ArgumentList @(
        $ProjectUe, "-stdout", "-FullStdOutLogOutput", "-unattended", "-nop4", $AuthorExecFlag
      ) -LogPath $AuthorLog -Phase "Phase B[$slotIndex] author $systemName"
  } catch {
    $authorExit = 1
    $_ | Out-File -FilePath $AuthorLog -Append
    Send-VellumProgress -Message "Phase B[$slotIndex] author crashed: $_" -LogPath $AuthorLog
  }

  $AuthorResultPath = Join-Path $OutDir "author-result.json"
  if (-not (Test-Path $AuthorResultPath)) {
    [void]$allErrors.Add("author_no_result:$systemName`:exit=$authorExit")
    Send-VellumProgress -Message "FAIL author $systemName (no result)" -LogPath $AuthorLog
    break
  }
  $author = Get-Content $AuthorResultPath -Raw | ConvertFrom-Json
  if ($author.errors) { foreach ($e in @($author.errors)) { [void]$allErrors.Add("author:$systemName`:$e") } }
  if (-not [bool]$author.ok) {
    [void]$allErrors.Add("author_failed:$systemName")
    Send-VellumProgress -Message "FAIL author $systemName" -LogPath $AuthorLog
    break
  }

  $seqPath = [string]$author.sequence_asset
  $cfgPath = [string]$author.config_asset
  $mapForRender = [string]$author.map_path
  Write-Host "Phase C [$slotIndex] cmdline MRQ seq=$seqPath cfg=$cfgPath"

  $MrqLog = Join-Path $OutDir "ue-mrq-$slotIndex.log"
  if (Test-Path $MrqLog) { Remove-Item -Force $MrqLog }
  $mrqArgs = @(
    $ProjectUe,
    $mapForRender,
    "-game",
    "-windowed",
    "-ResX=$Width",
    "-ResY=$Height",
    "-nosplash",
    "-nop4",
    "-log",
    "-stdout",
    "-FullStdOutLogOutput",
    "-LevelSequence=$seqPath",
    "-MoviePipelineConfig=$cfgPath"
  )
  $mrqExit = 0
  try {
    $mrqExit = Invoke-UeLogged -Exe $Ue -ArgumentList $mrqArgs -LogPath $MrqLog `
      -Phase "Phase C[$slotIndex] MRQ $systemName" -HeartbeatSeconds 20
  } catch {
    $mrqExit = 1
    $_ | Out-File -FilePath $MrqLog -Append
    Send-VellumProgress -Message "Phase C[$slotIndex] MRQ crashed: $_" -LogPath $MrqLog
  }

  $frameFiles = @(Get-ImageFiles -Root $seqOutDir)
  if ($frameFiles.Count -eq 0) {
    # MRQ sometimes writes under Saved/MovieRenders — sweep recent images
    $savedRoot = Join-Path $ProjectDir "Saved"
    $since = (Get-Date).AddMinutes(-30)
    $frameFiles = @(Find-RecentImages -Roots @($seqOutDir, $MrqRoot, $savedRoot) -Since $since -NameHint $safeHint)
  }
  Write-Host "Phase C [$slotIndex] frames found=$($frameFiles.Count) exit=$mrqExit"
  if ($frameFiles.Count -eq 0) {
    [void]$allErrors.Add("mrq_no_frames:$systemName`:exit=$mrqExit")
    Send-VellumProgress -Message "FAIL MRQ no frames $systemName" -LogPath $MrqLog
    break
  }

  # Normalize frames into seqOutDir for zip/heroes
  foreach ($f in $frameFiles) {
    if ($f.DirectoryName -ne $seqOutDir) {
      Copy-Item -Force -Path $f.FullName -Destination (Join-Path $seqOutDir $f.Name)
    }
  }

  $HeroJson = Join-Path $OutDir "heroes-$slotIndex.json"
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
  if (-not $py) { throw "python/py not found on PATH for pick_heroes.py" }
  & $py.Source $StagedPickHeroesPy $seqOutDir --json-out $HeroJson
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $HeroJson)) {
    [void]$allErrors.Add("hero_pick_failed:$systemName")
    break
  }
  $heroDoc = Get-Content $HeroJson -Raw | ConvertFrom-Json
  if (-not [bool]$heroDoc.ok) {
    [void]$allErrors.Add("hero_rejected:$systemName`:$($heroDoc.error)")
    Send-VellumProgress -Message "FAIL heroes $systemName $($heroDoc.error)"
    break
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
        method      = "mrq-sequencer"
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
  Send-VellumProgress -Message "Captured $systemName heroes=$($heroDoc.heroes.Count) frames=$($heroDoc.frame_count)"
  $slotIndex++
}

# ---------------------------------------------------------------------------
# Manifest + scratch + ingest (slots + hail-overlay)
# ---------------------------------------------------------------------------
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
  errors                = @($allErrors)
  stills_attempted      = $true
  ok                    = ($stills.Count -gt 0)
}
($man | ConvertTo-Json -Depth 8) | Set-Content -Path $Manifest -Encoding utf8

$errJoin = (@($allErrors) -join "; ")
$notes = "auto-capture(mrq-sequencer) systems=$($inv.niagara_systems_found) stills=$($stills.Count) sequences=$($sequences.Count) errors=$errJoin"
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

$uploaded = 0
foreach ($still in $stills) {
  $path = [string]$still.path
  if (-not (Test-Path $path)) { continue }
  foreach ($laneName in $IngestLanes) {
    & curl.exe -sS -X POST "$VellumBase/api/lookdev/ingest-render" `
      -F "asset_id=$AssetId" `
      -F "lane=$laneName" `
      -F "note=auto Niagara MRQ $($still.role) via mrq-sequencer" `
      -F "file=@$path"
    if ($LASTEXITCODE -ne 0) { throw "ingest-render failed for $path lane=$laneName" }
    $uploaded++
    Write-Host "Ingested hero $path -> $laneName"
  }
}

foreach ($seq in $sequences) {
  $seqDir = [string]$seq.path
  $sysName = [string]$seq.system
  if (-not (Test-Path $seqDir)) { continue }
  $zipPath = Join-Path $OutDir ("seq-" + (Safe-Name $sysName) + ".zip")
  if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
  Compress-Archive -Path (Join-Path $seqDir "*") -DestinationPath $zipPath -Force
  foreach ($laneName in $IngestLanes) {
    & curl.exe -sS -X POST "$VellumBase/api/lookdev/ingest-sequence" `
      -F "asset_id=$AssetId" `
      -F "lane=$laneName" `
      -F "system_name=$sysName" `
      -F "note=auto Niagara MRQ sequence via mrq-sequencer" `
      -F "archive=@$zipPath"
    if ($LASTEXITCODE -ne 0) { throw "ingest-sequence failed for $sysName lane=$laneName" }
    Write-Host "Ingested sequence $sysName -> $laneName"
  }
}

Write-Host "Done. systems=$($inv.niagara_systems_found) uploaded_heroes=$uploaded ok=$($man.ok)"
if (-not $man.ok) { exit 2 }
exit 0
