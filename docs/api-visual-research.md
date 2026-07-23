# Visual Research API

Visual Research is a **standalone collection** of reference/inspiration images
stored inside the Vellum vault. These are **not** game-ready assets and are
labeled `asset_type: visual-research` / collection `Visual Research`.
Extracted source text is stored in **Mneme** and linked from the Vellum item.
The collection is shared across Control Alt projects; `project_id` identifies
the consumer (default `bandit`, configurable with `MNEME_DEFAULT_PROJECT_ID`).

Control Alt project agents use the **read** endpoints. Upload, patch, and delete
require `Authorization: Bearer <VELLUM_RESEARCH_WRITE_TOKEN>`.
Read-only agents must **not** receive the write token — unauthorized mutations return
HTTP **403** with `detail: "visual_research_read_only"`.

Operator UI: open Vellum → **Visual Research** tab
(`http://192.168.68.93:8770/`).

Persistence:

| Layer | Location |
| --- | --- |
| Catalog YAML | `data/visual-research.yaml` (compose) |
| Vault mirror | `/mnt/data/vault/vellum/02-index/visual-research.yaml` |
| Image bytes | `/mnt/data/vault/vellum/07-visual-research/<id>/` |

Supported formats (content-validated): **PNG, JPG, GIF, SVG, WebP, WebM, MP4**.

Video (WebM/MP4) is first-class for Theia look-continuity motion companions;
stills remain required for side-by-side review. Bytes live under the same
`07-visual-research/<id>/` vault path; `mime_type` is `video/webm` or
`video/mp4`.

## Read (Bandit-safe)

### List / search

`GET /api/visual-research?q=&project_id=&tag=&format=&limit=100&offset=0`

| Param | Description |
| --- | --- |
| `q` | Substring match on title, caption, tags, source URL, attribution, filename |
| `project_id` | Exact project match (case-insensitive), e.g. `bandit` |
| `tag` | Exact tag match (case-insensitive) |
| `format` | `png` \| `jpg` \| `gif` \| `webp` \| `svg` \| `webm` \| `mp4` (`jpeg` accepted as `jpg`) |
| `limit` | 1–1000 (default 100) |
| `offset` | Pagination offset |

Example response:

```json
{
  "schema_version": 1,
  "asset_type": "visual-research",
  "collection": "Visual Research",
  "count": 1,
  "total": 1,
  "offset": 0,
  "limit": 100,
  "items": [
    {
      "id": "vr-20260718-143012-a1b2c3",
      "asset_type": "visual-research",
      "collection": "Visual Research",
      "title": "Neon HUD mockup",
      "project_id": "bandit",
      "caption": "Inspiration for Bandit scoreboard",
      "tags": ["ui", "hud"],
      "source_url": "https://example.com/page",
      "captured_at": "2026-07-18T18:30:12+00:00",
      "created_at": "2026-07-18T18:30:12+00:00",
      "updated_at": "2026-07-18T18:30:12+00:00",
      "format": "png",
      "mime_type": "image/png",
      "original_filename": "hud.png",
      "byte_size": 48210,
      "width": 1280,
      "height": 720,
      "checksum_sha256": "…",
      "rights": "research-reference",
      "attribution": "Example Studio",
      "mneme_document_id": "doc-20260718-...",
      "mneme_document_url": "http://192.168.68.93:8790/api/documents/doc-20260718-...",
      "file_url": "/api/visual-research/vr-20260718-143012-a1b2c3/file"
    }
  ]
}
```

### Get one

`GET /api/visual-research/{id}` → same item shape (404 `visual_research_not_found`).

### Readable image bytes

`GET /api/visual-research/{id}/file`

Returns the stored file with the correct `Content-Type`. Paths are jailed under
the vault. Use this URL as an `<img src>` (or Bandit tool image fetch) for a
readable-size preview.

```
http://192.168.68.93:8770/api/visual-research/<id>/file
```

## Write (operator / automated capture only)

All write routes require:

```
Authorization: Bearer <VELLUM_RESEARCH_WRITE_TOKEN>
```

Unset or wrong token → **403** `visual_research_read_only`.

### Paired source bundle (preferred)

`POST /api/visual-research/bundles`

This is the required ingestion path when source text is available. One request
stores image bytes in Vellum, creates a Markdown research document in Mneme,
and persists cross-links. A successful response is returned only when both
records exist.

| Field | Required | Notes |
| --- | --- | --- |
| `file` | yes | Selected visual evidence bytes |
| `source_url` | yes | Original `http`/`https` page |
| `body` | yes | Extracted source text as Markdown (max 2,000,000 characters) |
| `project_id` | no | Mneme project; configured default is `bandit` |
| `title` | no | Defaults from filename |
| `caption` | no | Image-specific note |
| `captured_at` | no | ISO-8601; defaults to upload time |
| `tags` | no | Comma-separated |
| `rights` | no | Rights/research-use status |
| `attribution` | no | Credit/license note |
| `author` | no | Source author for Mneme |
| `publisher` | no | Source publisher for Mneme |

