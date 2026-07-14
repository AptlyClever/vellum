# Capture hosting decision — Epic batch MRQ (binding)

**Locked:** 2026-07-14  
**Owner:** implementer (not operator)  
**Operator does not pick paths.**

## Decision

**Primary capture backend:** Epic’s published **command-line Movie Render Queue** pattern:

1. Windows agent claims `ue_capture`
2. `run_vellum_capture.ps1` drives **UnrealEditor-Cmd** phases (studio → inventory → author Queue asset → render → ingest)
3. Render gate = **PNG artifacts on disk**, then vault ingest

**Authority:** [Batch Rendering with Command-Line (Epic Developer Community)](https://dev.epicgames.com/community/learning/tutorials/WWMD/unreal-engine-batch-rendering-with-command-line) — `UnrealEditor-Cmd` + `-unattended` + Python/queue execution + finish/quit. Same stack as Vellum’s Movie Render Queue capability spec (`docs/ue-mrq-capture.md`).

## Frozen (do not touch unless operator unparks)

**Warm Lookdev Worker** (`vellum_ue_worker_boot.py`, HTTP `:8771`, in-process executor on a long-lived GUI editor).

Reason: custom warm-daemon + inbox/outbox + mid-flight Python hotpatches is **not** the Epic batch tutorial path. It consumed implementer cycles, orphaned jobs, and failed with `mrq_never_started_rendering` while packs authored fine. Parked as experiment.

Unpark phrase (operator only): `Unpark: Lookdev Worker`.

## What this is not

- Not “legacy vs modern” — the whole Vellum capture stack is days old.
- Not Horde / multi-machine (parked).
- Not SceneCapture / HighResShot (retired in capability spec).
- Not asking the operator which path to use.

## Success

Slash / Ground (and remaining on-disk Niagara packs) reach **Ready** via Cmd batch MRQ + Live ops, without warm-worker surgery.
