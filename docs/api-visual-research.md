# Visual Research API

Visual Research is a **standalone collection** of reference/inspiration images
stored inside the Vellum vault. These are **not** game-ready assets and are
labeled `asset_type: visual-research` / collection `Visual Research`.

Bandit agents (and other LAN consumers) use the **read** endpoints. Upload,
patch, and delete require `Authorization: Bearer <VELLUM_RESEARCH_WRITE_TOKEN>`.
Bandit must **not** receive the write token — unauthorized mutations return
HTTP **403** with `detail: "visual_research_read_only"`.

Operator UI: open Vellum → **Visual Research** tab
(`http://192.168.68.93:8770/`).

Persistence:

| Layer | Location |
| --- | --- |
| Catalog YAML | `data/visual-research.yaml` (compose) |
| Vault mirror | `/mnt/data/vault/vellum/02-index/visual-research.yaml` |
| Image bytes | `/mnt/data/vault/vellum/07-visual-research/<id>/` |

Supported formats (content-validated): **PNG, JPG, GIF, SVG, WebP**.

## Read (Bandit-safe)

### List / search

`GET /api/visual-research?q=&tag=&format=&limit=100&offset=0`

| Param | Description |
| --- | --- |
| `q` | Substring match on title, caption, tags, source URL, attribution, filename |
| `tag` | Exact tag match (case-insensitive) |
| `format` | `png` \| `jpg` \| `gif` \| `webp` \| `svg` (`jpeg` accepted as `jpg`) |
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

### Upload (multipart)

`POST /api/visual-research`

Form fields:

| Field | Required | Notes |
| --- | --- | --- |
| `file` | yes | Image bytes |
| `title` | no | Defaults from filename |
| `caption` | no | Free text |
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

## Bandit contract

1. **Browse/search:** `GET /api/visual-research?q=…`
2. **View:** `GET /api/visual-research/{id}/file` (readable image)
3. **Distinguish from game assets:** every item has
   `asset_type: "visual-research"` and `collection: "Visual Research"`.
   Do not mix with `/api/game-ready/elements` or lookdev outputs.
4. **Read-only:** Bandit must not send the write token. Any `POST`/`PATCH`/`DELETE`
   without it returns:

```json
{"detail": "visual_research_read_only"}
```

5. **Ingestion:** external capture tools (or the Vellum UI upload form) push
   files into Vellum; Bandit only consumes the catalog.

> The Bandit-side browser/agent tool that calls these endpoints lives in the
> Bandit repository. This API is the Vellum half of the contract.

## Compose / secrets

The write token is a shared secret. Its canonical home is the press host:

```
/mnt/temp/config/vellum/.env   →   VELLUM_RESEARCH_WRITE_TOKEN=…
```

That file is gitignored (never commit it) and survives Repo Ops deploys —
`git.sync.origin` uses `git clean -fd`, which preserves gitignored files.
Docker Compose reads it automatically for the
`${VELLUM_RESEARCH_WRITE_TOKEN:-}` substitution in `docker-compose.yml`.

**Agents that need to WRITE visual research** (ingest/capture tools) fetch it
from the press:

```bash
ssh dev-ubuntu "grep VELLUM_RESEARCH_WRITE_TOKEN /mnt/temp/config/vellum/.env | cut -d= -f2-"
```

Then send it as `Authorization: Bearer <token>` on each request. Do not bake
it into any repo, doc, handoff, or Cue. Bandit and other read-only consumers
must never receive it.

The Vellum web UI remembers the token in browser `localStorage` after the
first successful upload; that copy is for the human operator only.

Compose wires:

- `VELLUM_RESEARCH_PATH`
- `VELLUM_VAULT_RESEARCH_PATH`
- `VELLUM_RESEARCH_WRITE_TOKEN`
