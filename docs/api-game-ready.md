# Game-ready catalog API

Portable Conversion Factory outputs (glTF, VFX clips, textures, audio) — distinct from lookdev hero photos.

**Product SoT:** [`asset-pipeline-product.md`](./asset-pipeline-product.md)

## List

`GET /api/game-ready/elements?asset_id=&kind=&lane=&limit=`

Kinds: `vfx-clip`, `sprite-sheet`, `model-gltf`, `texture`, `audio`, `bake-plan`, `manifest`.

## Get / file

- `GET /api/game-ready/elements/{id}`
- `GET /api/game-ready/elements/{id}/file`

## Ingest factory manifest

`POST /api/game-ready/ingest-manifest`

```json
{
  "asset_id": "fireworks-vol-1-niagara",
  "pack": "FireworksV1",
  "manifest_path": "/path/to/export-models.manifest.json"
}
```

Copies referenced artifacts under vault `05-derived-renders/game-ready/` and appends catalog rows (`data/game-ready.yaml` + vault index).

This path is retained for targeted/manual manifest ingestion. Normal Aurora
operation uses the run-upload endpoint below.

## Upload a factory run

`POST /api/assets/{asset_id}/game-ready/upload-run`

Multipart form:

- `pack`: Unreal Content folder / factory pack name
- `archive`: ZIP produced by `tools/pipeline/pack_factory_run.ps1`

The hub:

1. extracts the run;
2. recognizes portable files and manifests;
3. copies them under vault `05-derived-renders/game-ready/`;
4. replaces prior catalog rows for the same asset + pack;
5. writes the local and vault-mirror catalogs once.

Recognized file mappings:

| Extension/file | Catalog kind |
| --- | --- |
| `.glb`, `.gltf` | `model-gltf` |
| `.png`, `.jpg`, `.jpeg`, `.webp` | `texture` |
| `.wav`, `.ogg`, `.mp3` | `audio` |
| `.webm` | `vfx-clip` |
| `*.sprite-sheet.png` under `vfx/` | `sprite-sheet` |
| `bake-plan.json`, VFX manifests | `bake-plan` |
| other `*manifest.json` | `manifest` |

Ingest is capped at 500 rows per run. Aurora smart-ZIP packing sends at most
480 files to leave room for manifests.

Example response:

```json
{
  "schema_version": 1,
  "ok": true,
  "asset_id": "fireworks-vol-1-niagara",
  "pack": "FireworksV1",
  "registered": 42,
  "skipped": 0
}
```

Catalog presence is **conversion evidence**, not a final quality guarantee.
A `bake-plan` proves discovery/planning only; playable VFX requires a
`vfx-clip` or `sprite-sheet` that passes the acceptance gates in
[`factory-operations.md`](./factory-operations.md).

When `pack_vfx_media.ps1` writes `pack-manifest.json`, upload ingest carries
per-system validation metadata onto VFX rows: frame count, dimensions, alpha,
duration, and non-empty motion evidence.

## Publish to lane

`POST /api/game-ready/elements/{id}/publish`

```json
{ "lane": "slots" }
```

Copies into `05-derived-renders/<lane>/<asset>/game-ready/<kind>/` and records `lanes` + `lane_paths`.
