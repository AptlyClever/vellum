# Vellum UE host install (Aurora)

Wraps Capture so you do **not** leave a PowerShell window open.

| Piece | Mechanism | Why |
| --- | --- | --- |
| **VellumUeAgent** | Windows Service (WinSW) | Polls Vellum forever; restarts on crash |
| **VellumLookdevWorkerEnsure** | Scheduled Task (At logon) | Starts warm Unreal in your interactive GPU session |
| **VellumLookdevWorkerWatchdog** | Scheduled Task (every 5 min) | Re-Ensure if `http://127.0.0.1:8771/health` dies |

Unreal itself is **not** a Session 0 service (GPU/editor reality). The service is the agent; the editor is warmed at logon.

## Install (once, Admin)

```powershell
cd E:\Dev\vellum   # or your ue-hosts.json repo path
git pull
pwsh -File tools/unreal/host-install/install.ps1 -StartWorkerNow
```

## Check

```powershell
Get-Service VellumUeAgent
Get-ScheduledTask VellumLookdev*
Invoke-RestMethod http://127.0.0.1:8771/health
```

## Uninstall

```powershell
pwsh -File tools/unreal/host-install/uninstall.ps1
```

## Notes

- `runtime/` (WinSW exe, stamped XML, logs) is local machine state — gitignored.
- Delayed auto-start on the service gives logon a moment to bring UE up first.
- The **agent service** runs as LocalSystem and must **not** launch Unreal; the **logon task** (or `-StartWorkerNow` / interactive Ensure) warms the GPU editor. If you Capture before anyone is logged in, the agent waits for health then fails clearly.
- Auto-logon on a locked studio PC makes reboot → Capture fully hands-off; optional.
