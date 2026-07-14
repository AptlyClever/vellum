#Requires -Version 7.0
<#
.SYNOPSIS
  Bootstrap Helix Core (p4d) on this machine for the Vellum Library depot.
#>
param(
  [string]$ServerRoot = "F:\Perforce\vellum-library",
  [int]$Port = 1666,
  [string]$ServiceUser = "jaked"
)

$ErrorActionPreference = "Stop"
$p4d = Get-Command p4d -ErrorAction SilentlyContinue
$p4 = Get-Command p4 -ErrorAction SilentlyContinue

if (-not $p4d -or -not $p4) {
  Write-Host @"
Perforce Helix Core is not installed (p4/p4d missing from PATH).

Install steps:
  1. Download Helix Core Server (P4D) + Helix Command-Line Client for Windows
     https://www.perforce.com/downloads/helix-core-p4d
  2. Complete the installer (free for up to 5 users / 20 workspaces).
  3. Re-open a shell and re-run:
       pwsh -File tools/pipeline/p4/bootstrap_p4_server.ps1

Until then, the Library still lives on disk under F:\Games\AuroraVellum;
binary history is not yet versioned.
"@
  exit 3
}

New-Item -ItemType Directory -Force -Path $ServerRoot | Out-Null
$env:P4PORT = "localhost:$Port"
$env:P4USER = $ServiceUser
Remove-Item Env:P4PASSWD -ErrorAction SilentlyContinue

$p4dPath = (Get-Command p4d).Source
# P4D 2026.1 requires auth on fresh databases unless these are set OFFLINE
# (server stopped) before first start. Entire "var=value" must be ONE argument.
# Prefer security=0 for a private LAN library until the operator hardens with login.
& $p4dPath -r $ServerRoot "-cset security=0" 2>$null
& $p4dPath -r $ServerRoot "-cset dm.user.noautocreate=0" 2>$null
& $p4dPath -r $ServerRoot "-cset lbr.autocompress=1" 2>$null

$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
  Start-Process -FilePath $p4dPath -ArgumentList @("-r", $ServerRoot, "-p", "$Port", "-L", "$ServerRoot\p4d.log") -WindowStyle Hidden
  Start-Sleep -Seconds 2
}
Write-Host "p4d root=$ServerRoot port=$Port (prefer Helix installer for durable Windows Service)."

$info = & p4 info 2>&1 | Out-String
Write-Host $info
if ($info -match "Connect to server failed") {
  Write-Warning "p4 info failed — start the p4d service, then re-run this script."
  exit 4
}

$depotSpec = @"
Depot:  vellum_library
Owner:  $ServiceUser
Description: Vellum AuroraVellum Library binaries
Type:   local
Map:    vellum_library/...
"@
$depotSpec | & p4 depot -i
Write-Host "Ensured depot //vellum_library/"

$ignoreSrc = Join-Path $PSScriptRoot "p4ignore.txt"
if (Test-Path $ignoreSrc) {
  Copy-Item -Force $ignoreSrc (Join-Path $ServerRoot "p4ignore.txt")
}
Write-Host "Bootstrap complete. Next: pwsh -File tools/pipeline/p4/first_library_submit.ps1"
