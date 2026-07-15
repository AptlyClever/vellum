#Requires -Version 7.0
<#
.SYNOPSIS
  One-shot reconcile: make Vellum, disk, vault, and Perforce agree about the Library.

.DESCRIPTION
  Push-based (no job queue, no agent loop). Safe to run any time; idempotent.

  1. Push a fresh Content scan to the hub (report_host_specs.ps1)
  2. Register any Content folders Vellum has never seen (orphans)
  3. Patch register rows that are on disk but missing host path / in_project
  4. Zip + stage-upload packs that are on disk but not in the vault
  5. p4 reconcile + submit Content changes
  6. Unreal load-check (inventory-pack) any pack without a manifest
  6b. Conversion Factory: factory-all (one UE boot: models+media+bake) for
      packs missing game-ready evidence; up to FactoryWorkers packs in parallel
      with isolated work dirs; smart zip upload to the hub
  7. Corrupt-package health scan
  8. Detect stray Unreal projects (Fab installed into the wrong project)
  9. Write an exception report; operator only ever reads the exceptions

.EXAMPLE
  pwsh -File tools/pipeline/reconcile_aurora.ps1
  pwsh -File tools/pipeline/reconcile_aurora.ps1 -SkipInventory
  pwsh -File tools/pipeline/reconcile_aurora.ps1 -InstallTask   # hourly scheduled task
