Write-Host '=== UE ==='
Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("{0} pid={1} MB={2}" -f $_.ProcessName, $_.Id, [int]($_.WorkingSet64/1MB)) }
Write-Host '=== agents ==='
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match 'vellum_ue_agent\.ps1' } | ForEach-Object {
  $role = if ($_.CommandLine -match 'SidecarOnly') {'SIDECAR'} else {'PRIMARY'}
  Write-Host "$role $($_.ProcessId)"
}
Write-Host '=== agent OUT ==='
if (Test-Path E:\Dev\vellum\tmp\agent-out.log) { Get-Content E:\Dev\vellum\tmp\agent-out.log -Tail 40 }
Write-Host '=== agent ERR ==='
if (Test-Path E:\Dev\vellum\tmp\agent-err.log) { Get-Content E:\Dev\vellum\tmp\agent-err.log -Tail 20 }
Write-Host '=== nvidia ==='
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
