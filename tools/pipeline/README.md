# Vellum Conversion Factory

Headless Unreal jobs that turn Library packs into **game-ready** portable assets.

| Job | Script | Output |
| --- | --- | --- |
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

Wrappers: `tools/pipeline/run_job.ps1 -Job export-models -Pack FireworksV1`.

CI: `tools/pipeline/ci/README.md` + `.github/workflows/vellum-pipeline.yml`.

Success gate = artifacts on disk matching the job manifest (`manifest.json`).
