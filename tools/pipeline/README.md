# Vellum Conversion Factory

Headless Unreal jobs that turn Library packs into **game-ready** portable assets.

| Job | Script | Output |
| --- | --- | --- |
| inventory-pack | `jobs/inventory_pack.py` | asset-class counts + load-check manifest; no exported binaries |
| export-models | `jobs/export_models.py` | glTF/GLB under vault `game-ready/models/` |
| bake-vfx | `jobs/bake_vfx.py` + `jobs/pack_vfx_media.ps1` | sprite sheets + transparent WebM |
| export-media | `jobs/export_media.py` | textures (PNG) + audio (WAV/OGG) |

## Invocation pattern

```powershell
$ue = "F:\Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$proj = "F:\Games\AuroraVellum\AuroraVellum.uproject"
$script = "E:\Dev\vellum\tools\pipeline\jobs\export_models.py"
& $ue $proj `
  -unattended -nopause -nosplash -NullRHI `
  "-ExecutePythonScript=$script" `
  -AbsLog="F:\Games\AuroraVellum\Saved\VellumPipeline\export-models.log"
```

GPU jobs (`bake-vfx`) omit `-NullRHI`.

Wrappers: `tools/pipeline/run_job.ps1 -Job inventory-pack -Pack FireworksV1`.

Targeted VFX render proof (exclusive; do not run inside the parallel
`factory-all` worker pool):

```powershell
pwsh -NoProfile -File tools\pipeline\run_job.ps1 `
  -Job bake-vfx -Pack FireworksV1 -RunVfxMrq -MaxVfxSystems 1
```

`-RunVfxMrq` consumes the bake plan, authors run-scoped MRQ scratch assets under
`/Game/Vellum/PipelineScratch/...`, renders PNG frames, then runs
`pack_vfx_media.ps1`. If `ffmpeg` is on `PATH`, the packer also emits WebM;
otherwise it still emits and validates a sprite sheet from the rendered frames.

CI: `tools/pipeline/ci/README.md` + `.github/workflows/vellum-pipeline.yml`.

Success gate = artifacts on disk matching the job manifest (`manifest.json`).
