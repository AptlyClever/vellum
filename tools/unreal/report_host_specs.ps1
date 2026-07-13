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
  [string]$HostName = ""
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

# Prefer nvidia-smi for real VRAM — Win32 AdapterRAM is a 32-bit field and often lies.
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

$body = @{
  host_id = $UeHost.id
  specs   = $specs
} | ConvertTo-Json -Depth 8

Write-Host "Posting host specs for $($UeHost.id) to $VellumBase"
$res = Invoke-RestMethod -Method Post -Uri "$VellumBase/api/ue/hosts/specs" `
  -ContentType "application/json" -Body $body
Write-Host "Stored specs updated_at=$($res.updated_at)"
Write-Host ("CPU: " + (($specs.cpu | ForEach-Object { $_.name }) -join "; "))
Write-Host ("RAM: {0} GB" -f $specs.ram_gb)
Write-Host ("GPU: " + (($specs.gpus | ForEach-Object { $_.name }) -join "; "))
if ($nvidia.Count -gt 0) {
  Write-Host ("NVIDIA: " + (($nvidia | ForEach-Object { "{0} ({1} GB)" -f $_.name, $_.vram_gb }) -join "; "))
}
$specs | ConvertTo-Json -Depth 6
