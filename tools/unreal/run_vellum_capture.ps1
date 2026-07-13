#Requires -Version 5.1
<#
.SYNOPSIS
  Unsupervised Fireworks scratch inspect + still capture -> Vellum.

.DESCRIPTION
  Two Unreal phases, because UnrealEditor-Cmd has no live viewport under
  -unattended (HighResShot / editor SceneCapture2D both returned empty PNGs —
  see docs/scratch-inspect-niagara.md):

  Phase A (editor, -ExecutePythonScript):
    tools/unreal/vellum_capture.py — inventory only. Lists Niagara systems
    under -ContentRoot, picks up to -MaxSystems, writes manifest-inventory.json.

  Phase B, once per picked system (editor bake + real -game shot):
    1) tools/unreal/vellum_capture_bake_map.py (editor, -ExecutePythonScript)
       bakes that ONE system + a light + an auto-activating camera into
       /Game/Vellum/Maps/VellumNiagaraCapture (property-driven; no Blueprint
       graph, no GameMode code — see the script's header comment for why).
    2) UnrealEditor-Cmd.exe <uproject> <map> -game -windowed -ResX -ResY
       -unattended -ExecCmds="HighResShot <res>,quit" — a real game-mode
       render loop actually produces a PNG under Saved/Screenshots/.

  Manifests are merged into Saved/VellumCapture/manifest.json (same shape
  vellum_ue_agent.ps1 already reads), PNGs are ingested via
  /api/lookdev/ingest-render, and a scratch/record note is posted.

  One-time setup on the Windows box:
  - Enable Python Editor Script Plugin in the VellumImport project
  - Set VELLUM_UE_CMD if UnrealEditor-Cmd is not under a default path
  - No manual map/Blueprint authoring needed — the bake script creates/
    overwrites the capture map on every run.

.EXAMPLE
  pwsh -File tools/unreal/run_vellum_capture.ps1
#>
param(
  [string]$Project = "C:\epic\VellumImport\VellumImport.uproject",
  [string]$AssetId = "fireworks-vol-1-niagara",
  [string]$ContentRoot = "/Game/FireworksV1",
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$Lane = "slots",
  [string]$EngineVersion = "5.8",
  [string]$IntakeRunId = "",
  [string]$UeCmd = $env:VELLUM_UE_CMD,
  [int]$MaxSystems = $(if ($env:VELLUM_MAX_SYSTEMS) { [int]$env:VELLUM_MAX_SYSTEMS } else { 3 }),
  [int]$Width = $(if ($env:VELLUM_WIDTH) { [int]$env:VELLUM_WIDTH } else { 1920 }),
  [int]$Height = $(if ($env:VELLUM_HEIGHT) { [int]$env:VELLUM_HEIGHT } else { 1080 }),
  [string]$MapPath = "/Game/Vellum/Maps/VellumNiagaraCapture",
  [string]$JobId = $(if ($env:VELLUM_JOB_ID) { $env:VELLUM_JOB_ID } else { "" })
)

$ErrorActionPreference = "Stop"

function Find-UeCmd {
  param([string]$Hint)
  if ($Hint -and (Test-Path $Hint)) { return (Resolve-Path $Hint).Path }
  $candidates = @(
    "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    "C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    "C:\Program Files\Epic Games\UE_5.6\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
    "C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
  )
  foreach ($c in $candidates) {
    if (Test-Path $c) { return $c }
  }
  throw "UnrealEditor-Cmd.exe not found. Set VELLUM_UE_CMD to the full path."
}

