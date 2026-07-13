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
$specs | ConvertTo-Json -Depth 6
