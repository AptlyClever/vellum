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
  [switch]$SkipInventory,
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
          if (@($prev.load_errors).Count -gt 0) {
            Add-Exception "load" $pack.Name "$(@($prev.load_errors).Count) assets failed to load (manifest $($prev.generated_at_utc))" (@($prev.load_errors) -join "; ")
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
      if ($m.load_errors.Count -gt 0) {
        Add-Exception "load" $pack.Name "$($m.load_errors.Count) assets failed to load" ($m.load_errors -join "; ")
      } else {
        $actions.Add("validated:$($pack.Name):$($m.asset_count)_assets")
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
    Add-Exception "corrupt" $bad.path $bad.reason "Quarantine + re-Add pack from Fab"
  }
  $quarantine = Join-Path $ProjectRoot "Quarantine"
  if (Test-Path $quarantine) {
    foreach ($q in @(Get-ChildItem $quarantine -Recurse -File)) {
      Add-Exception "quarantined" $q.FullName.Substring($quarantine.Length + 1) `
        "awaiting clean re-download" "Fab: Add to Project (in-editor), then reconcile"
    }
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

  # Redeemed-but-not-downloaded (operator work, listed so nothing is forgotten)
  foreach ($nd in @($cov.need_download)) {
    Add-Exception "need_download" $nd.asset_id $nd.display_name "Epic Launcher: download / Add to Project -> AuroraVellum"
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
