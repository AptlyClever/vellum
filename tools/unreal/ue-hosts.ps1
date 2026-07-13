#Requires -Version 5.1
<#
.SYNOPSIS
  Shared UE capture host profile loader (Aurora / Borealis).

.DESCRIPTION
  Dot-source from vellum_ue_agent.ps1 / run_vellum_capture.ps1.
  Config: config/ue-hosts.json (active host + per-machine paths).
  Override active host with -HostName / $env:VELLUM_UE_HOST.
#>

function Get-VellumRepoRoot {
  param([string]$FromScriptRoot = $PSScriptRoot)
  return (Resolve-Path (Join-Path $FromScriptRoot "..\..")).Path
}

function Get-UeHostsConfigPath {
  param([string]$RepoRoot)
  return (Join-Path $RepoRoot "config\ue-hosts.json")
}

function Read-UeHostsConfig {
  param([string]$RepoRoot)
  $path = Get-UeHostsConfigPath -RepoRoot $RepoRoot
  if (-not (Test-Path -LiteralPath $path)) {
    throw "UE hosts config missing: $path"
  }
  return (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Resolve-UeHostId {
  param(
    [string]$Requested,
    $Config
  )
  if ($Requested) { return $Requested.Trim().ToLowerInvariant() }
  if ($env:VELLUM_UE_HOST) { return $env:VELLUM_UE_HOST.Trim().ToLowerInvariant() }
  if ($Config.active) { return ([string]$Config.active).Trim().ToLowerInvariant() }
  return "aurora"
}

function Get-UeHostProfile {
  param(
    [string]$RepoRoot,
    [string]$HostName = ""
  )
  $config = Read-UeHostsConfig -RepoRoot $RepoRoot
  $id = Resolve-UeHostId -Requested $HostName -Config $config
  $hosts = $config.hosts
  if ($hosts.PSObject.Properties.Name -notcontains $id) {
    $known = @($hosts.PSObject.Properties.Name) -join ", "
    throw "Unknown UE host '$id'. Known: $known. Set config/ue-hosts.json active or VELLUM_UE_HOST."
  }
  $profile = $hosts.$id
  return [pscustomobject]@{
    id              = $id
    label           = [string]$profile.label
    role            = [string]$profile.role
    repo            = [string]$profile.repo
    ue_editor       = [string]$profile.ue_editor
    ue_cmd          = [string]$profile.ue_cmd
    project         = [string]$profile.project
    project_dir     = [string]$profile.project_dir
    content_root    = [string]$profile.content_root
    engine_version  = [string]$profile.engine_version
    active_in_config = ([string]$config.active).Trim().ToLowerInvariant()
  }
}

function ConvertTo-UeCmdPath {
  <#
  .SYNOPSIS
    Accept UnrealEditor.exe or UnrealEditor-Cmd.exe; return Cmd path if present.
  #>
  param([string]$PathHint)
  if (-not $PathHint) { return $null }
  $p = $PathHint.Trim()
  if ($p -match "(?i)UnrealEditor\.exe$") {
    $cmd = $p -replace "(?i)UnrealEditor\.exe$", "UnrealEditor-Cmd.exe"
    if (Test-Path -LiteralPath $cmd) { return (Resolve-Path -LiteralPath $cmd).Path }
    # Cmd missing beside Editor — still return expected Cmd path for clearer errors.
    return $cmd
  }
  if (Test-Path -LiteralPath $p) {
    return (Resolve-Path -LiteralPath $p).Path
  }
  return $p
}

function Find-UeCmdFromHost {
  param(
    $HostProfile,
    [string]$Hint = ""
  )
  $ordered = New-Object System.Collections.Generic.List[string]
  foreach ($c in @(
      $Hint,
      $env:VELLUM_UE_CMD,
      $(if ($HostProfile) { $HostProfile.ue_cmd } else { $null }),
      $(if ($HostProfile) { ConvertTo-UeCmdPath $HostProfile.ue_editor } else { $null }),
      "F:\Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
      "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
      "C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
      "E:\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
      "D:\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
    )) {
    if ($c) { [void]$ordered.Add((ConvertTo-UeCmdPath $c)) }
  }

  foreach ($hive in @(
      "HKLM:\SOFTWARE\EpicGames\Unreal Engine",
      "HKLM:\SOFTWARE\WOW6432Node\EpicGames\Unreal Engine"
    )) {
    if (-not (Test-Path $hive)) { continue }
    Get-ChildItem $hive -ErrorAction SilentlyContinue | ForEach-Object {
      try {
        $installed = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).InstalledDirectory
        if ($installed) {
          [void]$ordered.Add((Join-Path $installed "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"))
        }
      } catch { }
    }
  }

  foreach ($c in $ordered) {
    if ($c -and (Test-Path -LiteralPath $c)) {
      return (Resolve-Path -LiteralPath $c).Path
    }
  }

  foreach ($searchRoot in @(
      "F:\Games",
      "E:\Epic Games",
      "E:\UE",
      "D:\Epic Games",
      "C:\Epic Games",
      "C:\Program Files\Epic Games"
    )) {
    if (-not (Test-Path -LiteralPath $searchRoot)) { continue }
    $hit = Get-ChildItem -LiteralPath $searchRoot -Filter "UnrealEditor-Cmd.exe" -Recurse -File `
      -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit) { return $hit.FullName }
  }

  $hostId = if ($HostProfile) { $HostProfile.id } else { "?" }
  throw "UnrealEditor-Cmd.exe not found for host '$hostId'. Set ue_cmd in config/ue-hosts.json or VELLUM_UE_CMD. (Editor path alone is fine — we derive -Cmd beside it.)"
}

function Resolve-UprojectFromHost {
  param(
    $HostProfile,
    [string]$PayloadProjectPath = "",
    [string]$FallbackUproject = ""
  )
  $tries = New-Object System.Collections.Generic.List[string]
  # Active host profile first — job payload often still has the other machine's path.
  if ($HostProfile) {
    if ($HostProfile.project) { [void]$tries.Add($HostProfile.project) }
    if ($HostProfile.project_dir) {
      [void]$tries.Add((Join-Path $HostProfile.project_dir "VellumImport.uproject"))
      if (Test-Path -LiteralPath $HostProfile.project_dir) {
        Get-ChildItem -LiteralPath $HostProfile.project_dir -Filter "*.uproject" -File -ErrorAction SilentlyContinue |
          ForEach-Object { [void]$tries.Add($_.FullName) }
      }
    }
  }
  if ($env:VELLUM_UE_PROJECT) { [void]$tries.Add($env:VELLUM_UE_PROJECT) }
  if ($FallbackUproject) { [void]$tries.Add($FallbackUproject) }
  if ($PayloadProjectPath) {
    if ($PayloadProjectPath -like "*.uproject") {
      [void]$tries.Add($PayloadProjectPath)
    } else {
      [void]$tries.Add((Join-Path $PayloadProjectPath "VellumImport.uproject"))
      $leaf = Split-Path $PayloadProjectPath -Leaf
      [void]$tries.Add((Join-Path $PayloadProjectPath ($leaf + ".uproject")))
      if (Test-Path -LiteralPath $PayloadProjectPath) {
        Get-ChildItem -LiteralPath $PayloadProjectPath -Filter "*.uproject" -File -ErrorAction SilentlyContinue |
          ForEach-Object { [void]$tries.Add($_.FullName) }
      }
    }
  }
  foreach ($extra in @(
      "F:\Games\VellumImport\VellumImport.uproject",
      "E:\epic\VellumImport\VellumImport.uproject",
      "E:\Dev\VellumImport\VellumImport.uproject",
      "C:\epic\VellumImport\VellumImport.uproject"
    )) {
    [void]$tries.Add($extra)
  }

  # If payload path exists on this machine, use it; otherwise skip to profile.
  $seen = @{}
  foreach ($p in $tries) {
    if (-not $p -or $seen.ContainsKey($p)) { continue }
    $seen[$p] = $true
    if (Test-Path -LiteralPath $p) {
      return (Resolve-Path -LiteralPath $p).Path
    }
  }

  $hostId = if ($HostProfile) { $HostProfile.id } else { "?" }
  throw "No .uproject found for host '$hostId'. Edit config/ue-hosts.json project for this host, or set VELLUM_UE_PROJECT."
}