#>
param(
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$ProjectRoot = "F:\Games\AuroraVellum",
  [string]$P4Port = "localhost:1666",
  [string]$P4User = "jaked",
  [string]$P4Client = "aurora-vellum-library",
  [int]$MaxInventoryPerRun = 40,
  [int]$MaxStagePerRun = 5,
  [int]$MaxFactoryPerRun = 30,
  [int]$FactoryWorkers = 3,
  [switch]$SkipInventory,
  [switch]$SkipFactory,
  [switch]$InstallTask
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$StateDir = Join-Path $ProjectRoot "Saved\VellumReconcile"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

if ($InstallTask) {
  $action = New-ScheduledTaskAction -Execute "pwsh.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
  $triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
        -RepetitionInterval (New-TimeSpan -Hours 1) `
        -RepetitionDuration (New-TimeSpan -Days 3650))
  )
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)
  Register-ScheduledTask -TaskName "VellumReconcile" -Action $action `
    -Trigger $triggers -Settings $settings -Force | Out-Null
  Write-Host "Scheduled task VellumReconcile registered (at logon + hourly)."
  return
}

# Single instance guard
$lockFile = Join-Path $StateDir "reconcile.lock"
if (Test-Path $lockFile) {
  $age = (Get-Date) - (Get-Item $lockFile).LastWriteTime
  if ($age.TotalHours -lt 3) { Write-Host "Another reconcile is running (lock age $([int]$age.TotalMinutes)m); exiting."; return }
  Remove-Item $lockFile -Force
}
Set-Content -Path $lockFile -Value $PID

$exceptions = New-Object System.Collections.Generic.List[object]
$actions = New-Object System.Collections.Generic.List[string]
function Add-Exception([string]$Kind, [string]$Subject, [string]$Detail, [string]$FixHint = "") {
  $exceptions.Add([ordered]@{ kind = $Kind; subject = $Subject; detail = $Detail; fix = $FixHint })
  Write-Warning "[$Kind] $Subject — $Detail"
}
$acceptedDungeonRuinsQuarantine = @(
  "Dungeon_Ruins/Assets/decor_07.uasset",
  "Dungeon_Ruins/Assets/Pillar_Base_02.uasset",
  "Dungeon_Ruins/Assets/Pillar_Base_03.uasset"
)
function Test-AcceptedQuarantine([string]$Path) {
  $norm = ($Path -replace "\\", "/").TrimStart("/")
  foreach ($accepted in $acceptedDungeonRuinsQuarantine) {
    if ($norm -ieq $accepted) { return $true }
  }
  return $false
}
# Load errors that can never be fixed: legacy UE4 'Rig' retarget assets in
# Paragon demo content — the Rig class was removed from UE 5.8 entirely.
$acceptedLoadErrors = @(
  "load_failed:/Game/SlashTrail_SoftTofu/Demo/ParagonKwang/Characters/Heroes/Kwang/Meshes/Paragon_Proto_Retarget.Paragon_Proto_Retarget",
  "load_failed:/Game/SlashTrail_SoftTofu/Demo/ParagonSunWukong/Characters/Heroes/Wukong/Meshes/Orion_Proto_Retarget.Orion_Proto_Retarget"
)
function Get-ActionableLoadErrors($LoadErrors) {
  return @(@($LoadErrors) | Where-Object { $_ -notin $acceptedLoadErrors })
}
function Invoke-Api([string]$Method, [string]$Path, $Body = $null) {
  $uri = "$VellumBase$Path"
  if ($null -ne $Body) {
    return Invoke-RestMethod -Method $Method -Uri $uri -ContentType "application/json" `
      -Body ($Body | ConvertTo-Json -Depth 8) -TimeoutSec 60
  }
  return Invoke-RestMethod -Method $Method -Uri $uri -TimeoutSec 60
}

try {
  # ---- 1. Fresh Content scan pushed to hub -----------------------------------
  Write-Host "== 1/8 host scan"
  try {
    & pwsh -NoProfile -File (Join-Path $RepoRoot "tools\unreal\report_host_specs.ps1") `
      -VellumBase $VellumBase | Out-Null
    $actions.Add("host_scan_pushed")
  } catch {
    Add-Exception "scan" "report_host_specs" $_.Exception.Message "Hub unreachable or scan script broken; nothing else can be trusted this run."
    throw
  }

  # ---- 1b. Push launcher Fab catalog (free acquisition intel) ----------------
  # The launcher's listings_v1.db says which owned packs it has seen and that
  # UE listings have no standalone download — the hub uses it to emit real
  # per-pack acquisition instructions instead of a generic "download" hint.
  $fabDb = "C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\FabLibrary\listings_v1.db"
  if (Test-Path $fabDb) {
    try {
      Invoke-RestMethod -Method Post -Uri "$VellumBase/api/import/fab-listings-db" `
        -Form @{ db = Get-Item $fabDb } -TimeoutSec 120 | Out-Null
      $actions.Add("fab_listings_pushed")
    } catch {
      Add-Exception "fab_listings" $fabDb $_.Exception.Message "Hub rejected launcher catalog; acquisition hints may be stale."
    }
  }

  # ---- 2. Register orphan folders --------------------------------------------
  Write-Host "== 2/8 register orphans"
  $cov = Invoke-Api GET "/api/import/coverage?engine=unreal"
  if ([int]$cov.orphan_count -gt 0) {
    $reg = Invoke-Api POST "/api/import/register-orphans" @{ auto_stage = $false }
    $actions.Add("registered_orphans:$($reg.registered)")
    foreach ($e in @($reg.errors)) {
      Add-Exception "register" $e.folder $e.error "Register manually via POST /api/assets"
    }
    $cov = Invoke-Api GET "/api/import/coverage?engine=unreal"
  }

  # ---- 3. Patch on-disk rows missing host path / in_project ------------------
  Write-Host "== 3/8 patch register rows"
  $assetsById = @{}
  foreach ($a in @((Invoke-Api GET "/api/assets").assets)) { $assetsById[$a.id] = $a }
  foreach ($row in @($cov.on_disk)) {
    $asset = $assetsById[$row.asset_id]
    if (-not $asset) { continue }
    $needsPatch = -not $asset.host_content_path -or ($asset.ue_in_project -ne "in_project")
    if ($needsPatch) {
      $folderLeaf = Split-Path ([string]$row.path) -Leaf
      Invoke-Api PATCH "/api/assets/$($row.asset_id)" @{
        host_content_path = [string]$row.path
        content_root      = "/Game/$folderLeaf"
        ue_in_project     = "in_project"
      } | Out-Null
      $actions.Add("patched:$($row.asset_id)")
    }
  }

  # ---- 4. Stage packs on disk but missing from vault --------------------------
  Write-Host "== 4/8 stage to vault"
  $staged = 0
  foreach ($row in @($cov.on_disk)) {
    if ($row.staged -or $staged -ge $MaxStagePerRun) { continue }
    $packPath = [string]$row.path
    $folder = Split-Path $packPath -Leaf
    $zip = Join-Path $env:TEMP "vellum-stage-$folder.zip"
    try {
      if (Test-Path $zip) { Remove-Item $zip -Force }
      Add-Type -AssemblyName System.IO.Compression.FileSystem
      [IO.Compression.ZipFile]::CreateFromDirectory(
        $packPath, $zip, [IO.Compression.CompressionLevel]::Fastest, $false)
      Invoke-RestMethod -Method Post `
        -Uri "$VellumBase/api/assets/$($row.asset_id)/import/stage-upload" `
        -Form @{
          host_content_path   = $packPath
          content_folder_name = $folder
          archive             = Get-Item $zip
        } -TimeoutSec 1800 | Out-Null
      $actions.Add("staged:$($row.asset_id)")
      $staged++
    } catch {
      Add-Exception "stage" $row.asset_id $_.Exception.Message "Retry next run; check hub disk space"
    } finally {
      if (Test-Path $zip) { Remove-Item $zip -Force -ErrorAction SilentlyContinue }
    }
  }

  # ---- 5. Perforce reconcile + submit -----------------------------------------
  Write-Host "== 5/8 perforce"
  $p4 = "C:\Program Files\Perforce\p4.exe"
  if (Test-Path $p4) {
    $env:P4PORT = $P4Port; $env:P4USER = $P4User; $env:P4CLIENT = $P4Client
    Push-Location $ProjectRoot
    try {
      & $p4 reconcile "Content/..." 2>&1 | Out-Null
      $opened = @(& $p4 opened 2>$null)
      if ($opened.Count -gt 0) {
        $out = & $p4 submit -d "reconcile: library content sync $(Get-Date -Format s)" 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -and $out -notmatch "submitted") {
          Add-Exception "p4" "submit" ($out.Trim() -split "`n" | Select-Object -Last 1) "p4 opened / resolve on Aurora"
        } else {
          $actions.Add("p4_submitted:$($opened.Count)_files")
        }
      }
    } finally { Pop-Location }
  } else {
    Add-Exception "p4" "p4.exe" "Perforce client missing" "Install Helix CLI"
  }

  # ---- 6. Unreal load-check for packs without a manifest ----------------------
  Write-Host "== 6/8 inventory validation"
  if (-not $SkipInventory) {
    $infra = @("Collections", "Developers", "Fab", "Python", "Vellum",
      "__ExternalActors__", "__ExternalObjects__")
    $packs = @(Get-ChildItem (Join-Path $ProjectRoot "Content") -Directory |
      Where-Object { $_.Name -notin $infra })
    $ran = 0
    foreach ($pack in $packs) {
      if ($ran -ge $MaxInventoryPerRun) { break }
      $manifest = Join-Path $ProjectRoot "Saved\VellumPipeline\$($pack.Name)\inventory-pack.manifest.json"
      if (Test-Path $manifest) {
        # Re-check only if pack changed after last manifest;
        # still re-surface stale load errors so they are never forgotten.
        $mTime = (Get-Item $manifest).LastWriteTimeUtc
        $newest = (Get-ChildItem $pack.FullName -Recurse -File -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1)
        if (-not $newest -or $newest.LastWriteTimeUtc -le $mTime) {
          $prev = Get-Content $manifest -Raw | ConvertFrom-Json
          $actionable = Get-ActionableLoadErrors $prev.load_errors
          if (@($prev.load_errors).Count -gt $actionable.Count) {
            $actions.Add("accepted_load_errors:$($pack.Name):$(@($prev.load_errors).Count - $actionable.Count)")
          }
          if ($actionable.Count -gt 0) {
            Add-Exception "load" $pack.Name "$($actionable.Count) assets failed to load (manifest $($prev.generated_at_utc))" ($actionable -join "; ")
          }
          continue
        }
      }
      $ran++
      Write-Host "   inventory-pack $($pack.Name)"
      & pwsh -NoProfile -File (Join-Path $RepoRoot "tools\pipeline\run_job.ps1") `
        -Job inventory-pack -Pack $pack.Name -TimeoutSec 1200 *> (Join-Path $StateDir "inventory-$($pack.Name).log")
      if ($LASTEXITCODE -ne 0) {
        Add-Exception "inventory" $pack.Name "inventory-pack job failed (exit $LASTEXITCODE)" "See $StateDir\inventory-$($pack.Name).log"
        continue
      }
      $m = Get-Content $manifest -Raw | ConvertFrom-Json
      $actionable = Get-ActionableLoadErrors $m.load_errors
      if (@($m.load_errors).Count -gt $actionable.Count) {
        $actions.Add("accepted_load_errors:$($pack.Name):$(@($m.load_errors).Count - $actionable.Count)")
      }
      if ($actionable.Count -gt 0) {
        Add-Exception "load" $pack.Name "$($actionable.Count) assets failed to load" ($actionable -join "; ")
      } else {
        $actions.Add("validated:$($pack.Name):$($m.asset_count)_assets")
      }
    }
  }

  # ---- 6b. Conversion Factory (machine-owned "lookdev") ------------------------
  # Packs with no game-ready evidence get one UE boot (factory-all) that does
  # models+media+bake. Multiple packs run in parallel with isolated work dirs
  # so they don't clobber scripts/logs while sharing the Library project read-only.
  Write-Host "== 6b/8 conversion factory (workers=$FactoryWorkers)"
  if (-not $SkipFactory) {
    $cov2 = Invoke-Api GET "/api/import/coverage"
    $candidates = New-Object System.Collections.Generic.List[object]
    foreach ($row in @($cov2.on_disk)) {
      if ($candidates.Count -ge $MaxFactoryPerRun) { break }
      $aid = [string]$row.asset_id
      $packName = [string]$row.folder
      if (-not $aid -or -not $packName) { continue }
      try {
        $ev = Invoke-Api GET "/api/game-ready/elements?asset_id=$aid&limit=1"
        if ([int]$ev.count -gt 0) { continue }
      } catch {
        Add-Exception "factory" $aid "hub game-ready query failed: $($_.Exception.Message)"
        continue
      }
      $candidates.Add([pscustomobject]@{ asset_id = $aid; pack = $packName })
    }
    Write-Host "   factory backlog: $($candidates.Count) packs"
    if ($candidates.Count -gt 0) {
      $workers = [Math]::Max(1, [Math]::Min($FactoryWorkers, $candidates.Count))
      $runJob = Join-Path $RepoRoot "tools\pipeline\run_job.ps1"
      $packZip = Join-Path $RepoRoot "tools\pipeline\pack_factory_run.ps1"
      $pipelineRoot = Join-Path $ProjectRoot "Saved\VellumPipeline"
      $results = $candidates | ForEach-Object -ThrottleLimit $workers -Parallel {
        $aid = $_.asset_id
        $packName = $_.pack
        $stateDir = $using:StateDir
        $vellumBase = $using:VellumBase
        $runJobPath = $using:runJob
        $packZipPath = $using:packZip
        $pipelineRootPath = $using:pipelineRoot
        $work = Join-Path $pipelineRootPath "workers\$packName"
        $out = Join-Path $work "game-ready-out"
        New-Item -ItemType Directory -Force -Path $work, $out | Out-Null
        $log = Join-Path $stateDir "factory-all-$packName.log"
        $result = [ordered]@{
          pack = $packName; asset_id = $aid; ok = $false
          registered = 0; detail = ""; keep_zip = $false; zip = $null
        }
        Write-Host "   factory $packName ($aid)"
        try {
          & pwsh -NoProfile -File $runJobPath -Job factory-all -Pack $packName `
            -WorkDir $work -VaultGameReady $out -TimeoutSec 5400 *> $log
          if ($LASTEXITCODE -ne 0) {
            $result.detail = "factory-all exit $LASTEXITCODE (see $log)"
            return [pscustomobject]$result
          }
          $packOutDirs = @("models\$packName", "textures\$packName", "audio\$packName", "vfx\$packName") |
            ForEach-Object { Join-Path $out $_ } | Where-Object { Test-Path $_ }
          if (-not $packOutDirs) {
            $result.detail = "no factory output produced"
            return [pscustomobject]$result
          }
          $zipPath = Join-Path $stateDir "factory-$packName.zip"
          & pwsh -NoProfile -File $packZipPath -SourceDirs $packOutDirs `
            -DestinationZip $zipPath -MaxFiles 480
          $resp = Invoke-RestMethod -Method Post `
            -Uri "$vellumBase/api/assets/$aid/game-ready/upload-run" `
            -Form @{ pack = $packName; archive = Get-Item $zipPath } -TimeoutSec 600
          $result.ok = $true
          $result.registered = [int]$resp.registered
          Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        } catch {
          $result.detail = $_.Exception.Message
          $result.keep_zip = $true
          $result.zip = Join-Path $stateDir "factory-$packName.zip"
        }
        return [pscustomobject]$result
      }
      foreach ($r in @($results)) {
        if ($r.ok) {
          $actions.Add("converted:$($r.pack):$($r.registered)_elements")
        } else {
          $fix = if ($r.keep_zip -and $r.zip) { "Zip kept at $($r.zip)" } else { "See $StateDir\factory-all-$($r.pack).log" }
          Add-Exception "factory" $r.pack $r.detail $fix
        }
      }
    }
  }

  # ---- 7. Corrupt-package health ----------------------------------------------
  Write-Host "== 7/8 health scan"
  $healthReport = Join-Path $StateDir "library_health_report.json"
  & pwsh -NoProfile -File (Join-Path $RepoRoot "tools\pipeline\library\reorganize_library_content.ps1") `
    -InventoryOnly -ReportOut $healthReport | Out-Null
  $health = Get-Content $healthReport -Raw | ConvertFrom-Json
  foreach ($bad in @($health.unloadable_packages)) {
    if (Test-AcceptedQuarantine ([string]$bad.path)) {
      $actions.Add("accepted_quarantine:$($bad.path)")
      continue
    }
    Add-Exception "corrupt" $bad.path $bad.reason "Quarantine + re-Add pack from Fab"
  }
  $quarantine = Join-Path $ProjectRoot "Quarantine"
  if (Test-Path $quarantine) {
    foreach ($q in @(Get-ChildItem $quarantine -Recurse -File)) {
      $rel = $q.FullName.Substring($quarantine.Length + 1)
      if (Test-AcceptedQuarantine $rel) {
        $actions.Add("accepted_quarantine:$rel")
        continue
      }
      Add-Exception "quarantined" $rel `
        "awaiting clean re-download" "Fab: Add to Project (in-editor), then reconcile"
    }
  }

  # ---- 7b. Launcher must be able to SEE the Library project -------------------
  # Fab "Add to Project" only lists projects the launcher discovers via
  # CreatedProjectPaths, and the entry must be the PARENT folder of the
  # project dir (F:/Games), not the project dir itself — a known launcher
  # quirk that silently hides the project.
  $launcherIni = Join-Path $env:LOCALAPPDATA "EpicGamesLauncher\Saved\Config\WindowsEditor\GameUserSettings.ini"
  $wantParent = (Split-Path $ProjectRoot -Parent).Replace("\", "/")
  if (Test-Path $launcherIni) {
    $iniLines = Get-Content $launcherIni
    $paths = @($iniLines | Where-Object { $_ -match "^CreatedProjectPaths=" } |
      ForEach-Object { ($_ -split "=", 2)[1].Trim().TrimEnd("/") })
    if ($paths -notcontains $wantParent) {
      $launcherRunning = @(Get-Process EpicGamesLauncher -ErrorAction SilentlyContinue).Count -gt 0
      if ($launcherRunning) {
        Add-Exception "launcher_config" $launcherIni `
          "CreatedProjectPaths missing '$wantParent' (project invisible to Fab Add to Project)" `
          "Close Epic Launcher fully (system tray too); reconcile will fix the ini on next run."
      } else {
        Copy-Item $launcherIni "$launcherIni.bak-vellum" -Force
        $filtered = @($iniLines | Where-Object {
            -not ($_ -match "^CreatedProjectPaths=" -and
              (($_ -split "=", 2)[1].Trim().TrimEnd("/")) -ieq $ProjectRoot.Replace("\", "/"))
          })
        $idx = [Array]::IndexOf($filtered, "[Launcher]")
        if ($idx -ge 0) {
          $before = $filtered[0..$idx]
          $after = if ($idx + 1 -le $filtered.Count - 1) { $filtered[($idx + 1)..($filtered.Count - 1)] } else { @() }
          $filtered = @($before) + @("CreatedProjectPaths=$wantParent") + @($after)
        } else {
          $filtered += @("[Launcher]", "CreatedProjectPaths=$wantParent")
        }
        Set-Content -Path $launcherIni -Value $filtered -Encoding utf8
        $actions.Add("launcher_created_project_paths_fixed:$wantParent")
      }
    }
  } else {
    Add-Exception "launcher_config" $launcherIni "Epic Launcher settings not found" `
      "Launch Epic Games Launcher once so it writes its config, then rerun reconcile."
  }

  # ---- 8. Stray Unreal projects (Fab installed into wrong project) ------------
  Write-Host "== 8/8 stray project scan"
  foreach ($root in @("C:\dev", "F:\Games", "$env:USERPROFILE\Documents\Unreal Projects")) {
    if (-not (Test-Path $root)) { continue }
    foreach ($up in @(Get-ChildItem $root -Filter *.uproject -Recurse -Depth 2 -ErrorAction SilentlyContinue)) {
      $projDir = Split-Path $up.FullName -Parent
      if ($projDir -ieq $ProjectRoot) { continue }
      $content = Join-Path $projDir "Content"
      $packCount = if (Test-Path $content) { @(Get-ChildItem $content -Directory -ErrorAction SilentlyContinue).Count } else { 0 }
      Add-Exception "stray_project" $up.FullName "$packCount Content folders outside the Library" `
        "Fab installed into the wrong project. Copy packs to $ProjectRoot\Content (folder names unchanged), then delete stray project."
    }
  }

  # Redeemed-but-not-in-project. The hub classifies each pack from the
  # launcher's own catalog (fab_add_to_project / vault_install / unseen);
  # UE-only listings cannot be "downloaded" — only added to a project.
  foreach ($nd in @($cov.need_download)) {
    $acq = $nd.acquisition
    $kind = if ($acq -and $acq.method) { "acquire_$($acq.method)" } else { "need_download" }
    $hint = if ($acq -and $acq.operator_hint) { [string]$acq.operator_hint } else { "Epic Launcher: Fab Library -> Add to Project -> AuroraVellum" }
    Add-Exception $kind $nd.asset_id $nd.display_name $hint
  }
}
finally {
  Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}

# NB: @($list) of ordered dictionaries inside an [ordered]@{} literal throws
# "Argument types do not match" — materialize plain arrays first.
$actionArr = $actions.ToArray()
$exceptionArr = $exceptions.ToArray()
$summary = [ordered]@{
  schema_version   = 1
  generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
  actions          = $actionArr
  exception_count  = $exceptionArr.Count
  exceptions       = $exceptionArr
}
$outPath = Join-Path $StateDir "reconcile_report.json"
$summary | ConvertTo-Json -Depth 6 | Set-Content -Path $outPath -Encoding utf8

Write-Host ""
Write-Host "Reconcile complete: $($actions.Count) actions, $($exceptions.Count) exceptions."
Write-Host "Report: $outPath"
if ($exceptions.Count -gt 0) {
  $exceptions | ForEach-Object { "  [$($_.kind)] $($_.subject)" } | Write-Host
}
