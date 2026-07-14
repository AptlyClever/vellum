#Requires -Version 7.0
<#
.SYNOPSIS
  Create a P4 client for AuroraVellum and submit Content/ (first full submit).
#>
param(
  [string]$P4PORT = "localhost:1666",
  [string]$P4USER = "jaked",
  [string]$ClientName = "aurora-vellum-library",
  [string]$ProjectRoot = "F:\Games\AuroraVellum",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$p4cmd = Get-Command p4 -ErrorAction SilentlyContinue
if (-not $p4cmd) {
  $guess = "C:\Program Files\Perforce\p4.exe"
  if (Test-Path $guess) { $p4 = $guess } else {
    Write-Host "p4 not on PATH. Install Helix Command-Line Client, then re-run. See docs/p4-library.md"
    exit 3
  }
} else {
  $p4 = $p4cmd.Source
}

$env:P4PORT = $P4PORT
$env:P4USER = $P4USER
$env:P4CLIENT = $ClientName

$info = & $p4 info 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $info -match "Connect to server failed") {
  Write-Host @"
Cannot reach p4d at $P4PORT.

Install Helix Core Server (P4D) separately from P4V:
  https://www.perforce.com/downloads/helix-core-p4d
Then: pwsh -File tools/pipeline/p4/bootstrap_p4_server.ps1
      pwsh -File tools/pipeline/p4/first_library_submit.ps1

Library Content/ is ready on disk; binary history waits for p4d.
"@
  exit 4
}

$clientSpec = @"
Client: $ClientName
Owner:  $P4USER
Description: AuroraVellum Library workspace
Root:   $ProjectRoot
Options:        noallwrite noclobber nocompress unlocked nomodtime normdir
SubmitOptions:  submitunchanged
LineEnd:        local
View:
        //vellum_library/AuroraVellum/... //$ClientName/...
"@
$clientSpec | & $p4 client -i

$ignore = Join-Path $PSScriptRoot "p4ignore.txt"
if (Test-Path $ignore) {
  Copy-Item -Force $ignore (Join-Path $ProjectRoot ".p4ignore")
  & $p4 set P4IGNORE=.p4ignore
}

Push-Location $ProjectRoot
try {
  Write-Host "Reconciling Content/ ..."
  & $p4 reconcile -f "Content/..."
  & $p4 reconcile -f "AuroraVellum.uproject"
  & $p4 reconcile -f "Config/..."
  if ($DryRun) {
    & $p4 opened
    Write-Host "DryRun — no submit."
    exit 0
  }
  & $p4 submit -d "vellum-library: first submit Content + project config"
  Write-Host "First library submit complete."
  & $p4 changes -m 3
} finally {
  Pop-Location
}
