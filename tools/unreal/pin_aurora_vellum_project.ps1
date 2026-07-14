#Requires -Version 5.1
<#
.SYNOPSIS
  Pin F:\Games\AuroraVellum as the only Aurora Unreal project Fab/UE remember.

.DESCRIPTION
  Fab/UE rebuild recent-project lists from EditorSettings + ProjectEditorRecords.
  Stale C:\dev and typo AuroraVallum entries make the real F: project look like it
  "disappears" after close. This rewrites those lists to the canonical path only.

  Closes Epic Games Launcher / UnrealEditor briefly so configs are not overwritten
  on exit with in-memory ghosts.
#>
param(
  [string]$Project = "F:\Games\AuroraVellum\AuroraVellum.uproject",
  [string]$UeEditor = "F:\Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe",
  [switch]$SkipKill
)

$ErrorActionPreference = "Stop"
$ProjectFwd = ($Project -replace "\\", "/")
$ProjectDir = Split-Path $Project -Parent

if (-not (Test-Path -LiteralPath $Project)) {
  throw "Missing uproject: $Project"
}

function Stop-NamedProcesses([string[]]$Names) {
  foreach ($n in $Names) {
    Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object {
      Write-Host "Stopping $($_.ProcessName) pid=$($_.Id)"
      Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
  }
  Start-Sleep -Seconds 2
}

if (-not $SkipKill) {
  Write-Host "=== Stopping Launcher/Editor so they cannot rewrite config on exit ==="
  Stop-NamedProcesses @(
    "EpicGamesLauncher",
    "EpicWebHelper",
    "UnrealEditor",
    "UnrealEditor-Cmd",
    "Fab"
  )
}

$now = (Get-Date).ToUniversalTime().ToString("yyyy.MM.dd-HH.mm.ss")
$recordsPath = Join-Path $env:LOCALAPPDATA "UnrealEngine\Editor\ProjectEditorRecords.json"
$autoPath = Join-Path $env:LOCALAPPDATA "UnrealEngine\5.8\Saved\AutoLoadProject.txt"
$editorSettings = Join-Path $env:LOCALAPPDATA "UnrealEngine\5.8\Saved\Config\WindowsEditor\EditorSettings.ini"

Write-Host "=== ProjectEditorRecords.json ==="
$recordsDir = Split-Path $recordsPath -Parent
New-Item -ItemType Directory -Force -Path $recordsDir | Out-Null
$baseDir = ((Split-Path $UeEditor -Parent) -replace "\\", "/") + "/"
$doc = [ordered]@{
  Projects = [ordered]@{
    LastAccessed = $now
  }
}
# Dynamic path key
$doc.Projects[$ProjectFwd] = [ordered]@{
  EngineLocation = $UeEditor
  BaseDir        = $baseDir
  LastAccessed   = $now
}
($doc | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $recordsPath -Encoding UTF8
Write-Host "Wrote $recordsPath"

Write-Host "=== AutoLoadProject.txt ==="
$autoDir = Split-Path $autoPath -Parent
New-Item -ItemType Directory -Force -Path $autoDir | Out-Null
Set-Content -LiteralPath $autoPath -Value $ProjectFwd -Encoding ASCII -NoNewline
Write-Host "Wrote $autoPath -> $ProjectFwd"

Write-Host "=== EditorSettings.ini RecentlyOpened / CreatedProjectPaths ==="
if (-not (Test-Path -LiteralPath $editorSettings)) {
  throw "Missing EditorSettings.ini: $editorSettings"
}
$raw = Get-Content -LiteralPath $editorSettings -Raw -Encoding UTF8
# Drop stale created/recent lines
$lines = $raw -split "`r?`n"
$out = New-Object System.Collections.Generic.List[string]
$inEditorSettings = $false
$injected = $false
foreach ($line in $lines) {
  if ($line -match '^\[/Script/UnrealEd\.EditorSettings\]') {
    $inEditorSettings = $true
    $out.Add($line) | Out-Null
    continue
  }
  if ($inEditorSettings -and $line -match '^\[') {
    if (-not $injected) {
      $out.Add("CreatedProjectPaths=$ProjectDir") | Out-Null
      $out.Add("RecentlyOpenedProjectFiles=(ProjectName=`"$ProjectFwd`",LastOpenTime=$now)") | Out-Null
      $injected = $true
    }
    $inEditorSettings = $false
  }
  if ($inEditorSettings -and (
      $line -match '^CreatedProjectPaths=' -or
      $line -match '^RecentlyOpenedProjectFiles='
    )) {
    continue
  }
  $out.Add($line) | Out-Null
}
if ($inEditorSettings -and -not $injected) {
  $out.Add("CreatedProjectPaths=$ProjectDir") | Out-Null
  $out.Add("RecentlyOpenedProjectFiles=(ProjectName=`"$ProjectFwd`",LastOpenTime=$now)") | Out-Null
}
Set-Content -LiteralPath $editorSettings -Value ($out -join "`r`n") -Encoding UTF8
Write-Host "Wrote $editorSettings"

# Remove empty typo nest that still appears in recent-project ghosts
$nested = Join-Path $ProjectDir "AuroraVallum"
if (Test-Path -LiteralPath $nested) {
  $files = @(Get-ChildItem -LiteralPath $nested -Recurse -Force -ErrorAction SilentlyContinue)
  if ($files.Count -eq 0) {
    Remove-Item -LiteralPath $nested -Recurse -Force
    Write-Host "Removed empty nest $nested"
  } else {
    Write-Host "Left non-empty nest $nested ($($files.Count) items) - inspect manually"
  }
}

Write-Host "=== Done ==="
Write-Host "Canonical: $Project"
Write-Host "Reopen Epic Games Launcher. In Fab Add to Project, pick AuroraVellum on F: only."
Write-Host "If the list is empty, Browse once to: $Project"
