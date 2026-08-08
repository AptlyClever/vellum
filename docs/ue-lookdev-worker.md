# Vellum Lookdev Worker — FROZEN

**Status:** frozen / parked (2026-07-14)  
**Product SoT:** [`docs/asset-pipeline-product.md`](./asset-pipeline-product.md)  
**Historical binding that briefly replaced Cmd capture:** this file previously claimed Option 1 (warm UE + HTTP `:8771`) as primary. That path caused orphaned jobs and `mrq_never_started_rendering`. Parked.

Unpark phrase (operator only): `Unpark: Lookdev Worker`.

Retained files for archaeology (not product path):

- `tools/unreal/vellum_ue_worker.ps1`
- `tools/unreal/vellum_ue_worker_boot.py`
- `tools/unreal/host-install/` (WinSW / logon task remnants)

The Conversion Factory uses headless `UnrealEditor-Cmd` jobs under `tools/pipeline/` driven by a CI runner, not a warm in-process HTTP worker.
