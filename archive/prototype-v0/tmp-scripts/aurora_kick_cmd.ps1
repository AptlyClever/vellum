$ErrorActionPreference = 'Continue'
Write-Host 'Kill agents + all Unreal (GUI was idle-blocking Cmd)...'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match 'vellum_ue_agent\.ps1' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host "Kill $($_.ProcessName) $($_.Id)"; Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
Start-Sleep 10

# Fresh agent logs
$out='E:\Dev\vellum\tmp\agent-out.log'; $err='E:\Dev\vellum\tmp\agent-err.log'
Remove-Item $out,$err -ErrorAction SilentlyContinue

# Ensure latest agent script (Epic batch default)
Start-Process pwsh -ArgumentList @(
  '-NoProfile','-ExecutionPolicy','Bypass',
  '-File','E:\Dev\vellum\tools\unreal\vellum_ue_agent.ps1',
  '-VellumBase','http://192.168.68.93:8770','-HostName','aurora','-SkipHostHeal'
) -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden

# Wait until Cmd is actually running or log shows Phase
$deadline = (Get-Date).AddMinutes(3)
do {
  Start-Sleep 5
  $cmd = Get-Process UnrealEditor-Cmd -ErrorAction SilentlyContinue
  $tail = if (Test-Path $out) { Get-Content $out -Tail 8 } else { @() }
  Write-Host ("t={0} cmd={1}" -f (Get-Date -Format HH:mm:ss), ($(if($cmd){$cmd.Id -join ','}else{'none'})))
  $tail | ForEach-Object { Write-Host "  $_" }
  if ($cmd) { break }
  if ($tail -match 'Phase A inventory pid=') { }
} while ((Get-Date) -lt $deadline)

Write-Host '=== FINAL ==='
Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("{0} {1} MB={2}" -f $_.ProcessName, $_.Id, [int]($_.WorkingSet64/1MB)) }
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vellum_ue_agent\.ps1' } |
  ForEach-Object { $r=if($_.CommandLine -match 'SidecarOnly'){'SIDECAR'}else{'PRIMARY'}; Write-Host "$r $($_.ProcessId)" }
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
Get-Content $out -Tail 15 -ErrorAction SilentlyContinue
