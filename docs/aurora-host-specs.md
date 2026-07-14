# Aurora (primary UE capture host) — hardware snapshot

Collected by `tools/unreal/report_host_specs.ps1` → `POST /api/ue/hosts/specs`
(live API is source of truth; this file is a human mirror for planning).

**As of 2026-07-13:**

| Field | Value |
| --- | --- |
| Hostname | AURORA |
| Board | ASUS (generic “System Product Name”) |
| OS | Windows 11 Pro 64-bit (10.0.26200) |
| CPU | Intel Core i7-10700 @ 2.90 GHz — **8 cores / 16 threads** |
| RAM | **64 GB** |
| GPU | **NVIDIA GeForce RTX 4070** (also shows RDP “Microsoft Remote Display Adapter” when agent runs over Remote Desktop) |
| Win32 AdapterRAM | reports ~4 GB (known Win32 DWORD lie — ignore; use nvidia-smi on next agent restart) |
| Volumes | C: ~953 GB (215 free) · D: ~894 (125) · E: ~931 (598) · **F: ~1863 GB (733 free)** — UE project + Game on F: |
| UE | `F:\Games\UE_5.8\…` · project `F:\Games\AuroraVellum` |

## Planning implications

- This is a **strong single-GPU creator box**, not a weak laptop — MRQ should saturate the 4070 during Phase C; idle time elsewhere is pipeline structure, not weak silicon.
- **8c/16t + 64 GB** is comfortable for Editor inventory/author; bottleneck remains **UE process cold starts** and **serial MRQ**, not RAM.
- Prefer work on **F:** (UE + capture I/O) where free space is largest.
- When judging GPU util over **RDP**, ignore the Remote Display adapter; look at the 4070 / nvidia-smi.

## Utilization doctrine (not ghetto, not Horde)

| Do | Don't |
| --- | --- |
| **One** warm `UnrealEditor` on AuroraVellum for MRQ (same `.uproject` = DDC/asset lock) | Spin two Editors on the same project and call it “scale” |
| Auto-`POST /api/ops/drain` so on-disk packs keep the worker fed | Leave Ready% stuck while agent idles with work on F: |
| Sidecar agent (`-SidecarOnly`) for `host_fab_install` / scan / stage overlapping capture | Block the whole Windows agent on one MRQ wait with CPU/disk idle |
| Publish `nvidia-smi` util into Live ops (`/api/ue/hosts/util` → pulse.host) | Assume the machine is busy because a job row says `running` |
| Linux `vellum-worker` for `derive_lookdev` concurrent with Windows capture | Serialize texture derive behind MRQ |

**Not yet:** second project clone / Horde multi-machine. That is a deliberate future cut when single-project MRQ is proven green.
