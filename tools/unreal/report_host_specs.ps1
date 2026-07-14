#Requires -Version 5.1
<#
.SYNOPSIS
  Collect Aurora/Borealis hardware specs and POST to Vellum.

.EXAMPLE
  pwsh -File tools/unreal/report_host_specs.ps1
  pwsh -File tools/unreal/vellum_ue_agent.ps1 -ReportHostSpecs
#>
param(
  [string]$VellumBase = "http://192.168.68.93:8770",
  [string]$HostName = "",
  # Nested pack roots (e.g. BefourStudios\JapaneseOldShoppingMall) to include in picker.
  [string[]]$ExtraContentPaths = @()
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "ue-hosts.ps1")
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$UeHost = Get-UeHostProfile -RepoRoot $RepoRoot -HostName $HostName

function Get-CimSafe([string]$Class, [string]$Filter = $null) {
  try {
    if ($Filter) { return @(Get-CimInstance -ClassName $Class -Filter $Filter -ErrorAction Stop) }
    return @(Get-CimInstance -ClassName $Class -ErrorAction Stop)
  } catch {
    return @()
  }
}

$cs = Get-CimSafe "Win32_ComputerSystem" | Select-Object -First 1
$os = Get-CimSafe "Win32_OperatingSystem" | Select-Object -First 1
$cpu = @(Get-CimSafe "Win32_Processor")
$gpus = @(Get-CimSafe "Win32_VideoController")
$mem = @(Get-CimSafe "Win32_PhysicalMemory")
$disks = @(Get-CimSafe "Win32_LogicalDisk" -Filter "DriveType=3")

$totalRamBytes = 0
foreach ($m in $mem) { $totalRamBytes += [int64]$m.Capacity }

# Prefer nvidia-smi for real VRAM - Win32 AdapterRAM is a 32-bit field and often lies.
$nvidia = @()
try {
  $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
  if ($smi) {
    $raw = & nvidia-smi --query-gpu=name,memory.total,driver_version,utilization.gpu,utilization.memory --format=csv,noheader,nounits 2>$null
    foreach ($line in @($raw)) {
      if (-not $line) { continue }
      $parts = @($line -split "," | ForEach-Object { $_.Trim() })
      if ($parts.Count -lt 2) { continue }
      $nvidia += [ordered]@{
        name            = [string]$parts[0]
        vram_mb         = [int]($parts[1] -as [double])
        vram_gb         = [math]::Round(([double]$parts[1]) / 1024.0, 1)
        driver_version  = if ($parts.Count -gt 2) { [string]$parts[2] } else { $null }
        util_gpu_pct    = if ($parts.Count -gt 3) { [int]($parts[3] -as [double]) } else { $null }
        util_mem_pct    = if ($parts.Count -gt 4) { [int]($parts[4] -as [double]) } else { $null }
      }
    }
  }
} catch {
  $nvidia = @()
}

$specs = [ordered]@{
  collected_by     = "report_host_specs.ps1"
  hostname         = $env:COMPUTERNAME
  manufacturer     = if ($cs) { [string]$cs.Manufacturer } else { $null }
  model            = if ($cs) { [string]$cs.Model } else { $null }
  domain           = if ($cs) { [string]$cs.Domain } else { $null }
  os_caption       = if ($os) { [string]$os.Caption } else { $null }
  os_version       = if ($os) { [string]$os.Version } else { $null }
  os_arch          = if ($os) { [string]$os.OSArchitecture } else { $null }
  cpu = @($cpu | ForEach-Object {
      [ordered]@{
        name            = [string]$_.Name
        cores           = [int]$_.NumberOfCores
        logical_processors = [int]$_.NumberOfLogicalProcessors
        max_clock_mhz   = [int]$_.MaxClockSpeed
      }
    })
  ram_gb           = [math]::Round($totalRamBytes / 1GB, 1)
  ram_bytes        = $totalRamBytes
  gpus = @($gpus | ForEach-Object {
      [ordered]@{
        name            = [string]$_.Name
        adapter_ram_gb  = if ($_.AdapterRAM -and $_.AdapterRAM -gt 0) {
          [math]::Round([double]$_.AdapterRAM / 1GB, 1)
        } else { $null }
        driver_version  = [string]$_.DriverVersion
        driver_date     = if ($_.DriverDate) { $_.DriverDate.ToString("u") } else { $null }
        video_mode      = [string]$_.VideoModeDescription
      }
    })
  nvidia_gpus      = $nvidia
  primary_gpu      = if ($nvidia.Count -gt 0) { $nvidia[0].name } elseif (
      ($gpus | Where-Object { $_.Name -notmatch 'Remote Display|Microsoft Basic' } | Select-Object -First 1)
    ) {
      ($gpus | Where-Object { $_.Name -notmatch 'Remote Display|Microsoft Basic' } | Select-Object -First 1).Name
    } else { $null }
  volumes = @($disks | ForEach-Object {
      [ordered]@{
        device_id   = [string]$_.DeviceID
        size_gb     = if ($_.Size) { [math]::Round([double]$_.Size / 1GB, 1) } else { $null }
        free_gb     = if ($_.FreeSpace) { [math]::Round([double]$_.FreeSpace / 1GB, 1) } else { $null }
        file_system = [string]$_.FileSystem
      }
    })
  ue_host_profile  = $UeHost.id
  ue_editor        = [string]$UeHost.ue_editor
  ue_project       = [string]$UeHost.project
}

