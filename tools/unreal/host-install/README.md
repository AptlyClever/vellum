# Vellum UE host install (Aurora)

Wraps Capture so you do **not** leave a PowerShell window open.

| Piece | Mechanism | Why |
| --- | --- | --- |
| **VellumUeAgent** | Scheduled Task (At logon, **interactive**) | Polls Vellum; launches UnrealEditor-Cmd in your GPU desktop session |
| **VellumLookdevWorkerEnsure** | Scheduled Task (At logon) | Optional warm Lookdev Worker (parked for Capture) |
| **VellumLookdevWorkerWatchdog** | Scheduled Task (every 5 min) | `host-heal.ps1`: git pull + restart agent task if code moved |

**Do not** run the agent as a WinSW/LocalSystem service. Session 0 + `systemprofile` DDC hangs GPU Cmd (confirmed 2026-07-13).

## Fix Capture now (Aurora)

```powershell
cd E:\Dev\vellum
git pull
pwsh -File tools/unreal/host-install/install-agent-interactive.ps1
```

Then click Capture in Vellum.

## Full install

```powershell
cd E:\Dev\vellum
git pull
pwsh -File tools/unreal/host-install/install.ps1
```

## Check

```powershell
Get-ScheduledTask VellumUeAgent, VellumLookdev*
Get-Service VellumUeAgent -ErrorAction SilentlyContinue   # should be absent
```

## Uninstall

```powershell
pwsh -File tools/unreal/host-install/uninstall.ps1
```
