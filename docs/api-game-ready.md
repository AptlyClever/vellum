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

## Publish to lane

`POST /api/game-ready/elements/{id}/publish`

```json
{ "lane": "slots" }
```

Copies into `05-derived-renders/<lane>/<asset>/game-ready/<kind>/` and records `lanes` + `lane_paths`.
