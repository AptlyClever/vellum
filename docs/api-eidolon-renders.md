# Eidolon Renders API

Read-only gallery of **Eidolon-authored** render outputs (symbols, bezel plates,
sprite sheets), proxied through Vellum so the operator UI stays same-origin.

Vellum does **not** generate these images. Source of truth is Eidolon
(`EIDOLON_BASE_URL`, default `http://192.168.68.93:7860`).

Operator UI: Vellum → **Eidolon Renders** tab (between Asset Register and Visual Research).

## List

`GET /api/eidolon/renders?limit=200`

Flattens Eidolon `/api/batches` into gallery rows (newest first).

Example item:

```json
{
  "id": "batch-20260719-063428-2da65e6c/token_pink.png",
  "batch_id": "batch-20260719-063428-2da65e6c",
  "filename": "token_pink.png",
  "asset_name": "zo-zo-zoe-symbols",
  "label": "token_pink",
  "group": "symbols",
  "kind": "reel-symbol-set",
  "status": "done",
  "lane": "slots",
  "provider": "openai",
  "rendered_at": "2026-07-19T06:34:28+00:00",
  "width": 256,
  "height": 256,
  "resolution": "256×256",
  "file_url": "/api/eidolon/renders/batch-20260719-063428-2da65e6c/token_pink.png/file"
}
```

## File proxy

`GET /api/eidolon/renders/{batch_id}/{filename}/file`

Streams the matching Eidolon artifact (`/api/batches/{id}/artifacts/{filename}`).
