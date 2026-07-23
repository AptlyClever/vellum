# Proscenium Dobsonian Game Contracts (binding)

**Locked:** 2026-07-22  
**Status:** active contract  
**Governing CFD:** `cfd-inspiration-20260722-215000-control-alt-games-platform-expansion`  
**Related:** Proscenium [`delivery-targets.json`](file:///C:/dev/proscenium/docs/presentation-delivery.md), Proscenium [`delivery.py`](file:///C:/dev/proscenium/backend/presentation/delivery.py)

---

## 1. Overview

This contract defines how **Field Ops** (`godot-field-ops`) and **Threshold Affairs** (`godot-threshold-affairs`) send visual Hails, celebration stingers, and audio cues to **Proscenium** (`http://192.168.68.93:8788`).

Proscenium acts as the home presentation authority. Games do not hold device URLs; instead, they send product events to Proscenium's delivery API, which routes them to physical display targets (`arcade`, `master_bedroom`, `away_team`, `operator_desk`) or the Android TV `overlay-apk/` compositor.

---

## 2. API Endpoints

* **Get Capabilities:** `GET http://192.168.68.93:8788/api/presentation/products`
* **Trigger Presentation Action:** `POST http://192.168.68.93:8788/api/presentation/products/{product_id}/show`
* **Dismiss Presentation Action:** `POST http://192.168.68.93:8788/api/presentation/products/{product_id}/show`

---

## 3. Product Event Schemas

### A. Field Ops (`godot-field-ops`) — Tactical Events

Default Target: `operator_desk` (configurable via `delivery_target_id` or LCARD control override).

```json
POST /api/presentation/products/godot-field-ops/show
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

Supported `event_type` categories:
- `TACTICAL_OBJECTIVE_COMPLETE`
- `HIGH_VALUE_TARGET_EXTRACTED`
- `MISSION_FAILED`
- `EXTRACTION_AVAILABLE`

---

### B. Threshold Affairs (`godot-threshold-affairs`) — Investigative Events

Default Target: `operator_desk` / `living_room_tv` (configurable via LCARD control override).

```json
POST /api/presentation/products/godot-threshold-affairs/show
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

Supported `event_type` categories:
- `EVIDENCE_COLLECTED`
- `ANOMALY_LOGGED`
- `CASE_BREAKTHROUGH`
- `CHRONO_DISRUPTION`

---

## 4. LCARD Target Override Contract

LCARD operator controls (`control-alt-lcard` `:8184`) can dynamically change Proscenium's active target for any game session by supplying `delivery_target_id` in the show payload:

```json
{
  "delivery_target_id": "arcade",
  "override_reason": "lcard_operator_select"
}
```

If `delivery_target_id` is omitted, Proscenium falls back to the default target declared in `config/presentation/delivery-targets.json`.