function Find-UeEditor {
  param([string]$CmdPath)
  # -game stills need a real presented swapchain. UnrealEditor-Cmd -unattended
  # often never flushes HighResShot. Prefer the GUI binary beside Cmd.
  if ($CmdPath -and $CmdPath -match "UnrealEditor-Cmd\.exe$") {
    $gui = $CmdPath -replace "UnrealEditor-Cmd\.exe$", "UnrealEditor.exe"
    if (Test-Path $gui) { return $gui }
  }
  foreach ($c in @(
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
  $lines = Select-String -Path $LogPath -Pattern "HighResShot|Screenshot|Shot |Writing|filename=|Error:|Fatal|LogViewport|LogRenderer" -ErrorAction SilentlyContinue |
    Select-Object -Last 40 |
    ForEach-Object { $_.Line }
  if (-not $lines) { return "(no HighResShot/Screenshot lines in log)" }
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
$BakePySource = Join-Path $PSScriptRoot "vellum_capture_bake_map.py"
if (-not (Test-Path $InventoryPySource)) { throw "vellum_capture.py not found next to runner" }
if (-not (Test-Path $BakePySource)) { throw "vellum_capture_bake_map.py not found next to runner" }
if (-not (Test-Path $Project)) { throw "Project not found: $Project" }

$Ue = Find-UeCmd -Hint $UeCmd
$UeGame = Find-UeEditor -CmdPath $Ue
$ProjectDir = Split-Path $Project -Parent
$OutDir = Join-Path $ProjectDir "Saved\VellumCapture"
$StillsDir = Join-Path $OutDir "stills"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path $StillsDir | Out-Null

# Stage scripts INSIDE the project so ExecutePythonScript never sees \tools (tab).
$StagedInventoryPy = Join-Path $OutDir "vellum_capture.py"
$StagedBakePy = Join-Path $OutDir "vellum_capture_bake_map.py"
Copy-Item -Force -Path $InventoryPySource -Destination $StagedInventoryPy
Copy-Item -Force -Path $BakePySource -Destination $StagedBakePy

$ProjectUe = ConvertTo-UePath $Project
$OutDirUe = ConvertTo-UePath $OutDir

Write-Host "UE (editor/inventory): $Ue"
Write-Host "UE (game stills): $UeGame"
Write-Host "Project: $ProjectUe"
Write-Host "MaxSystems=$MaxSystems Width=$Width Height=$Height MapPath=$MapPath"
Write-Host "Runner version: game-mode-progress-heartbeat (2026-07-13)"
if ($JobId) { Write-Host "JobId=$JobId (progress -> $VellumBase/api/jobs/$JobId/progress)" }

$allErrors = New-Object System.Collections.ArrayList
$stills = New-Object System.Collections.ArrayList

# ---------------------------------------------------------------------------
# Phase A: inventory only (editor Python; existing proven path).
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
Inventory did not write manifest-inventory.json under $OutDir (runner=game-mode-capture-map).
Unreal exit=$ueExit staged=$StagedInventoryPy

LogPython snippet:
$logTail
"@
}

$inv = Get-Content $InventoryManifestPath -Raw | ConvertFrom-Json
if ($inv.errors) { foreach ($e in @($inv.errors)) { [void]$allErrors.Add("inventory:$e") } }
$pickedSystems = @($inv.niagara_systems)
Write-Host "Inventory systems_found=$($inv.niagara_systems_found) picked=$($pickedSystems.Count)"
Send-VellumProgress -Message "Inventory done: found=$($inv.niagara_systems_found) picked=$($pickedSystems.Count)"
if ($pickedSystems.Count -eq 0) {
  [void]$allErrors.Add("no_systems_to_bake")
}

# ---------------------------------------------------------------------------
# Phase B: bake + `-game` shot, once per picked system.
# ---------------------------------------------------------------------------
$slotIndex = 0
foreach ($sys in $pickedSystems) {
  $systemName = [string]$sys.asset_name
  $objectPath = [string]$sys.object_path
  Write-Host "Phase B [$slotIndex] baking $objectPath"

  $job = @{
    asset_id            = $AssetId
    map_path            = $MapPath
    system_object_path  = $objectPath
    system_name         = $systemName
    slot_index          = $slotIndex
    width               = $Width
    height              = $Height
  }
  $JobPath = Join-Path $OutDir "job.json"
  ($job | ConvertTo-Json) | Set-Content -Path $JobPath -Encoding utf8

  $env:VELLUM_JOB_JSON = ConvertTo-UePath $JobPath
  $env:VELLUM_OUT_DIR = $OutDirUe

  $BakeLog = Join-Path $OutDir "ue-bake-$slotIndex.log"
  if (Test-Path $BakeLog) { Remove-Item -Force $BakeLog }
  $BakeExecFlag = "-ExecutePythonScript=" + (ConvertTo-UePath $StagedBakePy)

  $bakeExit = 0
  try {
    $bakeExit = Invoke-UeLogged -Exe $Ue -ArgumentList @(
        $ProjectUe, "-stdout", "-FullStdOutLogOutput", "-unattended", "-nop4", $BakeExecFlag
      ) -LogPath $BakeLog -Phase "Phase B[$slotIndex] bake $systemName"
  } catch {
    $bakeExit = 1
    $_ | Out-File -FilePath $BakeLog -Append
    Send-VellumProgress -Message "Phase B[$slotIndex] bake crashed: $_" -LogPath $BakeLog
  }

  $BakeResultPath = Join-Path $OutDir "bake-result.json"
  $bakeOk = $false
  if (Test-Path $BakeResultPath) {
    $bakeResult = Get-Content $BakeResultPath -Raw | ConvertFrom-Json
    $bakeOk = [bool]$bakeResult.ok
    if ($bakeResult.errors) { foreach ($e in @($bakeResult.errors)) { [void]$allErrors.Add("bake:$systemName`:$e") } }
  } else {
    $logTail = Get-LogPythonSnippet (Get-Content $BakeLog -Raw -ErrorAction SilentlyContinue)
    [void]$allErrors.Add("bake_no_result:$systemName`:exit=$bakeExit`:$logTail")
  }

  if (-not $bakeOk) {
    Write-Host "Phase B [$slotIndex] bake failed for $systemName, skipping shot"
    Send-VellumProgress -Message "Phase B[$slotIndex] bake FAILED $systemName" -LogPath $BakeLog
    $slotIndex++
    continue
  }

  # Game stills: GUI UnrealEditor.exe (not Cmd), NO -unattended (that flag
  # often skips presenting a viewport so HighResShot never writes a file).
  # Do NOT put quit in the same ExecCmds as HighResShot (async flush race).
  $shotStart = Get-Date
  $GameLog = Join-Path $OutDir "ue-game-$slotIndex.log"
  if (Test-Path $GameLog) { Remove-Item -Force $GameLog }

  $safeHint = Safe-Name $systemName
  $stillLeaf = "VellumCapture/stills/$AssetId-$safeHint"
  # Fire HighResShot after a short console delay via multiple commands is
  # unreliable; WarmupTime on the component covers particle readiness.
  # Also issue plain `Shot` as a second chance (writes under Screenshots/).
  $ExecCmds = "r.MotionBlurQuality 0,HighResShot ${Width}x${Height} filename=$stillLeaf,Shot"

  $gameArgs = @(
    $ProjectUe,
    $MapPath,
    "-game",
    "-windowed",
    "-ResX=$Width",
    "-ResY=$Height",
    "-nosplash",
    "-nop4",
    "-ExecCmds=$ExecCmds"
  )
  Write-Host "Phase B [$slotIndex] GAME still via $UeGame (windowed, no -unattended)"
  Send-VellumProgress -Message "Phase B[$slotIndex] GAME still starting $systemName"

  $gameProc = $null
  $gameExit = 0
  try {
    $gameProc = Start-Process -FilePath $UeGame -ArgumentList $gameArgs -PassThru -WindowStyle Normal
    $settleSeconds = 10
    $waited = 0
    while (-not $gameProc.HasExited -and $waited -lt $settleSeconds) {
      Start-Sleep -Seconds 2
      $waited += 2
      Send-VellumProgress -Message "Phase B[$slotIndex] GAME settle ${waited}/${settleSeconds}s"
    }
    if (-not $gameProc.HasExited) {
      Write-Host "Phase B [$slotIndex] settle ${settleSeconds}s — stopping UE"
      try { Stop-Process -Id $gameProc.Id -Force -ErrorAction SilentlyContinue } catch { }
      try { $gameProc.WaitForExit(20000) | Out-Null } catch { }
    }
    try { $gameExit = $gameProc.ExitCode } catch { $gameExit = 0 }
    if ($null -eq $gameExit) { $gameExit = 0 }
    $engineLogs = Join-Path $ProjectDir "Saved\Logs"
    if (Test-Path $engineLogs) {
      $newestLog = Get-ChildItem $engineLogs -Filter "*.log" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
      if ($newestLog) { Copy-Item -Force $newestLog.FullName $GameLog }
    }
  } catch {
    $gameExit = 1
    $_ | Out-File -FilePath $GameLog -Append
  }
  Write-Host "Phase B [$slotIndex] -game exit code: $gameExit"
  Send-VellumProgress -Message "Phase B[$slotIndex] GAME exited code=$gameExit" -LogPath $GameLog

  $searchRoots = @(
    $StillsDir,
    (Join-Path $ProjectDir "Saved\VellumCapture\stills"),
    (Join-Path $ProjectDir "Saved\Screenshots"),
    (Join-Path $ProjectDir "Saved")
  )
  $recent = Find-RecentImages -Roots $searchRoots -Since $shotStart -NameHint $safeHint
  $newPng = $recent | Select-Object -First 1

  if (-not $newPng) {
    $tree = Get-SavedTreeSnippet -SavedRoot (Join-Path $ProjectDir "Saved")
    $shotLog = Get-LogShotSnippet -LogPath $GameLog
    [void]$allErrors.Add("no_png:$systemName`:exit=$gameExit")
    [void]$allErrors.Add("saved_images:`n$tree")
    [void]$allErrors.Add("shot_log:`n$shotLog")
    Write-Host "Phase B [$slotIndex] FAIL: no PNG after game still. Recent Saved/ images:"
    Write-Host $tree
    Write-Host "---- shot log snippet ----"
    Write-Host $shotLog
    Send-VellumProgress -Message "FAIL no_png $systemName" -LogPath $GameLog
    Write-Host "Failing fast — not baking remaining systems until one still works."
    break
  }

  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $dest = Join-Path $StillsDir "$AssetId-$safeHint-$stamp.png"
  if ($newPng.FullName -ne $dest) {
    Copy-Item -Force -Path $newPng.FullName -Destination $dest
  }
  [void]$stills.Add(@{
      path        = $dest
      kind        = "niagara-render"
      system      = $systemName
      object_path = $objectPath
      method      = "game-mode-gui-highresshot"
      source      = $newPng.FullName
    })
  Write-Host "Phase B [$slotIndex] captured still $dest (from $($newPng.FullName))"
  Send-VellumProgress -Message "Captured still $systemName -> $dest"

  $slotIndex++
}

# ---------------------------------------------------------------------------
# Merge manifests -> Saved/VellumCapture/manifest.json (shape vellum_ue_agent.ps1 reads).
# ---------------------------------------------------------------------------
$Manifest = Join-Path $OutDir "manifest.json"
$man = @{
  schema_version        = 1
  tool                  = "vellum_capture"
  mode                  = "game-mode-capture-map"
  asset_id              = $AssetId
  content_root          = $ContentRoot
  niagara_systems_found = [int]$inv.niagara_systems_found
  niagara_systems       = $inv.niagara_systems
  stills                = @($stills)
  errors                = @($allErrors)
  stills_attempted      = $true
  ok                    = ($stills.Count -gt 0)
}
($man | ConvertTo-Json -Depth 8) | Set-Content -Path $Manifest -Encoding utf8

$errJoin = (@($allErrors) -join "; ")
$notes = "auto-capture(game-mode) systems=$($inv.niagara_systems_found) stills=$($stills.Count) errors=$errJoin"
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
  & curl.exe -sS -X POST "$VellumBase/api/lookdev/ingest-render" `
    -F "asset_id=$AssetId" `
    -F "lane=$Lane" `
    -F "note=auto Niagara game-mode capture via vellum_capture_bake_map" `
    -F "file=@$path"
  if ($LASTEXITCODE -ne 0) { throw "ingest-render failed for $path" }
  $uploaded++
  Write-Host "Ingested $path"
}

Write-Host "Done. systems=$($inv.niagara_systems_found) uploaded_stills=$uploaded ok=$($man.ok)"
if (-not $man.ok) { exit 2 }
exit 0
