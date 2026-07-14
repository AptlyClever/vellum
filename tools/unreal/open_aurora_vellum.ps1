#Requires -Version 5.1
<#
.SYNOPSIS
  Open canonical AuroraVellum in UE 5.8 so Fab-in-Editor can Add to Project
  without using Epic Launcher's broken project picker.
#>
param(
  [string]$Project = "F:\Games\AuroraVellum\AuroraVellum.uproject",
  [string]$UeEditor = "F:\Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe"
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $Project)) { throw "Missing $Project" }
if (-not (Test-Path -LiteralPath $UeEditor)) { throw "Missing $UeEditor" }
Write-Host "Launching $UeEditor $Project"
Start-Process -FilePath $UeEditor -ArgumentList "`"$Project`""
Write-Host "In Unreal: Window/Fab (or Fab plugin) -> Add to THIS project. Do not use Epic Launcher Fab for Add to Project."