# Content/<Pack> folders for Import pack picker (multi-root: canonical F: + Fab dumps).
$contentFolders = @()
$projDir = [string]$UeHost.project_dir
if (-not $projDir -and $UeHost.project) {
  $projDir = Split-Path ([string]$UeHost.project) -Parent
}
$primaryContent = if ($projDir) { Join-Path $projDir "Content" } else { $null }
$scanRoots = New-Object System.Collections.Generic.List[string]
foreach ($r in @($UeHost.content_scan_roots)) {
  if ($r) { [void]$scanRoots.Add([string]$r) }
}
if ($primaryContent -and -not ($scanRoots | Where-Object { $_ -ieq $primaryContent })) {
  [void]$scanRoots.Insert(0, $primaryContent)
}
function Add-ContentFolderRow {
  param(
    [System.IO.DirectoryInfo]$Dir,
    [string]$ProjectRoot,
    [string]$ContentRootPath
  )
  $full = [string]$Dir.FullName
  $key = $full.ToLowerInvariant()
  if ($script:seenPaths.ContainsKey($key)) { return }
  $script:seenPaths[$key] = $true
  $pngApprox = 0
  try {
    $pngApprox = @(Get-ChildItem -Path $Dir.FullName -Recurse -File -Include *.uasset,*.umap -ErrorAction SilentlyContinue |
      Select-Object -First 50).Count
  } catch { $pngApprox = 0 }
  $script:contentFolders += [ordered]@{
    name          = [string]$Dir.Name
    path          = $full
    project_root  = [string]$ProjectRoot
    content_root  = [string]$ContentRootPath
    engine        = "unreal"
    mtime_utc     = $Dir.LastWriteTimeUtc.ToString("o")
    sample_assets = [int]$pngApprox
  }
}

$seenPaths = @{}
$VendorNestParents = @("BefourStudios")
foreach ($contentRoot in $scanRoots) {
  if (-not $contentRoot -or -not (Test-Path -LiteralPath $contentRoot)) { continue }
  $projectRoot = Split-Path $contentRoot -Parent
  foreach ($d in @(Get-ChildItem -LiteralPath $contentRoot -Directory -ErrorAction SilentlyContinue)) {
    if ($d.Name -match '^(Collections|Developers|__ExternalActors__|__ExternalObjects__)$') { continue }
    Add-ContentFolderRow -Dir $d -ProjectRoot $projectRoot -ContentRootPath $contentRoot
    # Vendor packs nest one level (Japanese / Motel under BefourStudios).
    if ($VendorNestParents -contains $d.Name) {
      foreach ($child in @(Get-ChildItem -LiteralPath $d.FullName -Directory -ErrorAction SilentlyContinue)) {
        Add-ContentFolderRow -Dir $child -ProjectRoot $projectRoot -ContentRootPath $contentRoot
      }
    }
  }
}
foreach ($extra in @($ExtraContentPaths)) {
  if (-not $extra -or -not (Test-Path -LiteralPath $extra)) { continue }
  $item = Get-Item -LiteralPath $extra
  if (-not $item.PSIsContainer) { continue }
  $contentRootGuess = $primaryContent
  if ($primaryContent -and $item.FullName.StartsWith($primaryContent, [StringComparison]::OrdinalIgnoreCase)) {
    $contentRootGuess = $primaryContent
  } else {
    $contentRootGuess = Split-Path $item.FullName -Parent
  }
  $projectRootGuess = if ($projDir) { $projDir } else { Split-Path $contentRootGuess -Parent }
  Add-ContentFolderRow -Dir $item -ProjectRoot $projectRootGuess -ContentRootPath $contentRootGuess
}
# Optional Unity package roots (host profile may set unity_packages_dir later).
$unityRoot = [string]$UeHost.unity_packages_dir
if ($unityRoot -and (Test-Path -LiteralPath $unityRoot)) {
  foreach ($d in @(Get-ChildItem -LiteralPath $unityRoot -Directory -ErrorAction SilentlyContinue)) {
    $contentFolders += [ordered]@{
      name          = [string]$d.Name
      path          = [string]$d.FullName
      project_root  = [string]$unityRoot
      content_root  = [string]$unityRoot
      engine        = "unity"
      mtime_utc     = $d.LastWriteTimeUtc.ToString("o")
      sample_assets = 0
    }
  }
}
$specs["content_folders"] = $contentFolders
$specs["content_root_path"] = $primaryContent
$specs["content_scan_roots"] = @($scanRoots)
$specs["fab_target_project"] = [string]$UeHost.fab_target_project
$specs["fab_target_label"] = [string]$UeHost.fab_target_label

$body = @{
  host_id = $UeHost.id
  specs   = $specs
} | ConvertTo-Json -Depth 8

Write-Host "Posting host specs for $($UeHost.id) to $VellumBase ($($contentFolders.Count) content folders)"
$res = Invoke-RestMethod -Method Post -Uri "$VellumBase/api/ue/hosts/specs" `
  -ContentType "application/json" -Body $body
Write-Host "Stored specs updated_at=$($res.updated_at)"
Write-Host ("CPU: " + (($specs.cpu | ForEach-Object { $_.name }) -join "; "))
Write-Host ("RAM: {0} GB" -f $specs.ram_gb)
Write-Host ("GPU: " + (($specs.gpus | ForEach-Object { $_.name }) -join "; "))
if ($nvidia.Count -gt 0) {
  Write-Host ("NVIDIA: " + (($nvidia | ForEach-Object { "{0} ({1} GB)" -f $_.name, $_.vram_gb }) -join "; "))
}
foreach ($cf in $contentFolders) {
  Write-Host ("Content: {0} -> {1}" -f $cf.name, $cf.path)
}
$specs | ConvertTo-Json -Depth 6
