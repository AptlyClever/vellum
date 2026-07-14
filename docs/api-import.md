# Import pack API

Operator stays in Vellum. Hub → Aurora agent installs from Epic VaultCache and
stages Content into the vault.

## Human gate (locked 2026-07-14, revised same day)

**Do not use Epic Games Launcher → Fab → Add to Project** for Vellum.
Launcher project picker is unreliable for `F:\Games\AuroraVellum`.

**Primary path (agent-owned):**

1. Epic has already downloaded owned packs into
   `C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\<pack>\data\Content\`.
2. Vellum **Install from VaultCache** → job `host_fab_install` robocopies into
   `F:\Games\AuroraVellum\Content\` (no Fab UI).
3. Agent refreshes Content scan, marks in_project, optionally **Stage to vault**.

**Fallback** (pack missing from VaultCache — incomplete or never downloaded):

Agent-owned VaultCache fill (batch when possible), then **Install from VaultCache**.
Do **not** close this path by dumping N× “open Fab and Add to Project” onto the
operator after assuring Fab work was finished. Manual Fab-in-editor remains an
emergency last resort with operator consent, not the default finish plan.

| Step | Who | API / UI |
| --- | --- | --- |
| Redeemed | Operator or auto on install | `POST /api/assets/{id}/import/mark` `{step:"redeemed"}` |
| Install into F: Content | Aurora agent | `POST …/import/fab-install` → `host_fab_install` |
| Batch install | Operator | `POST /api/import/fab-install-batch` |
| In project | Auto after install / mark | pick scanned folder → mark |
| Open editor | Aurora agent | `POST /api/ue/hosts/open-editor` → `host_open_editor` |
| Content folders | Aurora scan | `GET /api/ue/hosts/content-folders` · `POST …/refresh` → `host_scan` |
| Stage | Aurora agent | `POST …/import/stage` → `host_stage` |
| After stage (required) | Agent auto-enqueue | **texture** packs → `derive_lookdev`; **Niagara/VFX** → `ue_capture` (MRQ). Fab catalog thumbs are preview-only for Niagara — they do **not** satisfy lookdev. |

`POST /api/jobs/claim` will not start a second `ue_capture` while one is already `running` (single-flight).

**Stale runner watchdog:** if a UE-agent job stays `running` with no progress heartbeat for `VELLUM_STALE_JOB_SEC` (default **180s**), claim/sweep fails it (`stale_agent_silence`) so the queue is not wedged by a dead PowerShell/Unreal. Endpoints: automatic on `POST /api/jobs/claim`, explicit `POST /api/jobs/sweep-stale`.

Mapping: `config/fab-vault-install-map.json` (asset id → VaultCache Content relative paths).

Coverage: `GET /api/import/coverage` includes `vault_installable` vs still need Epic download.

**Free or extra Epic packs** (Fab cookies): after Add to Project, **Refresh folders**.
Coverage lists **Content orphans** → **Register & Stage** (batch or per folder).
API: `POST /api/import/register-orphans` `{folders?: [...], auto_stage: true}`.
Also: `POST /api/assets` with `display_name` + `content_folder_name` / `host_content_path`.
