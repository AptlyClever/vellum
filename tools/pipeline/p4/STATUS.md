# P4 Library status (Aurora)

| Item | State |
| --- | --- |
| Helix Visual Client (`p4` / P4V) | Installed (`C:\Program Files\Perforce\p4.exe`) |
| Helix Core Server (`p4d`) | Running; `localhost:1666`; root `F:\Perforce\vellum-library` |
| Server config | `security=0`, `dm.user.noautocreate=0`, `lbr.autocompress=1` (set OFFLINE via `p4d -r <root> "-cset var=value"` — the whole `var=value` must be one quoted argument, and it must happen before first start on 2026.1) |
| User / depot / client | `jaked` / `//vellum_library` / `aurora-vellum-library` created 2026-07-14 |
| First full submit of `Content/` | Changelist 1 (11,861 files, ~82 GB) submitted 2026-07-14 |

## Gotcha learned the hard way

P4D 2026.1 on a fresh database demands a password ("Perforce password (P4PASSWD)
invalid or unset") for **every** command unless `security=0` is written into the
db.config **while the server is stopped**, before the first user is created. A
stale `P4PASSWD` in the Windows registry (`p4 set P4PASSWD=...`) causes the same
error; clear it with `p4 set P4PASSWD=`.

## Hardening later (optional)

1. Run `p4d` as a Windows service (official installer or WinSW) so it survives reboots.
2. Raise `security`, set a real password, `p4 protect` to lock down super access.
3. Checkpoint schedule: `p4d -r F:\Perforce\vellum-library -jc` weekly.

## Everyday use

```powershell
$env:P4PORT='localhost:1666'; $env:P4USER='jaked'; $env:P4CLIENT='aurora-vellum-library'
p4 reconcile Content/...
p4 submit -d "Add pack <name>"
```
