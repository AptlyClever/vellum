# Shared PowerShell helpers for native-exe launch on Aurora.
# NEVER use `$null = & exe` or PS Process.ExitCode after redirects.

function Invoke-ExeQuiet {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string[]]$ArgumentList,
    [int]$TimeoutSec = 180,
    [switch]$CaptureStdoutToTemp
  )
  $stamp = [guid]::NewGuid().ToString("n")
  $ecFile = Join-Path $env:TEMP "vellum-exe-$stamp-ec.txt"
  $outFile = Join-Path $env:TEMP "vellum-exe-$stamp-out.txt"
  $errFile = Join-Path $env:TEMP "vellum-exe-$stamp-err.txt"
  $batFile = Join-Path $env:TEMP "vellum-exe-$stamp.bat"
  $exe = [string]$FilePath
  $argLine = @(
    foreach ($a in $ArgumentList) {
      $s = [string]$a
      if ($s -match '[\s"^&|<>%]') { '"' + ($s -replace '"', '""') + '"' } else { $s }
    }
  ) -join ' '
  if ($exe -match '[\s"]') { $exe = '"' + ($exe -replace '"', '""') + '"' }
  $lines = New-Object System.Collections.Generic.List[string]
  [void]$lines.Add("@echo off")
  [void]$lines.Add("setlocal EnableDelayedExpansion")
  if ($CaptureStdoutToTemp -and $argLine -notmatch '(^|\s)(-o|--output)(\s|$)') {
    [void]$lines.Add("$exe -o `"$outFile`" $argLine 2>`"$errFile`"")
  } else {
    [void]$lines.Add("$exe $argLine >`"$outFile`" 2>`"$errFile`"")
  }
  [void]$lines.Add("echo !ERRORLEVEL!>`"$ecFile`"")
  [void]$lines.Add("endlocal")
  Set-Content -LiteralPath $batFile -Value $lines -Encoding Ascii
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "cmd.exe"
  $psi.Arguments = "/c `"$batFile`""
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $p = New-Object System.Diagnostics.Process
  $p.StartInfo = $psi
  try {
    [void]$p.Start()
    # Poll — WaitForExit alone has hung on Aurora after the child already
    # wrote ecFile (stage jobs stuck "running" forever after Stage done).
    $deadline = [datetime]::UtcNow.AddSeconds([Math]::Max(5, $TimeoutSec))
    while (-not $p.HasExited) {
      if ([datetime]::UtcNow -gt $deadline) {
        try { $p.Kill($true) } catch { try { $p.Kill() } catch {} }
        break
      }
      if (Test-Path -LiteralPath $ecFile) {
        # Bat finished; cmd sometimes lingers — don't block the agent.
        Start-Sleep -Milliseconds 300
        if (-not $p.HasExited) {
          try { $p.Kill($true) } catch { try { $p.Kill() } catch {} }
        }
        break
      }
      Start-Sleep -Milliseconds 400
    }
    if (-not $p.HasExited) {
      try { $p.Kill($true) } catch { try { $p.Kill() } catch {} }
      return 124
    }
  } finally {
    try { $p.Close() } catch {}
  }
  $exitCode = 1
  if (Test-Path -LiteralPath $ecFile) {
    $raw = (Get-Content -LiteralPath $ecFile -Raw -ErrorAction SilentlyContinue | ForEach-Object { $_.Trim() })
    if ($raw -match '^-?\d+$') { $exitCode = [int]$raw }
  } else {
    return 124
  }
  Remove-Item -Force $ecFile, $outFile, $errFile, $batFile -ErrorAction SilentlyContinue
  return $exitCode
}

function Find-VellumPython {
  $candidates = @()
  if ($env:VELLUM_PYTHON) { $candidates += $env:VELLUM_PYTHON }
  $candidates += @(
    "C:\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Program Files\Python312\python.exe"
  )
  foreach ($cmdName in @("python", "py")) {
    $cmd = Get-Command $cmdName -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $candidates += $cmd.Source }
  }
  foreach ($c in $candidates) {
    if (-not $c) { continue }
    if ($c -like "*\WindowsApps\*") { continue }
    if (-not (Test-Path -LiteralPath $c)) { continue }
    if ((Get-Item -LiteralPath $c).Length -lt 1024) { continue }
    return $c
  }
  throw "No real Python found. Install with: choco install python312 -y"
}