```bash
curl -sS -X POST "http://192.168.68.93:8770/api/visual-research/bundles" \
  -H "Authorization: Bearer $VELLUM_RESEARCH_WRITE_TOKEN" \
  -F "file=@./capture.png" \
  -F "project_id=bandit" \
  -F "title=Neon HUD mockup" \
  -F "source_url=https://example.com/page" \
  -F "body=<./captured-page.md" \
  -F "tags=ui,hud" \
  -F "rights=research-reference"
```

The Mneme document is tagged with `vellum-<visual-research-id>` and includes an
absolute link to the Vellum file. This deterministic tag is also used to
reconcile an ambiguous create timeout.

### Image-only upload (compatibility)

`POST /api/visual-research`

This legacy/operator endpoint stores only an image in Vellum. Prefer the paired
bundle endpoint for web research so source text is not lost.

Form fields:

| Field | Required | Notes |
| --- | --- | --- |
| `file` | yes | Image bytes |
| `title` | no | Defaults from filename |
| `caption` | no | Free text |
| `project_id` | no | Optional owning/consumer project |
| `source_url` | no | Must be `http`/`https` when set |
| `captured_at` | no | ISO-8601; defaults to upload time |
| `tags` | no | Comma-separated |
| `rights` | no | Optional rights status |
| `attribution` | no | Optional credit / license note |

curl (automated capture tool):

```bash
curl -sS -X POST "http://192.168.68.93:8770/api/visual-research" \
  -H "Authorization: Bearer $VELLUM_RESEARCH_WRITE_TOKEN" \
  -F "file=@./capture.png" \
  -F "title=Neon HUD mockup" \
  -F "source_url=https://example.com/page" \
  -F "caption=Scoreboard inspiration" \
  -F "tags=ui,hud" \
  -F "rights=research-reference" \
  -F "attribution=Example Studio"
```

### Patch metadata

`PATCH /api/visual-research/{id}`

```json
{
  "title": "Updated title",
  "caption": "…",
  "tags": ["ui"],
  "source_url": "https://example.com/page",
  "captured_at": "2026-07-18T12:00:00+00:00",
  "rights": "research-reference",
  "attribution": "Example Studio"
}
```

### Delete

`DELETE /api/visual-research/{id}` — removes catalog row and vault files.

## Project-agent contract

1. **Browse/search:** `GET /api/visual-research?q=…`
2. **View:** `GET /api/visual-research/{id}/file` (readable image)
3. **Distinguish from game assets:** every item has
   `asset_type: "visual-research"` and `collection: "Visual Research"`.
   Do not mix with `/api/game-ready/elements` or lookdev outputs.
4. **Read-only:** project agents must not send either write token. Any Vellum
   `POST`/`PATCH`/`DELETE` without its token returns:

```json
{"detail": "visual_research_read_only"}
```

5. **Source text:** follow `mneme_document_url`, or query Mneme directly by
   `project_id` / the `vellum-<id>` tag. Mneme reads require no token.
6. **Ingestion:** external capture tools submit selected image bytes, extracted
   Markdown, and the source URL to the paired bundle endpoint. LLM agents in
   Bandit or any other Control Alt project consume these APIs directly; no
   native Bandit UI or proxy is required.

## Compose / secrets

The write tokens are shared secrets. Their canonical Vellum-side home is the
press host:

```
/mnt/temp/config/vellum/.env
  VELLUM_RESEARCH_WRITE_TOKEN=…
  MNEME_WRITE_TOKEN=…
```

That file is gitignored (never commit it) and survives Repo Ops deploys —
`git.sync.origin` uses `git clean -fd`, which preserves gitignored files.
Docker Compose reads them through environment substitution. Operators provision
and rotate them on the press; agents must not read the press filesystem.
Authorized capture tools send only `VELLUM_RESEARCH_WRITE_TOKEN` to Vellum.
Do not bake either token into any repo, doc, handoff, or Cue. Read-only
consumers must never receive them.

The Vellum web UI remembers the token in browser `localStorage` after the
first successful upload; that copy is for the human operator only.

Compose wires:

- `VELLUM_RESEARCH_PATH`
- `VELLUM_VAULT_RESEARCH_PATH`
- `VELLUM_RESEARCH_WRITE_TOKEN`
- `VELLUM_PUBLIC_BASE_URL`
- `MNEME_BASE_URL`
- `MNEME_DEFAULT_PROJECT_ID`
- `MNEME_WRITE_TOKEN`

`MNEME_WRITE_TOKEN` is server-to-server only. Vellum uses it to create the
paired Mneme document; capture clients and read-only agents never receive it.
