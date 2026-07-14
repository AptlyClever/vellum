#Requires -Version 7.0
param(
  [string]$GitHubRepo = "AptlyClever/vellum",
  [Parameter(Mandatory = $true)][string]$Token,
  [string]$RunnerDir = "C:\actions-runner\vellum",
  [string]$Labels = "self-hosted,Windows,aurora-vellum"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $RunnerDir | Out-Null

# Download latest Actions runner (Windows x64)
$api = "https://api.github.com/repos/actions/runner/releases/latest"
$rel = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "vellum-pipeline" }
$asset = $rel.assets | Where-Object { $_.name -match "win-x64.*\.zip$" } | Select-Object -First 1
if (-not $asset) { throw "Could not find win-x64 runner asset" }
$zip = Join-Path $env:TEMP $asset.name
Write-Host "Downloading $($asset.browser_download_url)"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $RunnerDir -Force

Push-Location $RunnerDir
try {
  & .\config.cmd --url "https://github.com/$GitHubRepo" --token $Token --name "aurora-vellum" --labels $Labels --unattended --replace
  Write-Host "Configured. Start with: .\run.cmd  (interactive session; do not run as SERVICE for Unreal GPU jobs)"
  Write-Host "Optional: register as user-level startup, not LocalSystem."
} finally {
  Pop-Location
}
