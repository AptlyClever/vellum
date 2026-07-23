# Control Alt Games Platform Operational Manifest

**Locked:** 2026-07-22  
**Governing CFD:** `cfd-inspiration-20260722-215000-control-alt-games-platform-expansion`  
**Purpose:** Consolidate context, ports, directory layouts, and execution APIs across the entire games platform to prevent context drift.

---

## 1. System Topology & Machine Roles

The Control Alt Games platform consists of 5 sibling repositories mapped across 3 distinct machine roles. **Never run production stack targets on the local studio dev machine.**

```
                           [ Studio Machine (Borealis) ]
                                 (Code, Commit, Push)
                                          │
                                          ▼
   [ Press Machine (192.168.68.93) ]               [ Factory Machine (Aurora) ]
    (Docker runtime, vault mount)                   (Perforce, UE, Baker, P4)
    ┌─────────────────────────────┐                  ┌────────────────────────┐
    │  Axiom Hub      (:7895)     │                  │  UE AuroraVellum       │
    │  Vellum Vault   (:8770)     │◄─────────────────┤  (Bake WebM/Ogg clips) │
    │  Proscenium     (:8788)     │                  └────────────────────────┘
    │  Eidolon Art    (:7860)     │
    │  Mneme Lore     (:8790)     │
    │  Bandit Slot    (:8766)     │
    └─────────────────────────────┘
```

### Port Registry & Sibling Locations (Press)
* **Axiom Hub (`:7895`):** Control plane, Theme SoT, `config/apps.registry.yaml`.
* **Vellum (`:8770`):** Asset vault & SQLite job worker. Staging: `/mnt/data/vault/vellum/01-source-bundles/`.
* **Proscenium (`:8788`):** Presentation engine & target router. Delivery registry: `config/presentation/delivery-targets.json`.
* **Eidolon (`:7860`):** Authored AI concept art generator, versioned briefs, stills desk.
* **Mneme (`:8790`):** Durable cross-project Markdown research & lore library.
* **Bandit (`:8766`):** Fake-credit slot game (playable `/game`, overlay `/overlay`).
* **LCARD (`:8184`):** Room Arcade Control Panel hardware & surface interface.

---

## 2. Interactive Studio UI Overview (Axiom Studio Leaf)

The **Axiom Games Studio** UI (`praxis-games`) embeds directly inside the Axiom viewport, providing a single visual dashboard for solo game development:

1. **Game Fleet Command Desk:**
   * Visual cards for **Bandit** (1st priority), **Threshold Affairs** (2nd priority), and **Field Ops** (ready).
   * Actions: **Test Hail** (fires Proscenium stingers), **Sync Lane** (delivers elements), and **Verify Godot** (scans for import errors).
2. **Production Briefs:**
   * Pulls concept art from Eidolon (`/api/batches`) and lore from Mneme (`/api/documents`) into visual cards.
   * Lets you click **"Preview on Stage"** to load assets into the viewport.
3. **Stage Viewport Preview:**
   * Embedded interactive viewport showing model metadata and active overlays.
   * Flashes live stinger alerts (`BIG WIN` or `ANOMALY DISCOVERED`).

---

## 3. Platform Integration Contracts

### A. Proscenium Presentation Contracts
Dobsonian runtimes trigger display overlays and audio stings by POSTing to Proscenium’s delivery router:

* **Endpoint:** `POST /api/presentation/products/{product_id}/show`
* **Field Ops Payload:**
```json
{
  "delivery_target_id": "arcade",
  "payload": {
    "event_type": "TACTICAL_OBJECTIVE_COMPLETE",
    "title": "OBJECTIVE COMPLETE",
    "message": "Sector 4 Outpost Secured",
    "theme": "tactical_amber",
    "glyph_hero": "shield_check",
    "duration_sec": 5,
    "audio_stinger": "audio/field_ops/stinger_objective_complete.ogg"
  }
}
```
* **Threshold Affairs Payload:**
```json
{
  "delivery_target_id": "operator_desk",
  "payload": {
    "event_type": "EVIDENCE_COLLECTED",
    "title": "EVIDENCE UNLOCKED",
    "message": "Motel Keycard #204 Cataloged",
    "theme": "mystery_cyan",
    "glyph_hero": "magnifying_glass",
    "duration_sec": 4,
    "audio_stinger": "audio/threshold_affairs/chime_clue_found.ogg"
  }
}
```

---

### B. Vellum Background Job Tasks
Vellum's SQLite job queue (`data/jobs.sqlite3`) automates deployment and engine verification:

1. **`lane_sync` Job Kind:**
   * Copies game-ready models, ORM textures, and Ogg audio from Vellum vault index to `<project_dir>/res/assets/vellum/`.
   * **Soft Quarantine:** Moves missing or broken assets to `.quarantine/` and logs alerts on `/api/ops/pulse`.
2. **`headless_verify` Job Kind:**
   * Executes headless scanner (`godot --headless -e --quit`).
   * Parses output for `ERROR:`, `Failed loading`, or script exceptions, reporting status back to the dashboard.

---

## 4. Operational Playtest Runbook

To run and test the complete loop manually:

1. **Trigger Hails Client Preview:**
   From Python or Vellum CLI:
   ```python
   from tools.proscenium_hails_client import trigger_game_hail
   trigger_game_hail("godot-threshold-affairs", "EVIDENCE_COLLECTED", "FOUND KEYCARD", "Room 204")
   ```
2. **Enqueue Delivery Job:**
   ```bash
   # Enqueue sync to local checkout
   curl -X POST http://192.168.68.93:8770/api/jobs \
     -H "Content-Type: application/json" \
     -d '{"kind": "lane_sync", "asset_id": "godot-threshold-affairs", "payload": {"lane": "godot-threshold-affairs", "target_dir": "C:/dev/threshold_affairs"}}'
   ```
3. **Verify Local Imports:**
   ```bash
   # Run headless verification check
   curl -X POST http://192.168.68.93:8770/api/jobs \
     -H "Content-Type: application/json" \
     -d '{"kind": "headless_verify", "asset_id": "godot-threshold-affairs", "payload": {"target_dir": "C:/dev/threshold_affairs"}}'
   ```
